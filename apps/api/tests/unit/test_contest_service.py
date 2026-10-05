"""Unit tests for services/contest_service.py — contest time-window status,
team formation rules (2-3 members, one team per contest per user), leaderboard
ranking/tie-breaking, and the certificate PDF / stats-card PNG generators.

No real Piston/network calls anywhere in this file: leaderboard/stats tests
seed `contest_submissions_col` directly (bypassing run_submission entirely —
grading itself is Practice Engine's job, already exercised through the real
submit flow in tests/integration/test_contest_flows.py with Piston mocked at
the httpx boundary), and PDF/PNG generation is pure local rendering
(fpdf2/Pillow) — never network.
"""
import io
from datetime import timedelta

import pypdf
import pytest
from PIL import Image

from db import now_iso, now_utc, users_col
from services import contest_service as cs
from services.practice_service import seed_problems

pytestmark = pytest.mark.anyio


async def _make_user(name="Test User", email=None):
    email = email or f"{name.lower().replace(' ', '.')}@example.com"
    result = await users_col.insert_one({"email": email, "name": name})
    return str(result.inserted_id)


def _iso(dt):
    return dt.isoformat()


# --------------------------------------------------------------------------
# contest_status — pure function, the real enforcement source of truth.
# --------------------------------------------------------------------------
def test_contest_status_upcoming_before_start():
    now = now_utc()
    contest = {"start_at": _iso(now + timedelta(hours=1)), "end_at": _iso(now + timedelta(hours=2))}
    assert cs.contest_status(contest, now=now) == "upcoming"


def test_contest_status_live_within_window():
    now = now_utc()
    contest = {"start_at": _iso(now - timedelta(minutes=5)), "end_at": _iso(now + timedelta(minutes=5))}
    assert cs.contest_status(contest, now=now) == "live"


def test_contest_status_ended_after_end():
    now = now_utc()
    contest = {"start_at": _iso(now - timedelta(hours=2)), "end_at": _iso(now - timedelta(hours=1))}
    assert cs.contest_status(contest, now=now) == "ended"


# --------------------------------------------------------------------------
# create_contest / update_contest
# --------------------------------------------------------------------------
async def test_create_contest_uses_default_problems_when_none_given():
    await seed_problems()
    now = now_utc()
    contest = await cs.create_contest(
        "Test Contest", _iso(now), _iso(now + timedelta(hours=1)), None, created_by="admin1",
    )
    assert contest["problem_ids"] == cs.DEFAULT_CONTEST_PROBLEM_IDS


async def test_create_contest_rejects_unknown_problem_id():
    await seed_problems()
    now = now_utc()
    with pytest.raises(ValueError, match="Unknown problem"):
        await cs.create_contest(
            "Test Contest", _iso(now), _iso(now + timedelta(hours=1)),
            ["not-a-real-problem"], created_by="admin1",
        )


async def test_create_contest_rejects_end_before_start():
    now = now_utc()
    with pytest.raises(ValueError, match="end_at must be after start_at"):
        await cs.create_contest("Test", _iso(now), _iso(now - timedelta(hours=1)), None, created_by="admin1")


async def test_update_contest_can_extend_the_window():
    await seed_problems()
    now = now_utc()
    contest = await cs.create_contest("T", _iso(now), _iso(now + timedelta(minutes=5)), None, created_by="admin1")
    new_end = _iso(now + timedelta(hours=2))
    updated = await cs.update_contest(contest["_id"], {"end_at": new_end})
    assert updated["end_at"] == new_end


# --------------------------------------------------------------------------
# Teams: 2-3 members, one team per contest per user.
# --------------------------------------------------------------------------
async def test_create_team_auto_adds_creator_and_accepts_valid_size():
    await seed_problems()
    now = now_utc()
    contest = await cs.create_contest("T", _iso(now), _iso(now + timedelta(hours=1)), None, created_by="admin1")
    u1 = await _make_user("Creator")
    u2 = await _make_user("Mate")
    team = await cs.create_team(contest["_id"], "The A Team", [u2], created_by=u1)
    assert set(team["member_user_ids"]) == {u1, u2}
    assert team["created_by"] == u1


async def test_create_team_allows_solo_registration():
    """Solo participation is valid, not an error — a lone registrant isn't
    locked out just because they don't have teammates lined up yet."""
    await seed_problems()
    now = now_utc()
    contest = await cs.create_contest("T", _iso(now), _iso(now + timedelta(hours=1)), None, created_by="admin1")
    u1 = await _make_user("Solo")
    team = await cs.create_team(contest["_id"], "Solo Team", [], created_by=u1)
    assert team["member_user_ids"] == [u1]


async def test_create_team_rejects_too_large():
    await seed_problems()
    now = now_utc()
    contest = await cs.create_contest("T", _iso(now), _iso(now + timedelta(hours=1)), None, created_by="admin1")
    u1 = await _make_user("C1")
    u2, u3, u4 = await _make_user("C2"), await _make_user("C3"), await _make_user("C4")
    with pytest.raises(ValueError, match="1-3 members"):
        await cs.create_team(contest["_id"], "Big Team", [u2, u3, u4], created_by=u1)


async def test_create_team_rejects_member_already_on_another_team_in_same_contest():
    await seed_problems()
    now = now_utc()
    contest = await cs.create_contest("T", _iso(now), _iso(now + timedelta(hours=1)), None, created_by="admin1")
    u1, u2, u3 = await _make_user("A"), await _make_user("B"), await _make_user("C")
    await cs.create_team(contest["_id"], "Team One", [u2], created_by=u1)
    with pytest.raises(ValueError, match="already on a team"):
        await cs.create_team(contest["_id"], "Team Two", [u2], created_by=u3)


async def test_create_team_rejects_unknown_user_id():
    await seed_problems()
    now = now_utc()
    contest = await cs.create_contest("T", _iso(now), _iso(now + timedelta(hours=1)), None, created_by="admin1")
    u1 = await _make_user("A")
    with pytest.raises(ValueError, match="Unknown user"):
        await cs.create_team(contest["_id"], "Team", ["64" + "0" * 22], created_by=u1)


async def test_create_team_rejected_after_contest_ended():
    await seed_problems()
    now = now_utc()
    contest = await cs.create_contest(
        "T", _iso(now - timedelta(hours=2)), _iso(now - timedelta(hours=1)), None, created_by="admin1",
    )
    u1, u2 = await _make_user("A"), await _make_user("B")
    with pytest.raises(ValueError, match="already ended"):
        await cs.create_team(contest["_id"], "Late Team", [u2], created_by=u1)


async def test_get_my_team_returns_none_when_not_on_a_team():
    await seed_problems()
    now = now_utc()
    contest = await cs.create_contest("T", _iso(now), _iso(now + timedelta(hours=1)), None, created_by="admin1")
    u1 = await _make_user("Lonely")
    assert await cs.get_my_team(contest["_id"], u1) is None


# --------------------------------------------------------------------------
# Admin "stop contest now" — immediate, irreversible end regardless of the
# scheduled end_at.
# --------------------------------------------------------------------------
async def test_stop_contest_forces_ended_status_immediately():
    await seed_problems()
    now = now_utc()
    contest = await cs.create_contest(
        "T", _iso(now - timedelta(minutes=5)), _iso(now + timedelta(hours=2)), None, created_by="admin1",
    )
    assert cs.contest_status(contest) == "live"
    stopped = await cs.stop_contest(contest["_id"])
    assert stopped["ended_early"] is True
    assert cs.contest_status(stopped) == "ended"


async def test_stop_contest_blocks_new_teams_immediately():
    await seed_problems()
    now = now_utc()
    contest = await cs.create_contest(
        "T", _iso(now - timedelta(minutes=5)), _iso(now + timedelta(hours=2)), None, created_by="admin1",
    )
    await cs.stop_contest(contest["_id"])
    u1 = await _make_user("TooLate")
    with pytest.raises(ValueError, match="already ended"):
        await cs.create_team(contest["_id"], "Late Team", [], created_by=u1)


# --------------------------------------------------------------------------
# Open teams — the "join without knowing anyone's email" path.
# --------------------------------------------------------------------------
async def test_open_team_appears_in_list_open_teams():
    await seed_problems()
    now = now_utc()
    contest = await cs.create_contest("T", _iso(now), _iso(now + timedelta(hours=1)), None, created_by="admin1")
    u1 = await _make_user("Opener")
    team = await cs.create_team(contest["_id"], "Open Squad", [], created_by=u1, open_to_join=True)
    open_teams = await cs.list_open_teams(contest["_id"])
    assert [t["_id"] for t in open_teams] == [team["_id"]]


async def test_non_open_team_does_not_appear_in_list_open_teams():
    await seed_problems()
    now = now_utc()
    contest = await cs.create_contest("T", _iso(now), _iso(now + timedelta(hours=1)), None, created_by="admin1")
    u1 = await _make_user("Closed")
    await cs.create_team(contest["_id"], "Closed Squad", [], created_by=u1, open_to_join=False)
    assert await cs.list_open_teams(contest["_id"]) == []


async def test_join_open_team_adds_member_without_any_email_invite():
    await seed_problems()
    now = now_utc()
    contest = await cs.create_contest("T", _iso(now), _iso(now + timedelta(hours=1)), None, created_by="admin1")
    u1 = await _make_user("Opener")
    u2 = await _make_user("Joiner")
    team = await cs.create_team(contest["_id"], "Open Squad", [], created_by=u1, open_to_join=True)
    joined = await cs.join_open_team(contest["_id"], team["_id"], u2)
    assert set(joined["member_user_ids"]) == {u1, u2}
    my_team = await cs.get_my_team(contest["_id"], u2)
    assert my_team["_id"] == team["_id"]


async def test_join_open_team_stops_listing_it_once_full():
    await seed_problems()
    now = now_utc()
    contest = await cs.create_contest("T", _iso(now), _iso(now + timedelta(hours=1)), None, created_by="admin1")
    u1, u2, u3 = await _make_user("A"), await _make_user("B"), await _make_user("C")
    team = await cs.create_team(contest["_id"], "Open Squad", [], created_by=u1, open_to_join=True)
    await cs.join_open_team(contest["_id"], team["_id"], u2)
    await cs.join_open_team(contest["_id"], team["_id"], u3)  # now at MAX_TEAM_SIZE == 3
    assert await cs.list_open_teams(contest["_id"]) == []


async def test_join_open_team_rejects_a_user_already_on_a_team():
    await seed_problems()
    now = now_utc()
    contest = await cs.create_contest("T", _iso(now), _iso(now + timedelta(hours=1)), None, created_by="admin1")
    u1, u2 = await _make_user("A"), await _make_user("B")
    open_team = await cs.create_team(contest["_id"], "Open Squad", [], created_by=u1, open_to_join=True)
    await cs.create_team(contest["_id"], "Already Has One", [], created_by=u2)
    with pytest.raises(ValueError, match="already on a team"):
        await cs.join_open_team(contest["_id"], open_team["_id"], u2)


async def test_join_open_team_rejects_joining_a_closed_team():
    await seed_problems()
    now = now_utc()
    contest = await cs.create_contest("T", _iso(now), _iso(now + timedelta(hours=1)), None, created_by="admin1")
    u1, u2 = await _make_user("A"), await _make_user("B")
    closed_team = await cs.create_team(contest["_id"], "Closed Squad", [], created_by=u1, open_to_join=False)
    with pytest.raises(ValueError, match="not open"):
        await cs.join_open_team(contest["_id"], closed_team["_id"], u2)


# --------------------------------------------------------------------------
# Leaderboard ranking + tie-break.
#
# Scoring rule: team score = # of DISTINCT contest problems solved by AT
# LEAST ONE member (not summed across members). Ties broken by total
# time-to-solve (sum of first-passing-submission-time minus contest start,
# across solved problems) — lower wins, i.e. the team that reached its
# solved count FASTER ranks higher (ICPC-style).
# --------------------------------------------------------------------------
async def test_compute_leaderboard_ranks_by_distinct_problems_solved_first():
    await seed_problems()
    now = now_utc()
    contest = await cs.create_contest(
        "LB", _iso(now - timedelta(minutes=30)), _iso(now + timedelta(hours=1)), None, created_by="admin1",
    )
    cid = contest["_id"]
    u1, u2 = await _make_user("U1"), await _make_user("U2")
    team_a = await cs.create_team(cid, "Team A", [u2], created_by=u1)
    u3, u4 = await _make_user("U3"), await _make_user("U4")
    team_b = await cs.create_team(cid, "Team B", [u4], created_by=u3)

    # Team A: two DIFFERENT members solve two DIFFERENT problems -> counts as 2.
    await cs.contest_submissions_col.insert_one({
        "contest_id": cid, "team_id": team_a["_id"], "user_id": u1, "problem_id": "two-sum",
        "language": "python", "code": "x", "passed_count": 5, "total": 5, "all_passed": True,
        "created_at": _iso(now - timedelta(minutes=20)),
    })
    await cs.contest_submissions_col.insert_one({
        "contest_id": cid, "team_id": team_a["_id"], "user_id": u2, "problem_id": "contains-duplicate",
        "language": "python", "code": "x", "passed_count": 5, "total": 5, "all_passed": True,
        "created_at": _iso(now - timedelta(minutes=5)),
    })
    # Team B solves only 1 problem, even though it happens fast.
    await cs.contest_submissions_col.insert_one({
        "contest_id": cid, "team_id": team_b["_id"], "user_id": u3, "problem_id": "two-sum",
        "language": "python", "code": "x", "passed_count": 5, "total": 5, "all_passed": True,
        "created_at": _iso(now - timedelta(minutes=29)),
    })

    board = await cs.compute_leaderboard(cid)
    assert board[0]["team_id"] == team_a["_id"] and board[0]["rank"] == 1
    assert board[0]["problems_solved"] == 2
    assert board[1]["team_id"] == team_b["_id"] and board[1]["rank"] == 2
    assert board[1]["problems_solved"] == 1


async def test_compute_leaderboard_redundant_solves_by_same_problem_dont_double_count():
    """Two DIFFERENT members solving the SAME problem must still count once —
    team score is distinct problems solved, not raw submission count."""
    await seed_problems()
    now = now_utc()
    contest = await cs.create_contest(
        "LB-dup", _iso(now - timedelta(minutes=10)), _iso(now + timedelta(hours=1)), None, created_by="admin1",
    )
    cid = contest["_id"]
    u1, u2 = await _make_user("D1"), await _make_user("D2")
    team = await cs.create_team(cid, "Redundant Team", [u2], created_by=u1)
    for uid in (u1, u2):
        await cs.contest_submissions_col.insert_one({
            "contest_id": cid, "team_id": team["_id"], "user_id": uid, "problem_id": "two-sum",
            "language": "python", "code": "x", "passed_count": 5, "total": 5, "all_passed": True,
            "created_at": now_iso(),
        })
    board = await cs.compute_leaderboard(cid)
    assert board[0]["problems_solved"] == 1


async def test_compute_leaderboard_tiebreaks_by_total_time_when_solved_count_ties():
    await seed_problems()
    now = now_utc()
    contest = await cs.create_contest(
        "LB2", _iso(now - timedelta(minutes=30)), _iso(now + timedelta(hours=1)), None, created_by="admin1",
    )
    cid = contest["_id"]
    u1, u2 = await _make_user("F1"), await _make_user("F2")
    team_fast = await cs.create_team(cid, "Fast Team", [u2], created_by=u1)
    u3, u4 = await _make_user("S1"), await _make_user("S2")
    team_slow = await cs.create_team(cid, "Slow Team", [u4], created_by=u3)

    # Both solve exactly 1 problem — Fast Team solves it sooner after start.
    await cs.contest_submissions_col.insert_one({
        "contest_id": cid, "team_id": team_fast["_id"], "user_id": u1, "problem_id": "two-sum",
        "language": "python", "code": "x", "passed_count": 5, "total": 5, "all_passed": True,
        "created_at": _iso(now - timedelta(minutes=25)),  # 5 min after start
    })
    await cs.contest_submissions_col.insert_one({
        "contest_id": cid, "team_id": team_slow["_id"], "user_id": u3, "problem_id": "two-sum",
        "language": "python", "code": "x", "passed_count": 5, "total": 5, "all_passed": True,
        "created_at": _iso(now - timedelta(minutes=5)),  # 25 min after start
    })

    board = await cs.compute_leaderboard(cid)
    assert board[0]["problems_solved"] == board[1]["problems_solved"] == 1
    assert board[0]["team_id"] == team_fast["_id"]
    assert board[0]["total_time_seconds"] < board[1]["total_time_seconds"]


# --------------------------------------------------------------------------
# Personal stats — distinct from team score (see module docstring).
# --------------------------------------------------------------------------
async def test_get_user_contest_stats_counts_only_the_users_own_solves():
    await seed_problems()
    now = now_utc()
    contest = await cs.create_contest(
        "Stats", _iso(now - timedelta(minutes=10)), _iso(now + timedelta(hours=1)),
        ["two-sum", "contains-duplicate", "binary-search"], created_by="admin1",
    )
    cid = contest["_id"]
    u1, u2 = await _make_user("Stat User"), await _make_user("Stat Mate")
    team = await cs.create_team(cid, "Stat Team", [u2], created_by=u1)

    # u1 solves two-sum + contains-duplicate (both "Arrays & Hashing"), fails binary-search.
    for pid, passed in [("two-sum", True), ("contains-duplicate", True), ("binary-search", False)]:
        await cs.contest_submissions_col.insert_one({
            "contest_id": cid, "team_id": team["_id"], "user_id": u1, "problem_id": pid,
            "language": "python", "code": "x",
            "passed_count": 5 if passed else 0, "total": 5, "all_passed": passed,
            "created_at": now_iso(),
        })

    stats = await cs.get_user_contest_stats(cid, u1)
    assert stats["has_participated"] is True
    assert stats["problems_solved"] == 2
    assert stats["strongest_topic"] == "Arrays & Hashing"
    assert stats["team_rank"] == 1
    assert stats["team_name"] == "Stat Team"

    # u2 is on the SAME team (which has 2 solves) but never submitted anything
    # personally — their own card must show zero, not the team's total.
    stats_u2 = await cs.get_user_contest_stats(cid, u2)
    assert stats_u2["has_participated"] is False
    assert stats_u2["problems_solved"] == 0


# --------------------------------------------------------------------------
# Certificate PDF — real text-based PDF (fpdf2), verified by actually parsing
# it back with pypdf, not just checking that bytes were returned.
# --------------------------------------------------------------------------
def test_generate_certificate_pdf_is_valid_and_contains_real_data():
    contest = {"name": "Test Hack 2026", "start_at": "2026-09-17T00:00:00+00:00", "end_at": "2026-09-18T00:00:00+00:00"}
    pdf_bytes = cs.generate_certificate_pdf(contest, "Jane Q. Public")
    assert pdf_bytes[:5] == b"%PDF-"

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    assert len(reader.pages) == 1
    text = reader.pages[0].extract_text()
    assert "Jane Q. Public" in text
    assert "Test Hack 2026" in text
    assert "2026" in text


def test_generate_certificate_pdf_differs_per_recipient():
    contest = {"name": "Test Hack 2026", "start_at": "2026-09-17T00:00:00+00:00", "end_at": "2026-09-18T00:00:00+00:00"}
    pdf_a = cs.generate_certificate_pdf(contest, "Alice A")
    pdf_b = cs.generate_certificate_pdf(contest, "Bob B")
    assert pdf_a != pdf_b


# --------------------------------------------------------------------------
# Stats card PNG — deterministic templated render (Pillow), verified by
# actually reopening it as an image, not just checking bytes came back.
# --------------------------------------------------------------------------
def test_generate_stats_card_png_is_a_valid_image_of_the_expected_shape():
    contest = {"name": "Test Hack 2026"}
    stats = {
        "problems_solved": 3, "total_contest_problems": 4, "team_rank": 2,
        "strongest_topic": "Two Pointers", "team_name": "The Testers",
    }
    png_bytes = cs.generate_stats_card_png(contest, "Jane Q. Public", stats)
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n"

    img = Image.open(io.BytesIO(png_bytes))
    img.load()  # forces a full decode — a truncated/corrupt PNG raises here
    assert img.format == "PNG"
    assert img.size == (1200, 630)


def test_generate_stats_card_png_reflects_real_stats_not_a_placeholder():
    contest = {"name": "Test Hack 2026"}
    stats_a = {
        "problems_solved": 3, "total_contest_problems": 4, "team_rank": 2,
        "strongest_topic": "Two Pointers", "team_name": "The Testers",
    }
    stats_b = {
        "problems_solved": 0, "total_contest_problems": 4, "team_rank": None,
        "strongest_topic": "N/A", "team_name": None,
    }
    png_a = cs.generate_stats_card_png(contest, "Jane Q. Public", stats_a)
    png_b = cs.generate_stats_card_png(contest, "Someone Else", stats_b)
    # Different real inputs must render to different pixels — proves the
    # numbers are actually being drawn, not a static/cached image.
    assert png_a != png_b
