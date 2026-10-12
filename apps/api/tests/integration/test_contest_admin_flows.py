"""Integration tests for the contest admin surface: admin-only enforcement on
every mutating endpoint, lifecycle (draft/publish/start/pause/resume/extend/
stop/duplicate/archive/delete), registration rules (window, cap, mode, access),
per-problem rules honoured by submit (unlock, attempts, languages), grace /
override audit trail, freeze + visibility, announcements, clarifications, CSV
export and certificate options. Piston is faked exactly as in
test_contest_flows.py (real local subprocess, no network).
"""
import asyncio
import subprocess
import sys
from datetime import timedelta

import pytest
from bson import ObjectId

from db import now_utc, users_col
from services import practice_service

pytestmark = pytest.mark.integration


class _FakeResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeAsyncClient:
    last_payload = None

    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, _url, json):
        _FakeAsyncClient.last_payload = json
        proc = subprocess.run(
            [sys.executable, "-c", json["files"][0]["content"]], input=json.get("stdin", ""),
            capture_output=True, text=True, timeout=10,
        )
        return _FakeResponse({"run": {"stdout": proc.stdout, "stderr": proc.stderr, "code": proc.returncode, "signal": None}})


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
    "        if target - n in seen:\n"
    "            return [seen[target - n], i]\n"
    "        seen[n] = i\n"
    "    return []\n"
)
WRONG_TWO_SUM = "def two_sum(nums, target):\n    return []\n"


def _admin(register_user):
    user, tokens, headers = register_user()
    asyncio.run(users_col.update_one({"_id": ObjectId(user["id"])}, {"$set": {"role": "admin"}}))
    return user, headers


def _iso(d):
    return d.isoformat()


def _mk(client, headers, settings=None, configs=None, problem_ids=None, start=timedelta(minutes=-5),
        end=timedelta(hours=1), state="published", name="Admin Test"):
    now = now_utc()
    body = {"name": name, "start_at": _iso(now + start), "end_at": _iso(now + end), "state": state,
            "problem_ids": problem_ids or ["two-sum", "contains-duplicate"], "ai_landing": False}
    if settings:
        body["settings"] = settings
    if configs:
        body["problem_configs"] = configs
    r = client.post("/api/contest/", json=body, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def _register(client, headers, cid, name="Solo", **extra):
    return client.post(f"/api/contest/{cid}/teams", json={"name": name, "member_emails": [], **extra}, headers=headers)


def _submit(client, headers, cid, code=CORRECT_TWO_SUM, pid="two-sum", lang="python"):
    return client.post(f"/api/contest/{cid}/problems/{pid}/submit", json={"code": code, "language": lang}, headers=headers)


# ---------------------------------------------------------------------------
# Authorization: every mutating admin endpoint is admin-only, server-side.
# ---------------------------------------------------------------------------
def test_every_mutating_endpoint_rejects_non_admins(client, register_user):
    _admin_user, admin_h = _admin(register_user)
    c = _mk(client, admin_h)
    cid = c["id"]
    _user, _t, h = register_user()
    calls = [
        ("post", "/api/contest/", {"name": "x", "start_at": "2026-01-01T00:00:00", "end_at": "2026-01-02T00:00:00"}),
        ("post", "/api/contest/from-template", {"template_id": "sprint-1h", "name": "x"}),
        ("patch", f"/api/contest/{cid}", {"name": "hijack"}),
        ("delete", f"/api/contest/{cid}", None),
        ("put", f"/api/contest/{cid}/problems", {"problems": [{"problem_id": "two-sum"}]}),
        ("post", f"/api/contest/{cid}/stop", None),
        ("post", f"/api/contest/{cid}/start-now", None),
        ("post", f"/api/contest/{cid}/pause", None),
        ("post", f"/api/contest/{cid}/resume", None),
        ("post", f"/api/contest/{cid}/extend", {"minutes": 5}),
        ("post", f"/api/contest/{cid}/archive", {"archived": True}),
        ("post", f"/api/contest/{cid}/duplicate", {}),
        ("post", f"/api/contest/{cid}/adjustments", {"team_id": "t", "reason": "because", "points": 5}),
        ("post", f"/api/contest/{cid}/rejudge", {"problem_id": "two-sum"}),
        ("post", f"/api/contest/{cid}/leaderboard/reveal", {"revealed": True}),
        ("post", f"/api/contest/{cid}/participants", {"email": "a@b.co"}),
        ("delete", f"/api/contest/{cid}/participants/xyz", None),
        ("delete", f"/api/contest/{cid}/teams/xyz", None),
        ("post", f"/api/contest/{cid}/teams/xyz/disqualify", {"reason": "cheating"}),
        ("post", f"/api/contest/{cid}/teams/xyz/reinstate", None),
        ("post", f"/api/contest/{cid}/participants/xyz/disqualify", {"reason": "cheating"}),
        ("post", f"/api/contest/{cid}/invites", {"emails": ["a@b.co"]}),
        ("post", f"/api/contest/{cid}/announcements", {"text": "hi"}),
        ("delete", f"/api/contest/{cid}/announcements/xyz", None),
        ("post", f"/api/contest/{cid}/clarifications/xyz/answer", {"answer": "no"}),
        ("post", f"/api/contest/{cid}/submissions/xyz/override", {"fraction": 1, "reason": "because"}),
        ("get", f"/api/contest/{cid}/admin", None),
        ("get", f"/api/contest/{cid}/audit", None),
        ("get", f"/api/contest/{cid}/participants", None),
        ("get", f"/api/contest/{cid}/export/standings.csv", None),
        ("get", f"/api/contest/{cid}/export/submissions.csv", None),
        ("get", f"/api/contest/{cid}/plagiarism", None),
    ]
    for method, url, body in calls:
        kwargs = {"headers": h}
        if body is not None:
            kwargs["json"] = body
        resp = getattr(client, method)(url, **kwargs)
        assert resp.status_code == 403, f"{method.upper()} {url} -> {resp.status_code}"
    # ...and they require authentication at all.
    assert client.delete(f"/api/contest/{cid}").status_code == 401
    # The contest is untouched.
    assert client.get(f"/api/contest/{cid}", headers=h).json()["name"] == "Admin Test"


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def test_draft_is_invisible_to_users_until_published(client, register_user):
    _a, ah = _admin(register_user)
    _u, _t, uh = register_user()
    c = _mk(client, ah, state="draft")
    assert c["status"] == "draft"
    assert client.get("/api/contest/", headers=uh).json()["items"] == []
    assert client.get(f"/api/contest/{c['id']}", headers=uh).status_code == 404
    assert _register(client, uh, c["id"]).status_code == 400
    assert [i["id"] for i in client.get("/api/contest/", headers=ah).json()["items"]] == [c["id"]]
    assert client.patch(f"/api/contest/{c['id']}", json={"state": "published"}, headers=ah).json()["status"] == "live"
    assert len(client.get("/api/contest/", headers=uh).json()["items"]) == 1


def test_start_now_pause_resume_extend_stop_cycle(client, register_user):
    _a, ah = _admin(register_user)
    _u, _t, uh = register_user()
    c = _mk(client, ah, start=timedelta(hours=2), end=timedelta(hours=3))
    cid = c["id"]
    assert c["status"] == "upcoming"
    assert client.post(f"/api/contest/{cid}/start-now", headers=ah).json()["status"] == "live"
    assert _register(client, uh, cid).status_code == 200

    assert client.post(f"/api/contest/{cid}/pause", headers=ah).json()["status"] == "paused"
    r = _submit(client, uh, cid)
    assert r.status_code == 403 and "paused" in r.text
    end_before = client.get(f"/api/contest/{cid}/admin", headers=ah).json()["end_at"]
    resumed = client.post(f"/api/contest/{cid}/resume", headers=ah).json()
    assert resumed["status"] == "live"
    assert resumed["end_at"] >= end_before  # paused time is returned to the contest
    assert _submit(client, uh, cid).status_code == 200

    ext = client.post(f"/api/contest/{cid}/extend", json={"minutes": 30}, headers=ah).json()
    assert ext["end_at"] > resumed["end_at"]
    assert client.post(f"/api/contest/{cid}/stop", headers=ah).json()["status"] == "ended"
    assert _submit(client, uh, cid).status_code == 403
    # Extending an ended contest deliberately reopens it.
    assert client.post(f"/api/contest/{cid}/extend", json={"minutes": 10}, headers=ah).json()["status"] == "live"
    assert client.post(f"/api/contest/{cid}/pause", headers=ah).status_code == 200
    assert client.post(f"/api/contest/{cid}/pause", headers=ah).status_code == 400  # not live any more


def test_duplicate_archive_delete(client, register_user):
    _a, ah = _admin(register_user)
    _u, _t, uh = register_user()
    c = _mk(client, ah, settings={"scoring": {"mode": "points"}})
    cid = c["id"]
    _register(client, uh, cid)
    dup = client.post(f"/api/contest/{cid}/duplicate", json={}, headers=ah).json()
    assert dup["name"].endswith("(copy)") and dup["state"] == "draft" and dup["id"] != cid
    dup_admin = client.get(f"/api/contest/{dup['id']}/admin", headers=ah).json()
    assert dup_admin["settings"]["scoring"]["mode"] == "points"
    assert dup_admin["team_count"] == 0  # participants never copied

    assert client.post(f"/api/contest/{cid}/archive", json={"archived": True}, headers=ah).json()["archived"] is True
    assert client.get("/api/contest/", headers=uh).json()["items"] == []
    assert client.delete(f"/api/contest/{cid}", headers=ah).status_code == 200
    assert client.get(f"/api/contest/{cid}", headers=ah).status_code == 404
    actions = [a["action"] for a in client.get(f"/api/contest/{dup['id']}/audit", headers=ah).json()["items"]]
    assert "duplicate" in actions


def test_invalid_settings_are_rejected_with_a_readable_error(client, register_user):
    _a, ah = _admin(register_user)
    now = now_utc()
    body = {"name": "x", "start_at": _iso(now), "end_at": _iso(now + timedelta(hours=1)),
            "settings": {"registration": {"min_team_size": 5, "max_team_size": 2}}}
    r = client.post("/api/contest/", json=body, headers=ah)
    assert r.status_code == 400 and "min_team_size" in r.text
    c = _mk(client, ah)
    r = client.patch(f"/api/contest/{c['id']}", json={"settings": {"scoring": {"mode": "nope"}}}, headers=ah)
    assert r.status_code == 400


def test_quick_create_from_template_is_a_live_contest_with_settings(client, register_user):
    _a, ah = _admin(register_user)
    tpls = client.get("/api/contest/templates", headers=ah).json()["items"]
    assert {t["id"] for t in tpls} >= {"sprint-1h", "points-weekend"}
    c = client.post("/api/contest/from-template", json={"template_id": "points-weekend", "name": "Quick"}, headers=ah).json()
    assert c["status"] == "live"
    admin = client.get(f"/api/contest/{c['id']}/admin", headers=ah).json()
    assert admin["settings"]["scoring"]["mode"] == "points"
    assert admin["problem_configs"][admin["problem_ids"][0]]["points"] == 50


# ---------------------------------------------------------------------------
# Open signup -> a brand-new user can reach and enter a contest with no admin help
# ---------------------------------------------------------------------------
def test_brand_new_user_can_discover_register_and_submit_with_default_settings(client, register_user):
    _a, ah = _admin(register_user)
    c = _mk(client, ah)
    # Fresh signup straight through the public register endpoint, nothing else.
    _u, _t, uh = register_user(name="Newcomer")
    listed = client.get("/api/contest/", headers=uh).json()["items"]
    assert [i["id"] for i in listed] == [c["id"]]
    detail = client.get(f"/api/contest/{c['id']}", headers=uh).json()
    assert detail["registration"]["open"] is True and detail["my_team"] is None
    assert _register(client, uh, c["id"]).status_code == 200
    r = _submit(client, uh, c["id"])
    assert r.status_code == 200 and r.json()["all_passed"] and r.json()["credits_used"] == 0


# ---------------------------------------------------------------------------
# Registration rules
# ---------------------------------------------------------------------------
def test_registration_cap_closes_the_contest_to_new_participants(client, register_user):
    _a, ah = _admin(register_user)
    c = _mk(client, ah, settings={"registration": {"cap": 1}})
    _u1, _t1, h1 = register_user()
    _u2, _t2, h2 = register_user()
    assert _register(client, h1, c["id"]).status_code == 200
    r = _register(client, h2, c["id"])
    assert r.status_code == 400 and "full" in r.text
    assert client.get(f"/api/contest/{c['id']}", headers=h2).json()["registration"]["open"] is False


def test_registration_window_and_manual_close(client, register_user):
    _a, ah = _admin(register_user)
    future = _iso(now_utc() + timedelta(hours=1))
    c = _mk(client, ah, settings={"registration": {"open_at": future}})
    _u, _t, h = register_user()
    r = _register(client, h, c["id"])
    assert r.status_code == 400 and "opens" in r.text
    client.patch(f"/api/contest/{c['id']}", json={"settings": {"registration": {"open_at": None, "open": False}}}, headers=ah)
    assert "closed" in _register(client, h, c["id"]).text
    client.patch(f"/api/contest/{c['id']}", json={"settings": {"registration": {"open": True}}}, headers=ah)
    assert _register(client, h, c["id"]).status_code == 200


def test_solo_only_and_team_only_modes(client, register_user):
    _a, ah = _admin(register_user)
    solo = _mk(client, ah, settings={"registration": {"mode": "solo"}}, name="Solo only")
    team = _mk(client, ah, settings={"registration": {"mode": "team", "min_team_size": 2}}, name="Teams only")
    u1, _t1, h1 = register_user()
    u2, _t2, h2 = register_user()
    r = client.post(f"/api/contest/{solo['id']}/teams", json={"name": "T", "member_emails": [u2["email"]]}, headers=h1)
    assert r.status_code == 400 and "1-1" in r.text
    assert _register(client, h1, solo["id"]).status_code == 200
    assert _register(client, h2, team["id"]).status_code == 400  # a team of one is not allowed
    ok = client.post(f"/api/contest/{team['id']}/teams", json={"name": "Duo", "member_emails": [u1["email"]]}, headers=h2)
    assert ok.status_code == 200


def test_invite_only_and_code_protected_access(client, register_user):
    _a, ah = _admin(register_user)
    inv = _mk(client, ah, settings={"registration": {"access": "invite_only"}}, name="Private")
    code = _mk(client, ah, settings={"registration": {"access": "code", "access_code": "s3cret"}}, name="Coded")
    u, _t, h = register_user(email="guest@example.com")
    assert "invite-only" in _register(client, h, inv["id"]).text
    res = client.post(f"/api/contest/{inv['id']}/invites", json={"emails": ["GUEST@example.com", "not-an-email"]}, headers=ah).json()
    assert res["added"] == ["guest@example.com"] and res["invalid"] == ["not-an-email"]
    assert _register(client, h, inv["id"]).status_code == 200

    assert "access code" in _register(client, h, code["id"]).text
    assert "access code" in _register(client, h, code["id"], access_code="wrong").text
    assert _register(client, h, code["id"], access_code="s3cret").status_code == 200
    # The code never leaks through the participant-facing payload.
    assert "s3cret" not in client.get(f"/api/contest/{code['id']}", headers=h).text


def test_admin_can_add_and_remove_participants_bypassing_rules(client, register_user):
    _a, ah = _admin(register_user)
    c = _mk(client, ah, settings={"registration": {"cap": 1, "open": False}})
    u, _t, h = register_user(email="manual@example.com")
    r = client.post(f"/api/contest/{c['id']}/participants", json={"email": "manual@example.com"}, headers=ah)
    assert r.status_code == 200
    rows = client.get(f"/api/contest/{c['id']}/participants?q=manual", headers=ah).json()["items"]
    assert len(rows) == 1 and rows[0]["email"] == "manual@example.com"
    assert client.post(f"/api/contest/{c['id']}/participants", json={"email": "ghost@example.com"}, headers=ah).status_code == 400
    assert client.delete(f"/api/contest/{c['id']}/participants/{u['id']}", headers=ah).status_code == 200
    assert client.get(f"/api/contest/{c['id']}/participants", headers=ah).json()["items"] == []


# ---------------------------------------------------------------------------
# Per-problem rules honoured by submit
# ---------------------------------------------------------------------------
def test_staged_unlock_blocks_submit_and_redacts_the_problem(client, register_user):
    _a, ah = _admin(register_user)
    c = _mk(client, ah, configs={"two-sum": {"release_after_minutes": 30}})
    _u, _t, h = register_user()
    _register(client, h, c["id"])
    r = _submit(client, h, c["id"])
    assert r.status_code == 403 and "unlocks" in r.text
    prob = next(p for p in client.get(f"/api/contest/{c['id']}", headers=h).json()["problems"] if p["id"] == "two-sum")
    assert prob["locked"] is True and prob["title"] == "Locked problem"
    # Admin sees it, and releasing the problem now lets submissions through.
    client.put(f"/api/contest/{c['id']}/problems", json={"problems": [{"problem_id": "two-sum", "release_after_minutes": 0}]}, headers=ah)
    assert _submit(client, h, c["id"]).status_code == 200


def test_max_attempts_is_enforced(client, register_user):
    _a, ah = _admin(register_user)
    c = _mk(client, ah, configs={"two-sum": {"max_attempts": 2}})
    _u, _t, h = register_user()
    _register(client, h, c["id"])
    first = _submit(client, h, c["id"], WRONG_TWO_SUM)
    assert first.status_code == 200 and first.json()["attempts_left"] == 1
    assert _submit(client, h, c["id"], WRONG_TWO_SUM).json()["attempts_left"] == 0
    r = _submit(client, h, c["id"])
    assert r.status_code == 403 and "attempts" in r.text


def test_allowed_languages_and_limits_are_applied(client, register_user):
    _a, ah = _admin(register_user)
    c = _mk(client, ah, configs={"two-sum": {"allowed_languages": ["javascript"], "time_limit_ms": 1500, "memory_limit_mb": 64}})
    _u, _t, h = register_user()
    _register(client, h, c["id"])
    r = _submit(client, h, c["id"])
    assert r.status_code == 400 and "javascript" in r.text
    # Loosen to python and check the sandbox limits reached the runner.
    client.put(f"/api/contest/{c['id']}/problems", json={"problems": [
        {"problem_id": "two-sum", "time_limit_ms": 1500, "memory_limit_mb": 64}]}, headers=ah)
    assert _submit(client, h, c["id"]).status_code == 200
    assert _FakeAsyncClient.last_payload["run_timeout"] == 1500
    assert _FakeAsyncClient.last_payload["run_memory_limit"] == 64 * 1024 * 1024


def test_problems_can_be_reordered_added_and_removed_while_live(client, register_user):
    _a, ah = _admin(register_user)
    c = _mk(client, ah)
    _u, _t, h = register_user()
    _register(client, h, c["id"])
    _submit(client, h, c["id"])
    r = client.put(f"/api/contest/{c['id']}/problems", json={"problems": [
        {"problem_id": "contains-duplicate", "points": 10}, {"problem_id": "valid-anagram", "points": 20},
    ]}, headers=ah)
    assert r.status_code == 200 and r.json()["problem_ids"] == ["contains-duplicate", "valid-anagram"]
    ids = [p["id"] for p in client.get(f"/api/contest/{c['id']}", headers=h).json()["problems"]]
    assert ids == ["contains-duplicate", "valid-anagram"]
    # two-sum was removed mid-contest: its solve no longer counts and it can't be submitted.
    assert client.get(f"/api/contest/{c['id']}/leaderboard", headers=h).json()["items"][0]["problems_solved"] == 0
    assert _submit(client, h, c["id"]).status_code == 400
    bad = client.put(f"/api/contest/{c['id']}/problems", json={"problems": [{"problem_id": "nope"}]}, headers=ah)
    assert bad.status_code == 400


# ---------------------------------------------------------------------------
# Scoring controls, audit, moderation
# ---------------------------------------------------------------------------
def test_grace_marks_override_and_audit_log(client, register_user):
    _a, ah = _admin(register_user)
    c = _mk(client, ah, settings={"scoring": {"mode": "points"}}, configs={"two-sum": {"points": 100}})
    _u, _t, h = register_user()
    team = _register(client, h, c["id"]).json()
    _submit(client, h, c["id"])
    lb = lambda: client.get(f"/api/contest/{c['id']}/leaderboard", headers=h).json()["items"][0]
    assert lb()["score"] == 100
    no_reason = client.post(f"/api/contest/{c['id']}/adjustments", json={"team_id": team["id"], "points": 5, "reason": ""}, headers=ah)
    assert no_reason.status_code == 422
    adj = client.post(f"/api/contest/{c['id']}/adjustments",
                      json={"team_id": team["id"], "points": 15, "reason": "network outage"}, headers=ah).json()
    assert lb()["score"] == 115
    client.post(f"/api/contest/{c['id']}/adjustments",
                json={"team_id": team["id"], "kind": "override", "points": 7, "reason": "manual review"}, headers=ah)
    assert lb()["score"] == 7
    client.delete(f"/api/contest/{c['id']}/adjustments/{adj['id']}", headers=ah)
    audit = client.get(f"/api/contest/{c['id']}/audit", headers=ah).json()["items"]
    actions = [a["action"] for a in audit]
    assert "adjust_grace" in actions and "adjust_override" in actions and "delete_adjustment" in actions
    assert any(a["details"].get("reason") == "network outage" for a in audit)


def test_disqualify_and_reinstate_team(client, register_user):
    _a, ah = _admin(register_user)
    c = _mk(client, ah)
    _u, _t, h = register_user()
    team = _register(client, h, c["id"]).json()
    _submit(client, h, c["id"])
    assert client.post(f"/api/contest/{c['id']}/teams/{team['id']}/disqualify", json={"reason": ""}, headers=ah).status_code == 400
    assert client.post(f"/api/contest/{c['id']}/teams/{team['id']}/disqualify", json={"reason": "plagiarism"}, headers=ah).status_code == 200
    assert client.get(f"/api/contest/{c['id']}/leaderboard", headers=h).json()["items"] == []  # hidden from the public board
    assert _submit(client, h, c["id"]).status_code == 403
    admin_rows = client.get(f"/api/contest/{c['id']}/leaderboard", headers=ah).json()["items"]
    assert admin_rows[0]["disqualified"] is True and admin_rows[0]["rank"] is None
    assert client.post(f"/api/contest/{c['id']}/teams/{team['id']}/reinstate", headers=ah).status_code == 200
    assert client.get(f"/api/contest/{c['id']}/leaderboard", headers=h).json()["items"][0]["rank"] == 1


def test_submission_override_invalidate_and_rejudge(client, register_user):
    _a, ah = _admin(register_user)
    c = _mk(client, ah)
    _u, _t, h = register_user()
    _register(client, h, c["id"])
    sid = _submit(client, h, c["id"]).json()["submission_id"]
    lb = lambda: client.get(f"/api/contest/{c['id']}/leaderboard", headers=h).json()["items"][0]["problems_solved"]
    assert lb() == 1
    assert client.post(f"/api/contest/{c['id']}/submissions/{sid}/override", json={"invalidated": True, "reason": "cheated"}, headers=ah).status_code == 200
    assert lb() == 0
    client.post(f"/api/contest/{c['id']}/submissions/{sid}/override", json={"invalidated": False, "reason": "mistake"}, headers=ah)
    assert lb() == 1
    r = client.post(f"/api/contest/{c['id']}/rejudge", json={"problem_id": "two-sum"}, headers=ah)
    assert r.status_code == 200 and r.json()["rejudged"] == 1
    assert client.get(f"/api/contest/{c['id']}/submissions", headers=ah).json()["items"][0]["rejudged_at"]


def test_duplicate_code_is_flagged(client, register_user):
    _a, ah = _admin(register_user)
    c = _mk(client, ah)
    for _ in range(2):
        _u, _t, h = register_user()
        _register(client, h, c["id"])
        _submit(client, h, c["id"])
    groups = client.get(f"/api/contest/{c['id']}/plagiarism", headers=ah).json()["items"]
    assert len(groups) == 1 and len(groups[0]["team_ids"]) == 2


# ---------------------------------------------------------------------------
# Leaderboard visibility / freeze / export
# ---------------------------------------------------------------------------
def test_freeze_hides_progress_from_participants_but_not_admins(client, register_user):
    _a, ah = _admin(register_user)
    # Frozen for the whole contest window (freeze 120 min on a 65 min contest).
    c = _mk(client, ah, settings={"leaderboard": {"freeze_minutes": 120}})
    _u, _t, h = register_user()
    _register(client, h, c["id"])
    _submit(client, h, c["id"])
    pub = client.get(f"/api/contest/{c['id']}/leaderboard", headers=h).json()
    assert pub["frozen"] is True and pub["items"][0]["problems_solved"] == 0
    live = client.get(f"/api/contest/{c['id']}/leaderboard", headers=ah).json()
    assert live["items"][0]["problems_solved"] == 1
    # Reveal lifts the freeze for everyone.
    client.post(f"/api/contest/{c['id']}/leaderboard/reveal", json={"revealed": True}, headers=ah)
    pub = client.get(f"/api/contest/{c['id']}/leaderboard", headers=h).json()
    assert pub["frozen"] is False and pub["items"][0]["problems_solved"] == 1


def test_hidden_leaderboard_returns_nothing_to_participants(client, register_user):
    _a, ah = _admin(register_user)
    c = _mk(client, ah, settings={"leaderboard": {"visibility": "hidden"}})
    _u, _t, h = register_user()
    _register(client, h, c["id"])
    _submit(client, h, c["id"])
    r = client.get(f"/api/contest/{c['id']}/leaderboard", headers=h).json()
    assert r["hidden"] is True and r["items"] == []
    assert client.get(f"/api/contest/{c['id']}/my-stats", headers=h).json()["team_rank"] is None


def test_csv_exports_and_formula_injection_is_neutralised(client, register_user):
    _a, ah = _admin(register_user)
    c = _mk(client, ah)
    _u, _t, h = register_user()
    client.post(f"/api/contest/{c['id']}/teams", json={"name": "=HYPERLINK(\"evil\")", "member_emails": []}, headers=h)
    _submit(client, h, c["id"])
    st = client.get(f"/api/contest/{c['id']}/export/standings.csv", headers=ah)
    assert st.status_code == 200 and st.headers["content-type"].startswith("text/csv")
    assert "'=HYPERLINK" in st.text and "\n=HYPERLINK" not in st.text and ",=HYPERLINK" not in st.text
    sub = client.get(f"/api/contest/{c['id']}/export/submissions.csv", headers=ah)
    assert "two-sum" in sub.text


# ---------------------------------------------------------------------------
# Announcements & clarifications
# ---------------------------------------------------------------------------
def test_announcements_reach_participants_and_pinned_come_first(client, register_user):
    _a, ah = _admin(register_user)
    c = _mk(client, ah)
    _u, _t, h = register_user()
    client.post(f"/api/contest/{c['id']}/announcements", json={"text": "first"}, headers=ah)
    pinned = client.post(f"/api/contest/{c['id']}/announcements", json={"text": "rules changed", "pinned": True}, headers=ah).json()
    client.post(f"/api/contest/{c['id']}/announcements", json={"text": "latest"}, headers=ah)
    items = client.get(f"/api/contest/{c['id']}/announcements", headers=h).json()["items"]
    assert [i["text"] for i in items][0] == "rules changed" and len(items) == 3
    client.delete(f"/api/contest/{c['id']}/announcements/{pinned['id']}", headers=ah)
    assert len(client.get(f"/api/contest/{c['id']}/announcements", headers=h).json()["items"]) == 2


def test_clarification_qa_with_public_and_private_answers(client, register_user):
    _a, ah = _admin(register_user)
    c = _mk(client, ah)
    _u1, _t1, h1 = register_user()
    _u2, _t2, h2 = register_user()
    _register(client, h1, c["id"])
    _register(client, h2, c["id"])
    # Non-participants cannot ask.
    _u3, _t3, h3 = register_user()
    assert client.post(f"/api/contest/{c['id']}/clarifications", json={"question": "hi?"}, headers=h3).status_code == 400
    q1 = client.post(f"/api/contest/{c['id']}/clarifications", json={"question": "Is input sorted?", "problem_id": "two-sum"}, headers=h1).json()
    q2 = client.post(f"/api/contest/{c['id']}/clarifications", json={"question": "Private thing"}, headers=h2).json()
    client.post(f"/api/contest/{c['id']}/clarifications/{q1['id']}/answer", json={"answer": "No.", "public": True}, headers=ah)
    client.post(f"/api/contest/{c['id']}/clarifications/{q2['id']}/answer", json={"answer": "Ok", "public": False}, headers=ah)
    seen_by_1 = {i["question"] for i in client.get(f"/api/contest/{c['id']}/clarifications", headers=h1).json()["items"]}
    assert seen_by_1 == {"Is input sorted?"}  # q2's answer is private to its author
    seen_by_2 = {i["question"] for i in client.get(f"/api/contest/{c['id']}/clarifications", headers=h2).json()["items"]}
    assert seen_by_2 == {"Is input sorted?", "Private thing"}
    assert len(client.get(f"/api/contest/{c['id']}/clarifications", headers=ah).json()["items"]) == 2


# ---------------------------------------------------------------------------
# Certificate options
# ---------------------------------------------------------------------------
def test_certificate_threshold_and_issue_after_end(client, register_user):
    _a, ah = _admin(register_user)
    c = _mk(client, ah, settings={"certificate": {"participation_min_solved": 1, "issue_after": "ended"}})
    _u, _t, h = register_user()
    _register(client, h, c["id"])
    _submit(client, h, c["id"], WRONG_TWO_SUM)
    assert client.get(f"/api/contest/{c['id']}/certificate", headers=h).status_code == 404  # contest still live
    client.post(f"/api/contest/{c['id']}/stop", headers=ah)
    assert "at least 1" in client.get(f"/api/contest/{c['id']}/certificate", headers=h).text  # solved nothing


def test_winner_certificate_for_top_n(client, register_user):
    import io
    import pypdf
    _a, ah = _admin(register_user)
    c = _mk(client, ah, settings={"certificate": {"winner_top_n": 1},
                                  "prizes": [{"from_rank": 1, "to_rank": 1, "title": "Champion", "prize": "Trophy"}]})
    _u, _t, h = register_user(name="Ada Lovelace")
    _register(client, h, c["id"])
    _submit(client, h, c["id"])
    client.post(f"/api/contest/{c['id']}/stop", headers=ah)
    stats = client.get(f"/api/contest/{c['id']}/my-stats", headers=h).json()
    assert stats["award"]["kind"] == "winner" and stats["prize"]["title"] == "Champion"
    pdf = client.get(f"/api/contest/{c['id']}/certificate", headers=h)
    text = pypdf.PdfReader(io.BytesIO(pdf.content)).pages[0].extract_text()
    assert "Achievement" in text and "Ada Lovelace" in text and "Champion" in text
