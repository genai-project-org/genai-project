"""Unit tests for services/proctoring_service.py — the server-authoritative
warning-count / termination rule: 2 warnings, then the 3rd confirmed
violation ends the session, atomically."""
import pytest
from fastapi import HTTPException

from db import interview_sessions_col
from services import interview_service, proctoring_service

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _no_report_generation(monkeypatch):
    from services import interview_report_service

    async def _noop(session_id):
        return None

    monkeypatch.setattr(interview_report_service, "generate_report", _noop)


FULL_CONFIG = {
    "technical_minutes": 45, "behavioral_minutes": 15,
    "topics": ["dsa", "hld", "lld", "design", "hr"],
    "seniority_levels": ["entry", "mid", "senior"],
    "languages": ["python", "javascript", "cpp", "java"],
    "sub_topics": {},
}


async def _active_session(user_id="user-1"):
    pack = {"id": "pack-1", "slug": "interview-prep-usd", "name": "Interview Prep Pack", "config": FULL_CONFIG}
    granted = await interview_service.grant_sessions(user_id, 1, pack=pack, ref_id="pay-1")
    session = await interview_service.create_session(user_id, granted["grant_id"], "dsa", "mid")
    await interview_sessions_col.update_one(
        {"_id": session["_id"]},
        {"$set": {"status": "technical_in_progress"}},
    )
    return session["_id"]


async def test_first_violation_is_a_warning_not_a_termination():
    session_id = await _active_session()
    result = await proctoring_service.record_violation(session_id, "user-1", "tab_blur")
    assert result == {"warning_count": 1, "warnings_remaining": 2, "terminated": False}


async def test_second_violation_still_not_terminated():
    session_id = await _active_session()
    await proctoring_service.record_violation(session_id, "user-1", "tab_blur")
    result = await proctoring_service.record_violation(session_id, "user-1", "face_not_visible")
    assert result == {"warning_count": 2, "warnings_remaining": 1, "terminated": False}


async def test_third_violation_terminates_the_session():
    session_id = await _active_session()
    await proctoring_service.record_violation(session_id, "user-1", "tab_blur")
    await proctoring_service.record_violation(session_id, "user-1", "face_not_visible")
    result = await proctoring_service.record_violation(session_id, "user-1", "multiple_faces")
    assert result == {"warning_count": 3, "warnings_remaining": 0, "terminated": True}

    session = await interview_sessions_col.find_one({"_id": session_id})
    assert session["status"] == "terminated_violations"
    assert session["ended_at"] is not None


async def test_violation_reported_against_terminated_session_is_rejected():
    session_id = await _active_session()
    for _ in range(3):
        await proctoring_service.record_violation(session_id, "user-1", "tab_blur")
    with pytest.raises(HTTPException) as exc_info:
        await proctoring_service.record_violation(session_id, "user-1", "tab_blur")
    assert exc_info.value.status_code == 409


async def test_violation_against_unknown_session_404s():
    with pytest.raises(HTTPException) as exc_info:
        await proctoring_service.record_violation("not-a-real-session", "user-1", "tab_blur")
    assert exc_info.value.status_code == 404
