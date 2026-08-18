"""In-app content reporting/flagging.

Required by Google Play's AI-Generated Content policy: users must be able
to report or flag offensive AI-generated output without leaving the app,
and those reports must inform content filtering and moderation.
"""
import logging
from fastapi import APIRouter, Depends
from auth import get_current_user
from db import content_reports_col
from models import User, ContentReport, ReportContentRequest
from services.data_lake import log_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("/")
async def report_content(req: ReportContentRequest, user: User = Depends(get_current_user)):
    report = ContentReport(
        user_id=user.id,
        content_type=req.content_type,
        content_ref=req.content_ref,
        content_preview=req.content_preview,
        reason=req.reason or "inappropriate_or_offensive",
    )
    result = await content_reports_col.insert_one(report.to_mongo())
    await log_event(
        "content_report",
        user_id=user.id,
        payload={
            "content_type": req.content_type,
            "content_ref": (req.content_ref or "")[:500],
            "reason": report.reason,
        },
    )
    return {"id": str(result.inserted_id), "status": "received"}
