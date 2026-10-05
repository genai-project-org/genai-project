"""Integration tests for routers/contest_routes.py — Contest Mode's full HTTP
surface: admin-only contest creation, team signup (2-3 members, one team per
contest per user), the FREE contest-submit path with a real, enforced time
window, the leaderboard, and the certificate (PDF) / stats-card (PNG)
downloads.

Piston is never actually reached. `services.practice_service.httpx.AsyncClient`
is monkeypatched — the same call-site-level mocking pattern already used for
external HTTP in tests/unit/test_payments_service.py — to a fake client that
runs the harness-wrapped Python source through a REAL local subprocess. That
keeps grading genuine (actual Python semantics decide pass/fail, exactly like
the real Piston sandbox would) while keeping the suite fully hermetic: no
container, no network, ever.
"""
import asyncio
import subprocess
import sys
from datetime import timedelta
from io import BytesIO

import pypdf
import pytest
from bson import ObjectId
from PIL import Image

from db import now_utc, users_col
from services import practice_service

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fake Piston — see module docstring.
# ---------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, _url, json):
        source = json["files"][0]["content"]
        stdin = json.get("stdin", "")
        try:
            proc = subprocess.run(
                [sys.executable, "-c", source], input=stdin,
                capture_output=True, text=True, timeout=10,
            )
            run = {"stdout": proc.stdout, "stderr": proc.stderr, "code": proc.returncode, "signal": None}
        except subprocess.TimeoutExpired:
            run = {"stdout": "", "stderr": "timeout", "code": None, "signal": "SIGKILL"}
        return _FakeResponse({"run": run})


@pytest.fixture(autouse=True)
def _fake_piston(monkeypatch):
    monkeypatch.setattr(practice_service.httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(**kw))


@pytest.fixture(autouse=True)
def _seed_practice_problems():
    asyncio.run(practice_service.seed_problems())


CORRECT_TWO_SUM = (
    "def two_sum(nums, target):\n"
    "    seen = {}\n"
    "    for i, n in enumerate(nums):\n"
    "        need = target - n\n"
    "        if need in seen:\n"
    "            return [seen[need], i]\n"
    "        seen[n] = i\n"
    "    return []\n"
)

WRONG_TWO_SUM = "def two_sum(nums, target):\n    return []\n"


def _make_admin(register_user):
    """register_user() creates a plain `role: user` account — promote it to
    admin directly in mongomock, mirroring how routers/contest_routes.py's
    require_admin re-checks the DB role on every request (never trusts a
    stale JWT claim), so this promotion takes effect immediately."""
    user, tokens, headers = register_user()
    asyncio.run(users_col.update_one({"_id": ObjectId(user["id"])}, {"$set": {"role": "admin"}}))
    return user, tokens, headers


def _iso(dt):
    return dt.isoformat()


def _contest_payload(problem_ids=None, start_delta=timedelta(minutes=-1), end_delta=timedelta(hours=1), name="Hack Test"):
    now = now_utc()
    body = {"name": name, "start_at": _iso(now + start_delta), "end_at": _iso(now + end_delta)}
    if problem_ids is not None:
        body["problem_ids"] = problem_ids
    return body


def _create_contest(client, headers, **kwargs):
    resp = client.post("/api/contest/", json=_contest_payload(**kwargs), headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _create_team(client, headers, contest_id, teammate_email, name="Test Team"):
    resp = client.post(
        f"/api/contest/{contest_id}/teams",
        json={"name": name, "member_emails": [teammate_email]},
        headers=headers,
    )
    return resp


# ---------------------------------------------------------------------------
# Admin-only contest creation
# ---------------------------------------------------------------------------
def test_non_admin_cannot_create_contest(client, auth_user):
    _user, _tokens, headers = auth_user
    resp = client.post("/api/contest/", json=_contest_payload(), headers=headers)
    assert resp.status_code == 403


def test_admin_can_create_contest_with_default_problems(client, register_user):
    _admin, _tokens, headers = _make_admin(register_user)
    contest = _create_contest(client, headers)
    assert contest["problem_ids"] == ["two-sum", "contains-duplicate", "valid-anagram", "best-time-to-buy-sell-stock"]
    assert contest["status"] == "live"


def test_create_contest_rejects_unknown_problem_id(client, register_user):
    _admin, _tokens, headers = _make_admin(register_user)
    resp = client.post(
        "/api/contest/", json=_contest_payload(problem_ids=["not-a-real-problem"]), headers=headers,
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Time-window enforcement — the core "real deadline" requirement.
# ---------------------------------------------------------------------------
def test_submit_rejected_before_contest_starts(client, register_user):
    _admin, _tokens, admin_headers = _make_admin(register_user)
    contest = _create_contest(client, admin_headers, start_delta=timedelta(hours=1), end_delta=timedelta(hours=2))

    _user, _tokens, headers = register_user()
    resp = client.post(
        f"/api/contest/{contest['id']}/problems/two-sum/submit",
        json={"code": CORRECT_TWO_SUM, "language": "python"},
        headers=headers,
    )
    assert resp.status_code == 403
    assert "hasn't started" in resp.json()["detail"]


def test_submit_rejected_after_contest_ends(client, register_user):
    _admin, _tokens, admin_headers = _make_admin(register_user)
    contest = _create_contest(client, admin_headers, start_delta=timedelta(hours=-2), end_delta=timedelta(hours=-1))

    _user, _tokens, headers = register_user()
    resp = client.post(
        f"/api/contest/{contest['id']}/problems/two-sum/submit",
        json={"code": CORRECT_TWO_SUM, "language": "python"},
        headers=headers,
    )
    assert resp.status_code == 403
    assert "has ended" in resp.json()["detail"]


def test_team_cannot_be_formed_after_contest_ends(client, register_user):
    _admin, _tokens, admin_headers = _make_admin(register_user)
    contest = _create_contest(client, admin_headers, start_delta=timedelta(hours=-2), end_delta=timedelta(hours=-1))

    user, _tokens, headers = register_user()
    mate, _tokens2, _headers2 = register_user()
    resp = _create_team(client, headers, contest["id"], mate["email"])
    assert resp.status_code == 400
    assert "already ended" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Teams: 2-3 members, one team per user per contest.
# ---------------------------------------------------------------------------
def test_create_team_allows_solo_registration(client, register_user):
    """Solo participation is a real, valid path — not everyone shows up with
    a pre-formed squad."""
    _admin, _tokens, admin_headers = _make_admin(register_user)
    contest = _create_contest(client, admin_headers)

    user, _tokens, headers = register_user()
    resp = client.post(
        f"/api/contest/{contest['id']}/teams", json={"name": "Solo", "member_emails": []}, headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["member_user_ids"] == [user["id"]]


def test_create_team_still_rejects_more_than_3_members(client, register_user):
    _admin, _tokens, admin_headers = _make_admin(register_user)
    contest = _create_contest(client, admin_headers)

    user, _tokens, headers = register_user()
    m2, _t2, _h2 = register_user()
    m3, _t3, _h3 = register_user()
    m4, _t4, _h4 = register_user()
    resp = client.post(
        f"/api/contest/{contest['id']}/teams",
        json={"name": "Too Big", "member_emails": [m2["email"], m3["email"], m4["email"]]},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "1-3 members" in resp.json()["detail"]


def test_create_team_with_valid_size_succeeds(client, register_user):
    _admin, _tokens, admin_headers = _make_admin(register_user)
    contest = _create_contest(client, admin_headers)

    user, _tokens, headers = register_user()
    mate, _tokens2, _headers2 = register_user()
    resp = _create_team(client, headers, contest["id"], mate["email"])
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body["member_user_ids"]) == {user["id"], mate["id"]}


def test_user_can_only_be_on_one_team_per_contest(client, register_user):
    _admin, _tokens, admin_headers = _make_admin(register_user)
    contest = _create_contest(client, admin_headers)

    user, _tokens, headers = register_user()
    mate, _tokens2, _headers2 = register_user()
    other, _tokens3, other_headers = register_user()

    resp1 = _create_team(client, headers, contest["id"], mate["email"], name="First Team")
    assert resp1.status_code == 200, resp1.text

    # `mate` tries to also form/join a second team in the SAME contest — rejected.
    resp2 = _create_team(client, other_headers, contest["id"], mate["email"], name="Second Team")
    assert resp2.status_code == 400
    assert "already on a team" in resp2.json()["detail"]


def test_get_my_team_reflects_membership(client, register_user):
    _admin, _tokens, admin_headers = _make_admin(register_user)
    contest = _create_contest(client, admin_headers)

    user, _tokens, headers = register_user()
    mate, _tokens2, _headers2 = register_user()
    _create_team(client, headers, contest["id"], mate["email"])

    resp = client.get(f"/api/contest/{contest['id']}/team/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["team"] is not None

    lonely, _tokens3, lonely_headers = register_user()
    resp2 = client.get(f"/api/contest/{contest['id']}/team/me", headers=lonely_headers)
    assert resp2.json()["team"] is None


# ---------------------------------------------------------------------------
# Contest submission — free, real grading, requires a team.
# ---------------------------------------------------------------------------
def test_submit_requires_a_team(client, register_user):
    _admin, _tokens, admin_headers = _make_admin(register_user)
    contest = _create_contest(client, admin_headers)

    user, _tokens, headers = register_user()
    resp = client.post(
        f"/api/contest/{contest['id']}/problems/two-sum/submit",
        json={"code": CORRECT_TWO_SUM, "language": "python"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "team" in resp.json()["detail"].lower()


def test_submit_rejects_a_problem_not_in_the_contest(client, register_user):
    _admin, _tokens, admin_headers = _make_admin(register_user)
    contest = _create_contest(client, admin_headers, problem_ids=["two-sum"])

    user, _tokens, headers = register_user()
    mate, _tokens2, _headers2 = register_user()
    _create_team(client, headers, contest["id"], mate["email"])

    resp = client.post(
        f"/api/contest/{contest['id']}/problems/binary-search/submit",
        json={"code": "def search(nums, target):\n    return -1\n", "language": "python"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "not part of this contest" in resp.json()["detail"]


def test_submit_during_window_is_graded_for_real_and_costs_no_credits(client, register_user):
    _admin, _tokens, admin_headers = _make_admin(register_user)
    contest = _create_contest(client, admin_headers)

    user, _tokens, headers = register_user()
    mate, _tokens2, _headers2 = register_user()
    _create_team(client, headers, contest["id"], mate["email"])

    balance_before = client.get("/api/wallet/", headers=headers).json()["total"]

    resp = client.post(
        f"/api/contest/{contest['id']}/problems/two-sum/submit",
        json={"code": CORRECT_TWO_SUM, "language": "python"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["all_passed"] is True
    assert body["credits_used"] == 0
    assert body["free"] is True

    balance_after = client.get("/api/wallet/", headers=headers).json()["total"]
    assert balance_after == balance_before  # genuinely free — not merely a discounted price


def test_submit_a_wrong_solution_is_recorded_as_not_passed(client, register_user):
    _admin, _tokens, admin_headers = _make_admin(register_user)
    contest = _create_contest(client, admin_headers)

    user, _tokens, headers = register_user()
    mate, _tokens2, _headers2 = register_user()
    _create_team(client, headers, contest["id"], mate["email"])

    resp = client.post(
        f"/api/contest/{contest['id']}/problems/two-sum/submit",
        json={"code": WRONG_TWO_SUM, "language": "python"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["all_passed"] is False


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------
def test_leaderboard_reflects_a_real_submission(client, register_user):
    _admin, _tokens, admin_headers = _make_admin(register_user)
    contest = _create_contest(client, admin_headers)

    user, _tokens, headers = register_user()
    mate, _tokens2, _headers2 = register_user()
    team_resp = _create_team(client, headers, contest["id"], mate["email"], name="Leaderboard Team")
    team_id = team_resp.json()["id"]

    client.post(
        f"/api/contest/{contest['id']}/problems/two-sum/submit",
        json={"code": CORRECT_TWO_SUM, "language": "python"},
        headers=headers,
    )

    resp = client.get(f"/api/contest/{contest['id']}/leaderboard", headers=headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["team_id"] == team_id
    assert items[0]["problems_solved"] == 1
    assert items[0]["rank"] == 1
    assert resp.json()["top5"] == items[:5]


def test_leaderboard_is_visible_to_any_authenticated_participant_not_just_the_team(client, register_user):
    """Leaderboard visibility must never be gated — any authenticated user in
    the app can see full contest standings, not only contest participants."""
    _admin, _tokens, admin_headers = _make_admin(register_user)
    contest = _create_contest(client, admin_headers)

    bystander, _tokens, bystander_headers = register_user()
    resp = client.get(f"/api/contest/{contest['id']}/leaderboard", headers=bystander_headers)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Certificate (PDF) + stats card (PNG)
# ---------------------------------------------------------------------------
def test_certificate_404s_for_a_non_participant(client, register_user):
    _admin, _tokens, admin_headers = _make_admin(register_user)
    contest = _create_contest(client, admin_headers)

    user, _tokens, headers = register_user()
    resp = client.get(f"/api/contest/{contest['id']}/certificate", headers=headers)
    assert resp.status_code == 404


def test_certificate_is_a_real_pdf_with_the_users_real_name(client, register_user):
    _admin, _tokens, admin_headers = _make_admin(register_user)
    contest = _create_contest(client, admin_headers)

    user, _tokens, headers = register_user(name="Certificate Recipient")
    mate, _tokens2, _headers2 = register_user()
    _create_team(client, headers, contest["id"], mate["email"])

    client.post(
        f"/api/contest/{contest['id']}/problems/two-sum/submit",
        json={"code": WRONG_TWO_SUM, "language": "python"},  # even a FAILED submission counts as participation
        headers=headers,
    )

    resp = client.get(f"/api/contest/{contest['id']}/certificate", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"

    reader = pypdf.PdfReader(BytesIO(resp.content))
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    assert "Certificate Recipient" in text
    assert contest["name"] in text


def test_stats_card_404s_for_a_non_participant(client, register_user):
    _admin, _tokens, admin_headers = _make_admin(register_user)
    contest = _create_contest(client, admin_headers)

    user, _tokens, headers = register_user()
    resp = client.get(f"/api/contest/{contest['id']}/stats-card", headers=headers)
    assert resp.status_code == 404


def test_stats_card_is_a_real_png_with_correct_solved_count(client, register_user):
    _admin, _tokens, admin_headers = _make_admin(register_user)
    contest = _create_contest(client, admin_headers, problem_ids=["two-sum", "contains-duplicate"])

    user, _tokens, headers = register_user()
    mate, _tokens2, _headers2 = register_user()
    _create_team(client, headers, contest["id"], mate["email"])

    client.post(
        f"/api/contest/{contest['id']}/problems/two-sum/submit",
        json={"code": CORRECT_TWO_SUM, "language": "python"},
        headers=headers,
    )

    stats_resp = client.get(f"/api/contest/{contest['id']}/my-stats", headers=headers)
    assert stats_resp.json()["problems_solved"] == 1
    assert stats_resp.json()["total_contest_problems"] == 2

    resp = client.get(f"/api/contest/{contest['id']}/stats-card", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"

    img = Image.open(BytesIO(resp.content))
    img.load()
    assert img.format == "PNG"
    assert img.size == (1200, 630)


# ---------------------------------------------------------------------------
# Admin "stop contest now" — real, immediate end regardless of end_at.
# ---------------------------------------------------------------------------
def test_non_admin_cannot_stop_a_contest(client, register_user):
    _admin, _tokens, admin_headers = _make_admin(register_user)
    contest = _create_contest(client, admin_headers)

    _user, _tokens, headers = register_user()
    resp = client.post(f"/api/contest/{contest['id']}/stop", headers=headers)
    assert resp.status_code == 403


def test_admin_stop_contest_immediately_rejects_a_submission(client, register_user):
    _admin, _tokens, admin_headers = _make_admin(register_user)
    contest = _create_contest(client, admin_headers)  # live: started 1 min ago, ends in 1 hour

    user, _tokens, headers = register_user()
    mate, _tokens2, _headers2 = register_user()
    _create_team(client, headers, contest["id"], mate["email"])

    stop_resp = client.post(f"/api/contest/{contest['id']}/stop", headers=admin_headers)
    assert stop_resp.status_code == 200, stop_resp.text
    assert stop_resp.json()["status"] == "ended"
    assert stop_resp.json()["ended_early"] is True

    # A submission attempted immediately after must be rejected exactly like
    # one made after the original deadline — not merely a DB flag flip.
    resp = client.post(
        f"/api/contest/{contest['id']}/problems/two-sum/submit",
        json={"code": CORRECT_TWO_SUM, "language": "python"},
        headers=headers,
    )
    assert resp.status_code == 403
    assert "has ended" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# Open teams — solo registration + "join an open team" without knowing
# anyone's email in advance.
# ---------------------------------------------------------------------------
def test_open_team_join_flow_end_to_end(client, register_user):
    """Register solo + mark open -> a second, unrelated user finds it via the
    open-teams list and joins with no email/invite -> both are real members,
    verifiable via /team/me."""
    _admin, _tokens, admin_headers = _make_admin(register_user)
    contest = _create_contest(client, admin_headers)

    opener, _tokens, opener_headers = register_user()
    resp = client.post(
        f"/api/contest/{contest['id']}/teams",
        json={"name": "Find Me", "member_emails": [], "open_to_join": True},
        headers=opener_headers,
    )
    assert resp.status_code == 200, resp.text
    team_id = resp.json()["id"]

    open_resp = client.get(f"/api/contest/{contest['id']}/teams/open", headers=opener_headers)
    assert open_resp.status_code == 200
    items = open_resp.json()["items"]
    assert any(t["id"] == team_id and t["member_count"] == 1 and t["spots_left"] == 2 for t in items)

    joiner, _tokens2, joiner_headers = register_user()
    join_resp = client.post(f"/api/contest/{contest['id']}/teams/{team_id}/join", headers=joiner_headers)
    assert join_resp.status_code == 200, join_resp.text
    assert set(join_resp.json()["member_user_ids"]) == {opener["id"], joiner["id"]}

    me_resp = client.get(f"/api/contest/{contest['id']}/team/me", headers=joiner_headers)
    assert me_resp.json()["team"]["id"] == team_id


def test_cannot_join_an_open_team_youre_already_on_a_team_for(client, register_user):
    _admin, _tokens, admin_headers = _make_admin(register_user)
    contest = _create_contest(client, admin_headers)

    opener, _tokens, opener_headers = register_user()
    team_id = client.post(
        f"/api/contest/{contest['id']}/teams",
        json={"name": "Open", "member_emails": [], "open_to_join": True},
        headers=opener_headers,
    ).json()["id"]

    already_teamed, _tokens2, already_headers = register_user()
    client.post(
        f"/api/contest/{contest['id']}/teams",
        json={"name": "Already Has One", "member_emails": []},
        headers=already_headers,
    )
    resp = client.post(f"/api/contest/{contest['id']}/teams/{team_id}/join", headers=already_headers)
    assert resp.status_code == 400
    assert "already on a team" in resp.json()["detail"]
