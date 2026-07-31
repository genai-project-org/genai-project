"""Counseling routes — Career, Psychology, Academic AI counselor."""
import os
import logging
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from auth import get_current_user
from models import User
from services.counseling_service import counsel
from services.pricing_engine import spend
from services.data_lake import log_event
from db import counseling_history_col, now_iso

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/counseling", tags=["counseling"])

MODES = ("career", "psychology", "academic")


class CounselRequest(BaseModel):
    mode: str = Field(default="career")
    message: str = Field(min_length=3, max_length=4000)


@router.post("")
async def counsel_route(req: CounselRequest, user: User = Depends(get_current_user)):
    if req.mode not in MODES:
        raise HTTPException(400, f"mode must be one of {MODES}")
    try:
        result = await counsel(req.mode, req.message, user_id=user.id)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Counsel failed")
        raise HTTPException(500, f"Counsel failed: {str(e)[:200]}")

    billing = await spend(
        user.id, f"counseling_{req.mode}",
        provider_override=result.get("provider"),
        skip_charge=(result["source"] == "kb"),
        description=f"Counseling ({req.mode})",
    )
    await log_event(
        f"counseling_{req.mode}", user_id=user.id,
        payload={"chars_in": len(req.message), "chars_out": len(result["response"]),
                 "source": result["source"], "score": result.get("score")},
    )
    # Persist for cross-device history (see GET/DELETE /counseling/history)
    res = await counseling_history_col.insert_one({
        "user_id": user.id, "mode": req.mode,
        "question": req.message, "answer": result["response"],
        "created_at": now_iso(),
    })
    return {
        # The client needs this to flag or replace the exchange it just created.
        "id": str(res.inserted_id),
        "response": result["response"],
        "mode": req.mode,
        "source": result["source"],
        "score": result.get("score"),
        "match": result.get("match"),
        "credits_used": billing["credits_used"],
        "balance": billing["balance"],
        "disclaimer": _disclaimer(req.mode),
    }


@router.get("/history")
async def counseling_history(limit: int = 50, user: User = Depends(get_current_user)):
    cursor = counseling_history_col.find({"user_id": user.id}).sort("created_at", -1).limit(min(limit, 100))
    items = [{"id": str(d["_id"]), "mode": d["mode"], "question": d["question"],
              "answer": d["answer"], "created_at": d.get("created_at"),
              "flagged": bool(d.get("flagged"))} async for d in cursor]
    return {"items": items}


@router.delete("/history")
async def clear_counseling_history(user: User = Depends(get_current_user)):
    await counseling_history_col.delete_many({"user_id": user.id})
    return {"ok": True}


@router.delete("/history/{entry_id}")
async def delete_counseling_entry(entry_id: str, user: User = Depends(get_current_user)):
    """Drop a single exchange. Backs "edit prompt": counseling turns are independent — the
    LLM is sent one message with no thread context — so re-asking replaces only this pair
    and leaves every other answer alone.
    """
    try:
        res = await counseling_history_col.delete_one({"_id": ObjectId(entry_id), "user_id": user.id})
    except Exception:
        raise HTTPException(400, "Invalid entry id")
    if res.deleted_count == 0:
        raise HTTPException(404, "Entry not found")
    return {"ok": True}


@router.post("/history/{entry_id}/flag")
async def toggle_counseling_flag(entry_id: str, user: User = Depends(get_current_user)):
    """Toggle a personal bookmark on one of the user's own exchanges."""
    try:
        doc = await counseling_history_col.find_one({"_id": ObjectId(entry_id), "user_id": user.id})
    except Exception:
        raise HTTPException(400, "Invalid entry id")
    if not doc:
        raise HTTPException(404, "Entry not found")
    flagged = not doc.get("flagged", False)
    await counseling_history_col.update_one({"_id": doc["_id"]}, {"$set": {"flagged": flagged}})
    return {"flagged": flagged}


def _disclaimer(mode: str) -> str:
    if mode == "psychology":
        return ("This is AI-generated wellness guidance, not a substitute for a licensed therapist. "
                "If you're in crisis, call iCall India: 9152987821.")
    if mode == "academic":
        return "Guidance is informational; verify against your official curriculum."
    return "Career suggestions are based on general market patterns; validate against current listings."
