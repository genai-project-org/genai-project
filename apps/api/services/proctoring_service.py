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
    "copy_paste", "devtools_suspected", "app_backgrounded",
}


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

    return {
        "warning_count": warning_count,
        "warnings_remaining": max(0, TERMINATE_AT_COUNT - warning_count),
        "terminated": terminated,
    }
