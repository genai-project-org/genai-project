"""Unit tests for services/interview_report_service.py — in particular the
no-data guard: a session that ended with zero recorded candidate turns must
never produce a normal-looking scored report (every dimension silently
defaulting to 50/100 with an empty narrative is indistinguishable from a
real, if weak, evaluation — that's a correctness bug, not just cosmetics)."""
import pytest

from db import (
    interview_sessions_col, interview_turns_col, interview_score_events_col,
    interview_reports_col, career_profile_col,
)
from services import interview_report_service
from services.llm_client import LlmChat

pytestmark = pytest.mark.anyio


async def _make_session(session_id="sess-1", user_id="user-1", topic="dsa"):
    await interview_sessions_col.insert_one({
        "_id": session_id, "user_id": user_id, "status": "completed", "topic": topic,
        "seniority": "mid", "technical_minutes": 45, "behavioral_minutes": 15,
    })


async def test_zero_candidate_turns_produces_no_data_report_not_a_scored_one():
    await _make_session()
    await interview_report_service.generate_report("sess-1")

    report = await interview_reports_col.find_one({"session_id": "sess-1"})
    assert report["status"] == "no_data"
    assert report["overall_score"] is None
    assert report["dimension_scores"] == {}
    assert "no analysis" in report["report_markdown"].lower()

    session = await interview_sessions_col.find_one({"_id": "sess-1"})
    assert session["final_report_id"] == str(report["_id"])

    # No Career Intelligence write-back for a session with nothing genuine to summarize.
    profile = await career_profile_col.find_one({"user_id": "user-1"})
    assert profile is None


async def test_zero_candidate_turns_with_only_interviewer_greeting_is_still_no_data():
    """An interviewer opening line with no candidate reply yet must not count
    as "content" — only a real candidate turn does."""
    await _make_session()
    await interview_turns_col.insert_one({
        "session_id": "sess-1", "round": "technical", "turn_index": 0,
        "speaker": "interviewer", "modality": "voice", "text": "Hi, let's get started.",
        "tool_calls": [], "created_at": "2026-01-01T00:00:00+00:00",
    })
    await interview_report_service.generate_report("sess-1")
    report = await interview_reports_col.find_one({"session_id": "sess-1"})
    assert report["status"] == "no_data"


async def test_real_interaction_produces_a_normal_scored_report(monkeypatch):
    await _make_session()
    await interview_turns_col.insert_one({
        "session_id": "sess-1", "round": "technical", "turn_index": 0,
        "speaker": "candidate", "modality": "text", "text": "I'd use a hash map.",
        "tool_calls": [], "created_at": "2026-01-01T00:00:00+00:00",
    })
    await interview_score_events_col.insert_one({
        "session_id": "sess-1", "round": "technical", "question_index": 0,
        "dimension": "technical_correctness", "score": 80, "note": "good", "created_at": "2026-01-01T00:00:00+00:00",
    })

    async def _fake_send_message(self, msg):
        import json
        return json.dumps({
            "strengths": ["Clear approach"], "weaknesses": ["Could go deeper"],
            "verdict": "Solid start.", "score_adjustments": {"communication": 0, "technical_correctness": 0, "problem_solving": 0, "confidence": 0},
        })

    monkeypatch.setattr(LlmChat, "send_message", _fake_send_message)

    await interview_report_service.generate_report("sess-1")
    report = await interview_reports_col.find_one({"session_id": "sess-1"})
    assert report["status"] == "ready"
    assert report["overall_score"] is not None
    assert report["strengths"] == ["Clear approach"]
    assert report["dimension_scores"]["technical_correctness"] == 80.0

    profile = await career_profile_col.find_one({"user_id": "user-1"})
    assert profile is not None
    assert "Mock Interview" in profile["profile_text"]
