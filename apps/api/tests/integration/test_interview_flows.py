"""Integration tests for routers/interview_routes.py — the full HTTP surface:
entitlement, session creation, a turn, proctoring violations, and early end.

The interviewer agent's tool-use loop (services/interview_agent.run_turn) is
monkeypatched to a canned response — it calls a real Anthropic client, which
this hermetic suite must never reach (no ANTHROPIC_API_KEY is set for tests).
Everything else (session state machine, entitlement consumption, transcript
persistence, proctoring's atomic warning count) runs for real against the
mongomock database, exactly like every other integration test in this suite.
"""
import pytest

from services import interview_agent, interview_report_service, interview_service

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _fake_agent_and_report(monkeypatch):
    async def _fake_run_turn(session, history, candidate_text, resume_doc, minutes_remaining, questions_asked):
        return {
            "interviewer_text": f"Thanks — tell me more about: {candidate_text[:40]}",
            "tool_calls": [],
            "end_requested": False,
            "end_reason": None,
            "messages": history + [{"role": "user", "content": candidate_text}],
        }

    async def _noop_report(session_id):
        return None

    monkeypatch.setattr(interview_agent, "run_turn", _fake_run_turn)
    monkeypatch.setattr(interview_report_service, "generate_report", _noop_report)


FULL_CONFIG = {
    "technical_minutes": 45, "behavioral_minutes": 15,
    "topics": ["dsa", "hld", "lld", "design", "hr"],
    "seniority_levels": ["entry", "mid", "senior"],
    "languages": ["python", "javascript", "cpp", "java"],
    "sub_topics": {"dsa": ["graphs", "dynamic_programming"]},
}


async def _grant(user_id: str, sessions: int = 1, config=FULL_CONFIG):
    pack = {"id": "pack-1", "slug": "interview-prep-usd", "name": "Interview Prep Pack", "config": config}
    return await interview_service.grant_sessions(user_id, sessions, pack=pack, ref_id="test-grant")


def test_entitlement_defaults_to_zero(client, register_user):
    _user, _tokens, headers = register_user()
    resp = client.get("/api/interview/entitlement", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"sessions_remaining": 0, "grants": []}


def test_create_session_requires_a_grant_id(client, register_user):
    _user, _tokens, headers = register_user()
    resp = client.post("/api/interview/sessions", json={"grant_id": "no-such-grant", "topic": "dsa", "seniority": "mid"}, headers=headers)
    assert resp.status_code == 404


def test_full_turn_and_end_flow(client, register_user):
    import asyncio
    user, _tokens, headers = register_user()
    asyncio.run(_grant(user["id"]))

    entitlement = client.get("/api/interview/entitlement", headers=headers).json()
    assert entitlement["sessions_remaining"] == 1
    grant_id = entitlement["grants"][0]["grant_id"]
    assert entitlement["grants"][0]["config"] == FULL_CONFIG

    create_resp = client.post(
        "/api/interview/sessions",
        json={"grant_id": grant_id, "topic": "dsa", "seniority": "senior", "sub_topic": "graphs", "language": "cpp"},
        headers=headers,
    )
    assert create_resp.status_code == 200, create_resp.text
    session_id = create_resp.json()["id"]
    assert create_resp.json()["status"] == "created"
    assert create_resp.json()["technical_minutes"] == 45
    assert create_resp.json()["include_behavioral"] is True

    # A "created" session must not accept a second one for the same user —
    # note the grant is now exhausted (0 remaining) anyway, but the 409 for an
    # already-active session must fire before any entitlement check would.
    second_resp = client.post(
        "/api/interview/sessions", json={"grant_id": grant_id, "topic": "hld", "seniority": "mid"}, headers=headers,
    )
    assert second_resp.status_code == 409

    turn_resp = client.post(
        f"/api/interview/sessions/{session_id}/turn",
        data={"modality": "text", "text": "I'd use a hash map for O(1) lookups."},
        headers=headers,
    )
    assert turn_resp.status_code == 200, turn_resp.text
    body = turn_resp.json()
    assert body["session_status"] == "technical_in_progress"
    assert body["round"] == "technical"
    assert "hash map" in body["interviewer_text"]
    assert body["warning_count"] == 0

    status_resp = client.get(f"/api/interview/sessions/{session_id}/status", headers=headers)
    assert status_resp.status_code == 200
    assert status_resp.json()["session_status"] == "technical_in_progress"

    end_resp = client.post(f"/api/interview/sessions/{session_id}/end", headers=headers)
    assert end_resp.status_code == 200
    assert end_resp.json()["session_status"] == "completed"  # had content (one turn) — not refunded as abandoned


def test_proctoring_violations_escalate_to_termination(client, register_user):
    import asyncio
    user, _tokens, headers = register_user()
    asyncio.run(_grant(user["id"]))
    grant_id = client.get("/api/interview/entitlement", headers=headers).json()["grants"][0]["grant_id"]

    session_id = client.post(
        "/api/interview/sessions", json={"grant_id": grant_id, "topic": "hr", "seniority": "mid"}, headers=headers,
    ).json()["id"]
    # Enter an active round so the violation endpoint accepts reports.
    client.post(f"/api/interview/sessions/{session_id}/turn",
               data={"modality": "text", "text": "Hi, ready to start."}, headers=headers)

    r1 = client.post(f"/api/interview/sessions/{session_id}/violations",
                     data={"type": "tab_blur"}, headers=headers)
    assert r1.json() == {"warning_count": 1, "warnings_remaining": 2, "terminated": False}

    r2 = client.post(f"/api/interview/sessions/{session_id}/violations",
                     data={"type": "face_not_visible"}, headers=headers)
    assert r2.json()["terminated"] is False

    r3 = client.post(f"/api/interview/sessions/{session_id}/violations",
                     data={"type": "multiple_faces"}, headers=headers)
    assert r3.json()["terminated"] is True

    status_resp = client.get(f"/api/interview/sessions/{session_id}/status", headers=headers)
    assert status_resp.json()["session_status"] == "terminated_violations"

    # A session-continuing action (another turn) must be rejected once terminated.
    dead_turn = client.post(f"/api/interview/sessions/{session_id}/turn",
                            data={"modality": "text", "text": "still there?"}, headers=headers)
    assert dead_turn.json()["session_status"] == "terminated_violations"


QUICK_CONFIG = {
    "technical_minutes": 30, "behavioral_minutes": 0,
    "topics": ["hr"],  # only HR unlocked on this (deliberately narrow) grant
    "seniority_levels": ["entry", "mid"],
    "languages": ["python"],
    "sub_topics": {},
}


def test_session_setup_is_bound_by_the_chosen_grants_pack_config(client, register_user):
    """A candidate can only pick topic/seniority/language/behavioral-inclusion
    within whatever the SPECIFIC grant they're spending was configured with —
    this is the whole point of per-pack configurability."""
    import asyncio
    user, _tokens, headers = register_user()
    asyncio.run(_grant(user["id"], config=QUICK_CONFIG))
    grant_id = client.get("/api/interview/entitlement", headers=headers).json()["grants"][0]["grant_id"]

    wrong_topic = client.post("/api/interview/sessions",
                              json={"grant_id": grant_id, "topic": "dsa", "seniority": "mid"}, headers=headers)
    assert wrong_topic.status_code == 400

    wrong_seniority = client.post("/api/interview/sessions",
                                  json={"grant_id": grant_id, "topic": "hr", "seniority": "senior"}, headers=headers)
    assert wrong_seniority.status_code == 400

    wants_behavioral = client.post("/api/interview/sessions",
                                   json={"grant_id": grant_id, "topic": "hr", "seniority": "mid", "include_behavioral": True},
                                   headers=headers)
    assert wants_behavioral.status_code == 400

    ok = client.post("/api/interview/sessions",
                     json={"grant_id": grant_id, "topic": "hr", "seniority": "mid"}, headers=headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["include_behavioral"] is False


def test_admin_grant_with_pack_id_snapshots_that_packs_config(client, register_user):
    import asyncio
    from bson import ObjectId
    from db import interview_packs_col, users_col

    admin_user, _admin_tokens, admin_headers = register_user()
    asyncio.run(users_col.update_one({"_id": ObjectId(admin_user["id"])}, {"$set": {"role": "admin"}}))
    target_user, _target_tokens, target_headers = register_user()

    pack_id = str(asyncio.run(interview_packs_col.insert_one({
        "name": "Custom Pack", "slug": "custom-pack", "price": 1.0, "currency": "usd",
        "sessions_included": 3, "config": QUICK_CONFIG, "is_visible": True, "sort_order": 0,
    })).inserted_id)

    grant_resp = client.post(
        "/api/interview/admin/grant",
        json={"user_id": target_user["id"], "sessions": 3, "pack_id": pack_id, "description": "test grant"},
        headers=admin_headers,
    )
    assert grant_resp.status_code == 200, grant_resp.text
    assert grant_resp.json()["config"] == QUICK_CONFIG

    entitlement = client.get("/api/interview/entitlement", headers=target_headers).json()
    assert entitlement["sessions_remaining"] == 3
    assert entitlement["grants"][0]["pack_slug"] == "custom-pack"


def test_non_admin_cannot_grant_sessions(client, register_user):
    _user, _tokens, headers = register_user()
    resp = client.post("/api/interview/admin/grant",
                       json={"user_id": "someone-else", "sessions": 5}, headers=headers)
    assert resp.status_code == 403


def test_admin_can_start_a_session_with_no_pack_at_all(client, register_user):
    import asyncio
    from bson import ObjectId
    from db import users_col

    admin_user, _tokens, headers = register_user()
    asyncio.run(users_col.update_one({"_id": ObjectId(admin_user["id"])}, {"$set": {"role": "admin"}}))

    resp = client.post("/api/interview/sessions", json={"topic": "dsa", "seniority": "senior"}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "created"
    # No entitlement was ever needed.
    assert client.get("/api/interview/entitlement", headers=headers).json() == {"sessions_remaining": 0, "grants": []}


def test_non_admin_still_requires_a_grant_id(client, register_user):
    _user, _tokens, headers = register_user()
    resp = client.post("/api/interview/sessions", json={"topic": "dsa", "seniority": "mid"}, headers=headers)
    assert resp.status_code == 400
