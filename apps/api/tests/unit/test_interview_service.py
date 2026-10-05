"""Unit tests for services/interview_service.py — entitlements (a list of
per-pack "grants", each carrying its own snapshotted config, not one flat
wallet-style counter), session lifecycle/state machine, and the
single-flight/time-window guardrails.
"""
from datetime import timedelta

import pytest
from fastapi import HTTPException

from db import interview_sessions_col, now_utc
from services import interview_service

pytestmark = pytest.mark.anyio

QUICK_CONFIG = {
    "technical_minutes": 30, "behavioral_minutes": 0,
    "topics": ["dsa", "hld", "lld", "design", "hr"],
    "seniority_levels": ["entry", "mid"],
    "languages": ["python", "javascript"],
    "sub_topics": {},
}
FULL_CONFIG = {
    "technical_minutes": 45, "behavioral_minutes": 15,
    "topics": ["dsa", "hld", "lld", "design", "hr"],
    "seniority_levels": ["entry", "mid", "senior"],
    "languages": ["python", "javascript", "cpp", "java"],
    "sub_topics": {"dsa": ["graphs", "dynamic_programming"]},
}


@pytest.fixture(autouse=True)
def _no_report_generation(monkeypatch):
    """Report generation calls the real Anthropic client — not something a
    hermetic unit test should ever reach. `_kick_off_report` looks up
    `interview_report_service.generate_report` lazily at call time, so
    patching the module attribute here is enough."""
    from services import interview_report_service

    async def _noop(session_id):
        return None

    monkeypatch.setattr(interview_report_service, "generate_report", _noop)


@pytest.fixture(autouse=True)
def _fake_agent_opening(monkeypatch):
    """interview_agent.run_turn calls the real Anthropic client — stub it for
    start_session's opening-greeting call, same as elsewhere in this suite."""
    from services import interview_agent

    async def _fake_run_turn(session, history, candidate_text, resume_doc, minutes_remaining, questions_asked):
        return {
            "interviewer_text": "Welcome! Let's get started — tell me about a recent project.",
            "tool_calls": [], "end_requested": False, "end_reason": None,
            "messages": history + [{"role": "user", "content": candidate_text}],
        }

    monkeypatch.setattr(interview_agent, "run_turn", _fake_run_turn)


async def _grant(user_id="user-1", sessions=1, config=FULL_CONFIG, name="Interview Prep Pack", slug="interview-prep-usd"):
    pack = {"id": "pack-1", "slug": slug, "name": name, "config": config}
    return await interview_service.grant_sessions(user_id, sessions, pack=pack, ref_id="pay-1")


# ------------------------------ entitlements ------------------------------

async def test_get_entitlement_defaults_to_empty_for_new_user():
    result = await interview_service.get_entitlement("user-1")
    assert result == {"sessions_remaining": 0, "grants": []}


async def test_grant_sessions_creates_a_grant_with_snapshotted_config():
    granted = await _grant(sessions=5)
    assert granted["sessions_total"] == 5
    assert granted["sessions_remaining"] == 5
    assert granted["pack_slug"] == "interview-prep-usd"
    assert granted["config"] == FULL_CONFIG

    result = await interview_service.get_entitlement("user-1")
    assert result["sessions_remaining"] == 5
    assert len(result["grants"]) == 1
    assert result["grants"][0]["grant_id"] == granted["grant_id"]


async def test_two_different_pack_purchases_stay_as_separate_grants():
    await _grant(sessions=2, config=QUICK_CONFIG, name="Starter Pack", slug="interview-starter-usd")
    await _grant(sessions=5, config=FULL_CONFIG, name="Interview Prep Pack", slug="interview-prep-usd")
    result = await interview_service.get_entitlement("user-1")
    assert result["sessions_remaining"] == 7
    assert len(result["grants"]) == 2
    configs = {g["pack_slug"]: g["config"] for g in result["grants"]}
    assert configs["interview-starter-usd"] == QUICK_CONFIG
    assert configs["interview-prep-usd"] == FULL_CONFIG


async def test_admin_grant_with_no_pack_falls_back_to_default_config():
    granted = await interview_service.grant_sessions("user-1", 3, tx_type="admin_grant", description="goodwill credit")
    assert granted["config"] == interview_service.DEFAULT_GRANT_CONFIG


async def test_precheck_and_reserve_consumes_one_session_from_that_grant():
    granted = await _grant(sessions=2)
    tx_id = await interview_service.precheck_and_reserve("user-1", granted["grant_id"])
    assert tx_id
    result = await interview_service.get_entitlement("user-1")
    assert result["grants"][0]["sessions_remaining"] == 1


async def test_precheck_and_reserve_raises_402_when_grant_exhausted():
    granted = await _grant(sessions=1)
    await interview_service.precheck_and_reserve("user-1", granted["grant_id"])
    with pytest.raises(HTTPException) as exc_info:
        await interview_service.precheck_and_reserve("user-1", granted["grant_id"])
    assert exc_info.value.status_code == 402


async def test_precheck_and_reserve_raises_404_for_someone_elses_grant():
    granted = await _grant(user_id="user-1", sessions=1)
    with pytest.raises(HTTPException) as exc_info:
        await interview_service.precheck_and_reserve("user-2", granted["grant_id"])
    assert exc_info.value.status_code == 404


async def test_refund_session_restores_that_grant_without_touching_total():
    granted = await _grant(sessions=3)
    tx_id = await interview_service.precheck_and_reserve("user-1", granted["grant_id"])
    await interview_service.refund_session("user-1", granted["grant_id"], tx_id, "test refund")
    result = await interview_service.get_entitlement("user-1")
    assert result["grants"][0] == granted  # back to exactly the pre-consume state


# ------------------------------ session creation & configurability ------------------------------

async def test_create_session_consumes_the_chosen_grant_and_snapshots_its_durations():
    granted = await _grant(sessions=1, config=FULL_CONFIG)
    doc = await interview_service.create_session("user-1", granted["grant_id"], "dsa", "mid")
    assert doc["status"] == "created"
    assert doc["current_round"] == "technical"
    assert doc["technical_minutes"] == 45
    assert doc["behavioral_minutes"] == 15
    assert doc["include_behavioral"] is True
    entitlement = await interview_service.get_entitlement("user-1")
    assert entitlement["sessions_remaining"] == 0


async def test_create_session_on_a_no_behavioral_pack_forces_include_behavioral_false():
    granted = await _grant(sessions=1, config=QUICK_CONFIG)
    doc = await interview_service.create_session("user-1", granted["grant_id"], "dsa", "mid")
    assert doc["include_behavioral"] is False
    assert doc["behavioral_minutes"] == 0
    assert doc["technical_minutes"] == 30


async def test_create_session_rejects_topic_not_covered_by_the_grants_pack():
    quick = {**QUICK_CONFIG, "topics": ["hr"]}
    granted = await _grant(sessions=1, config=quick)
    with pytest.raises(HTTPException) as exc_info:
        await interview_service.create_session("user-1", granted["grant_id"], "dsa", "mid")
    assert exc_info.value.status_code == 400


async def test_create_session_rejects_seniority_not_offered_by_the_pack():
    granted = await _grant(sessions=1, config=QUICK_CONFIG)  # only entry/mid
    with pytest.raises(HTTPException) as exc_info:
        await interview_service.create_session("user-1", granted["grant_id"], "dsa", "senior")
    assert exc_info.value.status_code == 400


async def test_create_session_rejects_sub_topic_not_offered_for_that_topic():
    granted = await _grant(sessions=1, config=FULL_CONFIG)  # dsa sub_topics: graphs, dynamic_programming
    with pytest.raises(HTTPException) as exc_info:
        await interview_service.create_session("user-1", granted["grant_id"], "dsa", "mid", sub_topic="quantum_computing")
    assert exc_info.value.status_code == 400


async def test_create_session_accepts_a_valid_sub_topic_and_language():
    granted = await _grant(sessions=1, config=FULL_CONFIG)
    doc = await interview_service.create_session(
        "user-1", granted["grant_id"], "dsa", "senior", sub_topic="graphs", language="cpp",
    )
    assert doc["sub_topic"] == "graphs"
    assert doc["language"] == "cpp"


async def test_create_session_rejects_language_not_offered_by_the_pack():
    granted = await _grant(sessions=1, config=QUICK_CONFIG)  # only python/javascript
    with pytest.raises(HTTPException) as exc_info:
        await interview_service.create_session("user-1", granted["grant_id"], "dsa", "mid", language="cpp")
    assert exc_info.value.status_code == 400


async def test_create_session_rejects_opting_into_behavioral_on_a_pack_without_it():
    granted = await _grant(sessions=1, config=QUICK_CONFIG)  # behavioral_minutes: 0
    with pytest.raises(HTTPException) as exc_info:
        await interview_service.create_session("user-1", granted["grant_id"], "dsa", "mid", include_behavioral=True)
    assert exc_info.value.status_code == 400


async def test_create_session_lets_candidate_opt_out_of_behavioral_on_a_full_pack():
    granted = await _grant(sessions=1, config=FULL_CONFIG)
    doc = await interview_service.create_session(
        "user-1", granted["grant_id"], "dsa", "mid", include_behavioral=False,
    )
    assert doc["include_behavioral"] is False
    assert doc["behavioral_minutes"] == 0
    assert doc["technical_minutes"] == 45  # technical duration is unaffected by skipping behavioral


async def test_create_session_lets_candidate_shorten_technical_round_to_fit_their_schedule():
    granted = await _grant(sessions=1, config=FULL_CONFIG)  # default 45+15
    doc = await interview_service.create_session(
        "user-1", granted["grant_id"], "dsa", "mid", include_behavioral=False, technical_minutes=15,
    )
    assert doc["technical_minutes"] == 15
    assert doc["behavioral_minutes"] == 0


async def test_create_session_lets_candidate_lengthen_within_bounds():
    granted = await _grant(sessions=1, config=FULL_CONFIG)
    doc = await interview_service.create_session(
        "user-1", granted["grant_id"], "dsa", "mid", technical_minutes=60, behavioral_minutes=20,
    )
    assert doc["technical_minutes"] == 60
    assert doc["behavioral_minutes"] == 20


async def test_create_session_rejects_technical_minutes_out_of_bounds():
    granted = await _grant(sessions=1, config=FULL_CONFIG)
    with pytest.raises(HTTPException) as exc_info:
        await interview_service.create_session("user-1", granted["grant_id"], "dsa", "mid", technical_minutes=5)
    assert exc_info.value.status_code == 400

    granted2 = await _grant(sessions=1, config=FULL_CONFIG)
    with pytest.raises(HTTPException) as exc_info2:
        await interview_service.create_session("user-1", granted2["grant_id"], "dsa", "mid", technical_minutes=200)
    assert exc_info2.value.status_code == 400


async def test_create_session_rejects_behavioral_minutes_out_of_bounds_only_when_included():
    granted = await _grant(sessions=1, config=FULL_CONFIG)
    with pytest.raises(HTTPException) as exc_info:
        await interview_service.create_session(
            "user-1", granted["grant_id"], "dsa", "mid", include_behavioral=True, behavioral_minutes=1,
        )
    assert exc_info.value.status_code == 400

    # An out-of-range behavioral_minutes is simply ignored when the round isn't included at all.
    granted2 = await _grant(sessions=1, config=FULL_CONFIG)
    doc = await interview_service.create_session(
        "user-1", granted2["grant_id"], "dsa", "mid", include_behavioral=False, behavioral_minutes=1,
    )
    assert doc["behavioral_minutes"] == 0


async def test_create_session_requires_a_valid_grant():
    with pytest.raises(HTTPException) as exc_info:
        await interview_service.create_session("user-1", "not-a-real-grant", "dsa", "mid")
    assert exc_info.value.status_code == 404


async def test_create_session_admin_bypass_needs_no_grant_and_consumes_nothing():
    doc = await interview_service.create_session("admin-1", None, "dsa", "senior", is_admin=True)
    assert doc["status"] == "created"
    assert doc["grant_id"] is None
    assert doc["entitlement_tx_id"] is None
    assert doc["technical_minutes"] == interview_service.DEFAULT_GRANT_CONFIG["technical_minutes"]
    # No entitlement doc was ever created/touched for this user.
    entitlement = await interview_service.get_entitlement("admin-1")
    assert entitlement == {"sessions_remaining": 0, "grants": []}


async def test_create_session_non_admin_cannot_omit_grant_id():
    with pytest.raises(HTTPException) as exc_info:
        await interview_service.create_session("user-1", None, "dsa", "mid", is_admin=False)
    assert exc_info.value.status_code == 400


async def test_create_session_blocks_second_concurrent_session():
    granted = await _grant(sessions=2, config=FULL_CONFIG)
    await interview_service.create_session("user-1", granted["grant_id"], "dsa", "mid")
    with pytest.raises(HTTPException) as exc_info:
        await interview_service.create_session("user-1", granted["grant_id"], "hld", "mid")
    assert exc_info.value.status_code == 409
    # The blocked attempt must NOT have consumed a second session from the grant.
    entitlement = await interview_service.get_entitlement("user-1")
    assert entitlement["sessions_remaining"] == 1


# ------------------------------ time-based state machine ------------------------------

async def test_technical_round_advances_to_behavioral_when_pack_includes_it():
    granted = await _grant(sessions=1, config=FULL_CONFIG)
    session = await interview_service.create_session("user-1", granted["grant_id"], "dsa", "mid")
    past = (now_utc() - timedelta(minutes=1)).isoformat()
    await interview_sessions_col.update_one(
        {"_id": session["_id"]},
        {"$set": {"status": "technical_in_progress", "technical_started_at": past, "technical_ends_at": past}},
    )
    updated = await interview_service._advance_time_based_transitions(
        await interview_sessions_col.find_one({"_id": session["_id"]})
    )
    assert updated["status"] == "behavioral_in_progress"
    assert updated["current_round"] == "behavioral"
    assert updated["behavioral_ends_at"] is not None


async def test_technical_round_completes_directly_when_pack_has_no_behavioral():
    granted = await _grant(sessions=1, config=QUICK_CONFIG)
    session = await interview_service.create_session("user-1", granted["grant_id"], "dsa", "mid")
    past = (now_utc() - timedelta(minutes=1)).isoformat()
    await interview_sessions_col.update_one(
        {"_id": session["_id"]},
        {"$set": {"status": "technical_in_progress", "technical_started_at": past, "technical_ends_at": past}},
    )
    updated = await interview_service._advance_time_based_transitions(
        await interview_sessions_col.find_one({"_id": session["_id"]})
    )
    assert updated["status"] == "completed"
    assert updated["ended_at"] is not None


async def test_behavioral_round_completes_once_window_elapses():
    granted = await _grant(sessions=1, config=FULL_CONFIG)
    session = await interview_service.create_session("user-1", granted["grant_id"], "dsa", "mid")
    past = (now_utc() - timedelta(minutes=1)).isoformat()
    await interview_sessions_col.update_one(
        {"_id": session["_id"]},
        {"$set": {"status": "behavioral_in_progress", "current_round": "behavioral",
                  "behavioral_started_at": past, "behavioral_ends_at": past}},
    )
    updated = await interview_service._advance_time_based_transitions(
        await interview_sessions_col.find_one({"_id": session["_id"]})
    )
    assert updated["status"] == "completed"
    assert updated["ended_at"] is not None


async def test_get_status_reports_active_session():
    granted = await _grant(sessions=1, config=FULL_CONFIG)
    session = await interview_service.create_session("user-1", granted["grant_id"], "dsa", "mid")
    status = await interview_service.get_status(session["_id"], "user-1")
    assert status["session_status"] == "created"
    assert status["warning_count"] == 0


async def test_start_session_generates_opening_and_starts_the_clock():
    granted = await _grant(sessions=1, config=FULL_CONFIG)
    session = await interview_service.create_session("user-1", granted["grant_id"], "dsa", "mid")
    assert session["status"] == "created"

    result = await interview_service.start_session(session["_id"], "user-1")
    assert result["session_status"] == "technical_in_progress"
    assert "Welcome" in result["interviewer_text"]
    assert result["minutes_remaining"] == 45

    updated = await interview_sessions_col.find_one({"_id": session["_id"]})
    assert updated["status"] == "technical_in_progress"
    assert updated["technical_ends_at"] is not None

    first_turn = await interview_service.interview_turns_col.find_one({"session_id": session["_id"], "turn_index": 0})
    assert first_turn["speaker"] == "interviewer"


async def test_start_session_is_idempotent_on_refresh():
    granted = await _grant(sessions=1, config=FULL_CONFIG)
    session = await interview_service.create_session("user-1", granted["grant_id"], "dsa", "mid")
    first = await interview_service.start_session(session["_id"], "user-1")
    second = await interview_service.start_session(session["_id"], "user-1")
    assert second["interviewer_text"] == first["interviewer_text"]
    # No second opening call/turn was generated.
    count = await interview_service.interview_turns_col.count_documents({"session_id": session["_id"]})
    assert count == 1


async def test_end_session_early_refunds_when_no_content_yet():
    granted = await _grant(sessions=1, config=FULL_CONFIG)
    session = await interview_service.create_session("user-1", granted["grant_id"], "dsa", "mid")
    result = await interview_service.end_session_early(session["_id"], "user-1")
    assert result["session_status"] == "abandoned"
    entitlement = await interview_service.get_entitlement("user-1")
    assert entitlement["sessions_remaining"] == 1  # refunded
