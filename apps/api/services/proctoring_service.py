"""Mock Interview proctoring — violation ingestion and server-authoritative termination.

Detection (webcam face-presence, tab-focus, fullscreen, devtools heuristics,
mobile app-backgrounding) is inherently CLIENT-side — there is no way for this
backend to inspect a candidate's browser devtools state or camera feed
directly. What IS server-authoritative, and lives here, is COUNTING and
ENFORCING: two confirmed violations end the session, atomically and
race-safely, regardless of how many violation reports arrive concurrently.

Recording is flag-triggered only (a short clip around the violation), never a
continuous session recording — see the product decision in the Mock Interview
plan.
"""
import asyncio
import logging
from typing import Any, Dict, Optional

from pymongo import ReturnDocument

from db import interview_violations_col, interview_sessions_col, now_iso
from services import storage_service

logger = logging.getLogger(__name__)

# Product rule: 2 warnings, then the 3rd confirmed violation ends the session.
WARNINGS_BEFORE_TERMINATION = 2
TERMINATE_AT_COUNT = WARNINGS_BEFORE_TERMINATION + 1

# Mirrors models.InterviewViolationType's Literal exactly — validated here
# too since the router accepts this as a raw Form string (FastAPI/pydantic
# never gets a chance to enforce that model), so an arbitrary/malformed type
# can't be stored and counted toward termination.
VALID_VIOLATION_TYPES = {
    "face_not_visible", "multiple_faces", "tab_blur", "fullscreen_exit",
    "copy_paste", "devtools_suspected", "app_backgrounded", "voice_mismatch",
}

_VIOLATION_SPOKEN = {
    "face_not_visible": "I cannot see your face. You must stay clearly in front of the camera for the whole interview.",
    "multiple_faces": "I can see more than one person on your camera. You must be completely alone during this interview.",
    "tab_blur": "You left the interview screen. You are not allowed to switch tabs or windows.",
    "fullscreen_exit": "You exited full screen. Return to full screen right now and stay there.",
    "copy_paste": "Copying or pasting is not allowed in this interview. Write your own code.",
    "devtools_suspected": "Opening developer tools is not permitted in this interview.",
    "app_backgrounded": "You moved the interview to the background. You must keep this screen in front at all times.",
    "voice_mismatch": "The voice I am hearing does not match the candidate who started this interview. Only you may answer.",
}


def spoken_warning_text(violation_type: str, warning_count: int, terminated: bool) -> str:
    """Strict, interviewer-voiced warning read aloud when a violation is confirmed."""
    reason = _VIOLATION_SPOKEN.get(violation_type, "That is a violation of the interview rules.")
    if terminated:
        return (f"{reason} This is your third violation. I am ending this interview right now. "
                "Your session is terminated and the violations will be recorded in your report.")
    if warning_count >= WARNINGS_BEFORE_TERMINATION:
        return (f"{reason} This is your final warning. One more violation and I will terminate this interview "
                "immediately. Do not let it happen again.")
    return (f"Warning. {reason} This would not be tolerated in a real interview. "
            "Do not repeat it, or this session will be terminated.")


async def _spoken_warning_audio(session: Dict[str, Any], text: str) -> Optional[str]:
    """TTS in the session's interviewer voice. Best effort: any failure degrades to text-only."""
    try:
        import base64
        from services import speech_service
        from services.interview_service import _INTERVIEWERS_BY_ID
        voice = speech_service.voice_model_path(
            _INTERVIEWERS_BY_ID.get(session.get("interviewer_id"), {}).get("voice_file", ""))
        audio = await asyncio.wait_for(speech_service.synthesize(text, voice), timeout=12)
        return base64.b64encode(audio).decode("ascii") if audio else None
    except Exception:
        logger.exception("proctoring_service: spoken warning TTS failed, continuing text-only")
        return None


async def record_violation(
    session_id: str, user_id: str, violation_type: str,
    detected_at: Optional[str] = None,
    evidence_bytes: Optional[bytes] = None, evidence_content_type: str = "video/webm",
) -> Dict[str, Any]:
    from fastapi import HTTPException
    # Late import to avoid a circular import (interview_service imports
    # nothing from here, but this keeps the dependency direction explicit
    # and matches _kick_off_report's existing late-import style below).
    from services.interview_service import ACTIVE_STATUSES, _advance_time_based_transitions, _kick_off_report

    if violation_type not in VALID_VIOLATION_TYPES:
        raise HTTPException(400, f"Unknown violation type: {violation_type}")

    session = await interview_sessions_col.find_one({"_id": session_id, "user_id": user_id})
    if not session:
        raise HTTPException(404, "Interview session not found")
    # Recompute from stored timestamps first — a round's time limit may have
    # already elapsed but the background sweep hasn't processed it yet, in
    # which case this report must NOT count against a session that should
    # already be completed.
    session = await _advance_time_based_transitions(session)
    if session["status"] not in ACTIVE_STATUSES:
        raise HTTPException(409, "This interview session is no longer active")

    evidence_clip_key = None
    if evidence_bytes:
        try:
            evidence_clip_key = await storage_service.upload_bytes(
                evidence_bytes, f"{violation_type}.webm", content_type=evidence_content_type,
                folder=f"interview-violations/{session_id}",
            )
        except Exception:
            logger.exception("proctoring_service: evidence clip upload failed — continuing without it")

    await interview_violations_col.insert_one({
        "session_id": session_id, "user_id": user_id, "type": violation_type,
        "detected_at": detected_at, "reported_at": now_iso(),
        "evidence_clip_key": evidence_clip_key, "counted": True, "created_at": now_iso(),
    })

    # Atomic guarded increment — two near-simultaneous violation reports can't
    # double-count or double-terminate, and the terminating write happens in
    # the SAME update as the increment that crosses the threshold.
    updated = await interview_sessions_col.find_one_and_update(
        {"_id": session_id, "status": {"$in": list(ACTIVE_STATUSES)}},
        {"$inc": {"warning_count": 1}, "$set": {"updated_at": now_iso()}},
        return_document=ReturnDocument.AFTER,
    )
    warning_count = (updated or session).get("warning_count", 1)
    terminated = False

    if updated and warning_count >= TERMINATE_AT_COUNT:
        # Same atomic-update idiom as the increment above: the status flip only
        # applies if the session was still active, so a second violation
        # arriving after termination can't "re-terminate" or overwrite state.
        terminate_result = await interview_sessions_col.find_one_and_update(
            {"_id": session_id, "status": {"$in": list(ACTIVE_STATUSES)}},
            {"$set": {"status": "terminated_violations",
                      "terminated_reason": f"{TERMINATE_AT_COUNT} proctoring violations (latest: {violation_type})",
                      "ended_at": now_iso(), "updated_at": now_iso()}},
        )
        if terminate_result:
            terminated = True
            _kick_off_report(session_id)
    elif updated and warning_count == WARNINGS_BEFORE_TERMINATION:
        # This is the LAST warning before termination — pause the round clock
        # server-side (paused_at) so the candidate reading/acknowledging the
        # blocking warning dialog doesn't silently burn real round time; see
        # interview_service.acknowledge_warning(), which measures and
        # compensates for this pause from the server's own clock.
        await interview_sessions_col.update_one(
            {"_id": session_id, "paused_at": None}, {"$set": {"paused_at": now_iso()}},
        )

    warning_text = spoken_warning_text(violation_type, warning_count, terminated)
    warning_audio = await _spoken_warning_audio(session, warning_text)
    return {
        "warning_count": warning_count,
        "warnings_remaining": max(0, TERMINATE_AT_COUNT - warning_count),
        "terminated": terminated,
        "warning_text": warning_text,
        "warning_audio_base64": warning_audio,
    }


async def get_evidence_url(session_id: str, user_id: str, violation_id: str) -> str:
    """Resolves one violation's evidence clip to a short-lived signed S3 URL,
    on demand — never exposed as a durable key on the report payload itself
    (see interview_report_service._violations_public). Raises 404 if the
    violation doesn't belong to this user's session, or if no clip was ever
    captured for it (e.g. the upload failed, or storage isn't configured in
    this environment — see storage_service.is_configured())."""
    from bson import ObjectId
    from fastapi import HTTPException

    try:
        oid = ObjectId(violation_id)
    except Exception:
        raise HTTPException(404, "Violation not found")

    violation = await interview_violations_col.find_one(
        {"_id": oid, "session_id": session_id, "user_id": user_id},
    )
    if not violation:
        raise HTTPException(404, "Violation not found")
    if not violation.get("evidence_clip_key"):
        raise HTTPException(404, "No evidence clip was captured for this violation")

    return storage_service.get_signed_url(violation["evidence_clip_key"])
