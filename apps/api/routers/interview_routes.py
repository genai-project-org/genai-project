"""Mock Interview routes — entitlement, session lifecycle, turns, proctoring, reports."""
import logging
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import Response
from auth import get_current_user, require_admin
from models import InterviewSessionCreateRequest, InterviewLanguageChangeRequest, AdminGrantInterviewSessionsRequest, User
from services import interview_service, proctoring_service, interview_report_service
from db import interview_sessions_col, interview_packs_col, users_col

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/interview", tags=["interview"])

MAX_AUDIO_SIZE = 15 * 1024 * 1024  # 15MB — a few minutes of webm/opus at typical bitrates
MAX_EVIDENCE_SIZE = 20 * 1024 * 1024  # 20MB — a short (~5-10s) evidence clip


@router.get("/entitlement")
async def get_entitlement(user: User = Depends(get_current_user)):
    return await interview_service.get_entitlement(user.id)


@router.post("/sessions")
async def create_session(req: InterviewSessionCreateRequest, user: User = Depends(get_current_user)):
    doc = await interview_service.create_session(
        user.id, req.grant_id, req.topic, req.seniority,
        is_admin=(user.role == "admin"),
        resume_profile_id=req.resume_profile_id, sub_topic=req.sub_topic,
        language=req.language, include_behavioral=req.include_behavioral,
        technical_minutes=req.technical_minutes, behavioral_minutes=req.behavioral_minutes,
    )
    return {
        "id": doc["_id"], "status": doc["status"], "topic": doc["topic"],
        "current_round": doc["current_round"], "include_behavioral": doc["include_behavioral"],
        "technical_minutes": doc["technical_minutes"], "behavioral_minutes": doc["behavioral_minutes"],
        "interviewer": interview_service.get_interviewer_public(doc.get("interviewer_id")),
    }


@router.get("/sessions")
async def list_sessions(limit: int = 20, user: User = Depends(get_current_user)):
    cursor = interview_sessions_col.find({"user_id": user.id}).sort("created_at", -1).limit(limit)
    items = []
    async for d in cursor:
        items.append({
            "id": d["_id"], "topic": d["topic"], "status": d["status"],
            "created_at": d["created_at"], "ended_at": d.get("ended_at"),
            "final_report_id": d.get("final_report_id"),
        })
    return {"items": items}


@router.get("/sessions/{session_id}/status")
async def session_status(session_id: str, user: User = Depends(get_current_user)):
    return await interview_service.get_status(session_id, user.id)


@router.post("/sessions/{session_id}/acknowledge")
async def acknowledge_warning(session_id: str, user: User = Depends(get_current_user)):
    """Dismisses the blocking 2nd-warning dialog and compensates the round
    clock for the time spent on it — see interview_service.acknowledge_warning."""
    return await interview_service.acknowledge_warning(session_id, user.id)


@router.post("/sessions/{session_id}/language")
async def change_language(session_id: str, req: InterviewLanguageChangeRequest, user: User = Depends(get_current_user)):
    """Mid-round coding-language switch (DSA technical round only) — see
    interview_service.change_language."""
    return await interview_service.change_language(session_id, user.id, req.language)


@router.post("/sessions/{session_id}/start")
async def start_session(session_id: str, user: User = Depends(get_current_user)):
    """Generates the interviewer's opening greeting + first question and starts
    the clock — called once by the client right after entering the live
    session (not gated on the candidate speaking first)."""
    try:
        return await interview_service.start_session(session_id, user.id)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"interview session start failed for session {session_id}")
        raise HTTPException(500, f"Could not start the interview: {str(e)[:200]}")


@router.post("/sessions/{session_id}/turn")
async def submit_turn(
    session_id: str,
    modality: str = Form(...),  # "voice" | "text" | "code"
    text: str = Form(""),
    audio: UploadFile = File(None),
    user: User = Depends(get_current_user),
):
    audio_bytes = None
    if audio and audio.filename:
        audio_bytes = await audio.read(MAX_AUDIO_SIZE + 1)
        if len(audio_bytes) > MAX_AUDIO_SIZE:
            raise HTTPException(400, "Audio clip too large.")
    try:
        return await interview_service.handle_turn(
            session_id, user.id, modality=modality, text=text, audio_bytes=audio_bytes,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"interview turn failed for session {session_id}")
        raise HTTPException(500, f"Interview turn failed: {str(e)[:200]}")


@router.post("/sessions/{session_id}/end")
async def end_session(session_id: str, user: User = Depends(get_current_user)):
    return await interview_service.end_session_early(session_id, user.id)


@router.post("/sessions/{session_id}/violations")
async def report_violation(
    session_id: str,
    type: str = Form(...),
    detected_at: str = Form(""),
    evidence: UploadFile = File(None),
    user: User = Depends(get_current_user),
):
    evidence_bytes, content_type = None, "video/webm"
    if evidence and evidence.filename:
        evidence_bytes = await evidence.read(MAX_EVIDENCE_SIZE + 1)
        if len(evidence_bytes) > MAX_EVIDENCE_SIZE:
            evidence_bytes = None  # drop an oversized clip rather than fail the whole violation report
        else:
            content_type = evidence.content_type or content_type
    return await proctoring_service.record_violation(
        session_id, user.id, type, detected_at=detected_at or None,
        evidence_bytes=evidence_bytes, evidence_content_type=content_type,
    )


@router.get("/sessions/{session_id}/report")
async def get_report(session_id: str, user: User = Depends(get_current_user)):
    report = await interview_report_service.get_report(session_id, user.id)
    if not report:
        # Confirm the session exists/is owned by this user before saying "pending"
        # vs a flat 404 for a session_id that was never theirs.
        await interview_service.get_session(session_id, user.id)
        return {"status": "pending"}
    report["id"] = str(report.pop("_id"))
    return report


@router.get("/sessions/{session_id}/report/pdf")
async def get_report_pdf(session_id: str, user: User = Depends(get_current_user)):
    session = await interview_service.get_session(session_id, user.id)
    report = await interview_report_service.get_report(session_id, user.id)
    if not report or report.get("status") != "ready":
        raise HTTPException(404, "Report not ready yet")
    user_doc = await users_col.find_one({"_id": ObjectId(user.id)})
    pdf_bytes = interview_report_service.generate_report_pdf(session, report, (user_doc or {}).get("name", user.email))
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="mock-interview-{session_id[:8]}.pdf"'})


# ================= Admin =================
@router.post("/admin/grant")
async def admin_grant_sessions(req: AdminGrantInterviewSessionsRequest, admin: User = Depends(require_admin)):
    pack = None
    if req.pack_id:
        pack_doc = await interview_packs_col.find_one({"_id": ObjectId(req.pack_id)})
        if not pack_doc:
            raise HTTPException(404, "Pack not found")
        pack_doc["id"] = str(pack_doc.pop("_id"))
        pack = pack_doc
    return await interview_service.grant_sessions(req.user_id, req.sessions, pack=pack,
                                                   tx_type="admin_grant", description=req.description)
