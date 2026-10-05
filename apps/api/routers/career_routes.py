"""Career Intelligence routes."""
import os
import logging
from typing import List, Optional, Literal
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from bson import ObjectId
from auth import get_current_user
from models import User
from db import db, now_iso
from services.career_service import (
    search_jobs, get_or_generate_learning_path, score_and_draft_job, derive_search_terms,
    tailor_resume_for_job, generate_interview_prep, salary_negotiation_coach, continue_addon_chat,
)
from services import gmail_service, resume_profile_service
from services.job_sources import search_all
from services.pricing_engine import spend, precheck
from services.data_lake import log_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/career", tags=["career"])

career_profile_col = db["career_profile"]
career_pipeline_col = db["career_pipeline"]


class JobSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=120)
    location: str = Field(default="", max_length=120)
    page: int = Field(default=1, ge=1, le=10)


class LearningPathRequest(BaseModel):
    role: str = Field(min_length=2, max_length=120)
    skills: List[str] = Field(default_factory=list, max_length=20)


@router.post("/jobs")
async def jobs_search(req: JobSearchRequest, user: User = Depends(get_current_user)):
    data = await search_jobs(req.query, req.location, req.page)
    await log_event("career_job_search", user_id=user.id,
                    payload={"q": req.query, "loc": req.location, "count": data.get("count", 0),
                             "source": data.get("source")})
    return data


@router.post("/learning-path")
async def learning_path(req: LearningPathRequest, user: User = Depends(get_current_user)):
    result = await get_or_generate_learning_path(req.role, req.skills, user_id=user.id)
    was_fresh = not result.get("cached", False)
    billing = await spend(
        user.id, "career_learning_path",
        skip_charge=not was_fresh,
        description="Learning path generation",
    )
    result["credits_used"] = billing["credits_used"]
    result["balance"] = billing["balance"]
    await log_event("career_learning_path", user_id=user.id,
                    payload={"role": req.role, "skills": req.skills, "cached": result.get("cached", False)})
    return result


# ================= PIPELINE (Gmail job-alert scan → fit score + outreach draft) =================

class GmailConnectRequest(BaseModel):
    code: str
    redirect_uri: str


class ProfileUpdateRequest(BaseModel):
    profile_text: str = Field(min_length=10, max_length=8000)


class PipelineStatusUpdate(BaseModel):
    status: Literal["new", "applied", "contacted", "interviewing", "offer", "rejected"]


class DigestToggleRequest(BaseModel):
    enabled: bool


@router.get("/gmail/status")
async def gmail_status(user: User = Depends(get_current_user)):
    return await gmail_service.get_status(user.id)


@router.post("/gmail/connect")
async def gmail_connect(req: GmailConnectRequest, user: User = Depends(get_current_user)):
    try:
        result = await gmail_service.exchange_code(user.id, req.code, req.redirect_uri)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))
    await log_event("career_gmail_connect", user_id=user.id, payload={"email": result.get("email")})
    return result


@router.post("/gmail/disconnect")
async def gmail_disconnect(user: User = Depends(get_current_user)):
    await gmail_service.disconnect(user.id)
    await log_event("career_gmail_disconnect", user_id=user.id)
    return {"connected": False}


@router.get("/profile")
async def get_profile(user: User = Depends(get_current_user)):
    doc = await career_profile_col.find_one({"user_id": user.id}) or {}
    return {"profile_text": doc.get("profile_text", ""), "digest_enabled": bool(doc.get("digest_enabled", False))}


@router.post("/profile")
async def save_profile(req: ProfileUpdateRequest, user: User = Depends(get_current_user)):
    await career_profile_col.update_one(
        {"user_id": user.id},
        {"$set": {"user_id": user.id, "profile_text": req.profile_text, "updated_at": now_iso()}},
        upsert=True,
    )
    return {"profile_text": req.profile_text}


@router.get("/pipeline")
async def list_pipeline(user: User = Depends(get_current_user)):
    items = []
    async for doc in career_pipeline_col.find({"user_id": user.id}).sort("created_at", -1):
        doc["id"] = str(doc.pop("_id"))
        items.append(doc)
    return {"items": items}


@router.patch("/pipeline/{job_id}/status")
async def update_pipeline_status(job_id: str, req: PipelineStatusUpdate, user: User = Depends(get_current_user)):
    try:
        oid = ObjectId(job_id)
    except Exception:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pipeline entry not found")
    result = await career_pipeline_col.update_one(
        {"_id": oid, "user_id": user.id},
        {"$set": {"status": req.status, "updated_at": now_iso()}},
    )
    if result.matched_count == 0:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pipeline entry not found")
    await log_event("career_pipeline_status", user_id=user.id, payload={"job_id": job_id, "status": req.status})
    return {"id": job_id, "status": req.status}


@router.post("/pipeline/scan")
async def scan_pipeline(user: User = Depends(get_current_user)):
    profile_doc = await career_profile_col.find_one({"user_id": user.id})
    profile_text = (profile_doc or {}).get("profile_text", "").strip()
    if not profile_text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Add a profile summary first (Career → Pipeline).")

    gmail_conn = await gmail_service.get_status(user.id)
    if not gmail_conn.get("connected"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Connect Gmail first (Career → Pipeline).")

    try:
        raw_jobs = await gmail_service.fetch_linkedin_alert_emails(user.id)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e))

    # Fail fast before doing any LLM work if the user can't afford even one job.
    await precheck(user.id, "career_pipeline_analyze")

    new_count = 0
    limited = False
    for job in raw_jobs:
        job_url = job.get("job_url")
        if job_url:
            existing = await career_pipeline_col.find_one({"user_id": user.id, "job_url": job_url})
            if existing:
                continue

        try:
            analysis = await score_and_draft_job(job, profile_text, user_id=user.id)
        except Exception:
            logger.exception("career_pipeline: scoring failed for a job, skipping")
            continue

        try:
            await spend(
                user.id, "career_pipeline_analyze",
                skip_charge=(analysis["source"] == "kb"),
                provider_override=analysis.get("provider"),
                description="Career pipeline job scoring",
            )
        except HTTPException:
            # Ran out of credits/window mid-scan — stop, but keep everything scored so far.
            limited = True
            break

        doc = {
            "user_id": user.id,
            "title": job.get("title"),
            "company": job.get("company"),
            "location": job.get("location"),
            "source": "gmail",
            "fit_score": analysis.get("fit_score"),
            "fit_reason": analysis.get("fit_reason"),
            "recruiter_title": analysis.get("recruiter_title"),
            "linkedin_search_query": analysis.get("linkedin_search_query"),
            "outreach_message": analysis.get("outreach_message"),
            "status": "new",
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        if job_url:
            doc["job_url"] = job_url  # omit when absent so the sparse unique index skips it
        try:
            await career_pipeline_col.insert_one(doc)
            new_count += 1
        except Exception:
            logger.warning("career_pipeline: duplicate job_url on insert, skipping")

    total = await career_pipeline_col.count_documents({"user_id": user.id})
    await log_event("career_pipeline_scan", user_id=user.id,
                    payload={"scanned": len(raw_jobs), "new": new_count, "limited": limited})
    return {"new_count": new_count, "total_count": total, "limited": limited}


@router.post("/digest/toggle")
async def toggle_digest(req: DigestToggleRequest, user: User = Depends(get_current_user)):
    await career_profile_col.update_one(
        {"user_id": user.id},
        {"$set": {"user_id": user.id, "digest_enabled": req.enabled, "updated_at": now_iso()}},
        upsert=True,
    )
    await log_event("career_digest_toggle", user_id=user.id, payload={"enabled": req.enabled})
    return {"digest_enabled": req.enabled}


# A live multi-board search can return dozens of results, and each one scored
# is a separate sequential LLM call (spend()'s wallet check/deduct isn't safe
# to parallelize) — capped so one click can't turn into a minutes-long request
# or a runaway credit charge. Live-tested: an uncapped run against real boards
# scored all 32 results found for one query, taking well over a minute.
DISCOVER_MAX_JOBS = int(os.environ.get("CAREER_DISCOVER_MAX_JOBS", "10"))


@router.post("/pipeline/discover")
async def discover_pipeline(user: User = Depends(get_current_user)):
    """On-demand version of the daily digest search: derive terms from the
    saved profile, search every job board directly (no Gmail/email dependency),
    fit-score the newest few. Mirrors /pipeline/scan's credit-gating shape."""
    profile_doc = await career_profile_col.find_one({"user_id": user.id})
    profile_text = (profile_doc or {}).get("profile_text", "").strip()
    if not profile_text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Add a profile summary first (Career → Pipeline).")

    terms = await derive_search_terms(profile_text, user_id=user.id)
    search_result = await search_all(terms["keywords"], terms["location"])

    # Dedup before capping — a page of already-tracked jobs shouldn't crowd
    # out genuinely new ones further down the result list.
    raw_jobs = []
    for job in search_result["results"]:
        job_url = job.get("job_url")
        if job_url and await career_pipeline_col.find_one({"user_id": user.id, "job_url": job_url}):
            continue
        raw_jobs.append(job)
        if len(raw_jobs) >= DISCOVER_MAX_JOBS:
            break

    await precheck(user.id, "career_pipeline_analyze")

    new_count = 0
    limited = False
    for job in raw_jobs:
        job_url = job.get("job_url")

        try:
            analysis = await score_and_draft_job(job, profile_text, user_id=user.id)
        except Exception:
            logger.exception("career_pipeline: scoring failed for a job, skipping")
            continue

        try:
            await spend(
                user.id, "career_pipeline_analyze",
                skip_charge=(analysis["source"] == "kb"),
                provider_override=analysis.get("provider"),
                description="Career pipeline job scoring",
            )
        except HTTPException:
            limited = True
            break

        doc = {
            "user_id": user.id,
            "title": job.get("title"),
            "company": job.get("company"),
            "location": job.get("location"),
            "source": "on_demand_search",
            "source_board": job.get("source_board"),
            "fit_score": analysis.get("fit_score"),
            "fit_reason": analysis.get("fit_reason"),
            "recruiter_title": analysis.get("recruiter_title"),
            "linkedin_search_query": analysis.get("linkedin_search_query"),
            "outreach_message": analysis.get("outreach_message"),
            "status": "new",
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        if job_url:
            doc["job_url"] = job_url
        try:
            await career_pipeline_col.insert_one(doc)
            new_count += 1
        except Exception:
            logger.warning("career_pipeline: duplicate job_url on insert, skipping")

    total = await career_pipeline_col.count_documents({"user_id": user.id})
    await log_event("career_pipeline_discover", user_id=user.id,
                    payload={"scanned": len(raw_jobs), "new": new_count, "limited": limited,
                             "sources": search_result["sources"], "terms": terms})
    return {"new_count": new_count, "total_count": total, "limited": limited, "sources": search_result["sources"]}


@router.post("/pipeline/{job_id}/apply")
async def apply_to_pipeline_job(job_id: str, user: User = Depends(get_current_user)):
    """Phase 1's honest 'Apply': opens the real posting for the user to apply
    themselves and marks it applied in the tracker. No automated submission —
    see the Career Pipeline v2 plan for why that needs separate infrastructure
    this app doesn't have yet."""
    try:
        oid = ObjectId(job_id)
    except Exception:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pipeline entry not found")
    doc = await career_pipeline_col.find_one({"_id": oid, "user_id": user.id})
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pipeline entry not found")
    if not doc.get("job_url"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This entry has no posting link to apply to.")

    await career_pipeline_col.update_one(
        {"_id": oid},
        {"$set": {"status": "applied", "application_method": "manual", "applied_at": now_iso(), "updated_at": now_iso()}},
    )
    await log_event("career_pipeline_apply", user_id=user.id, payload={"job_id": job_id})
    return {"id": job_id, "status": "applied", "job_url": doc["job_url"]}


# ================= Paid per-job add-ons: tailor, interview prep, salary coach =================

async def _get_pipeline_job(job_id: str, user_id: str) -> dict:
    try:
        oid = ObjectId(job_id)
    except Exception:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pipeline entry not found")
    doc = await career_pipeline_col.find_one({"_id": oid, "user_id": user_id})
    if not doc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pipeline entry not found")
    return doc


async def _get_resume_text(user_id: str) -> str:
    profile = await resume_profile_service.get_profile(user_id)
    raw_text = (profile or {}).get("raw_text", "").strip()
    if not raw_text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Save a resume in Resume Intelligence first (Resume → upload → Save as profile).")
    return raw_text


@router.post("/pipeline/{job_id}/tailor")
async def tailor_job(job_id: str, user: User = Depends(get_current_user)):
    job = await _get_pipeline_job(job_id, user.id)
    resume_text = await _get_resume_text(user.id)
    result = await tailor_resume_for_job(job, resume_text, user_id=user.id)
    billing = await spend(user.id, "career_tailor_resume", skip_charge=(result["source"] == "kb"),
                          provider_override=result.get("provider"), description="Tailored resume + cover letter")
    await log_event("career_tailor_resume", user_id=user.id, payload={"job_id": job_id, "source": result["source"]})
    return {**result, "credits_used": billing["credits_used"], "balance": billing["balance"]}


@router.post("/pipeline/{job_id}/interview-prep")
async def interview_prep_job(job_id: str, user: User = Depends(get_current_user)):
    job = await _get_pipeline_job(job_id, user.id)
    resume_text = await _get_resume_text(user.id)
    result = await generate_interview_prep(job, resume_text, user_id=user.id)
    billing = await spend(user.id, "career_interview_prep", skip_charge=(result["source"] == "kb"),
                          provider_override=result.get("provider"), description="Job-specific interview prep")
    await log_event("career_interview_prep", user_id=user.id, payload={"job_id": job_id, "source": result["source"]})
    return {**result, "credits_used": billing["credits_used"], "balance": billing["balance"]}


@router.post("/pipeline/{job_id}/salary-coach")
async def salary_coach_job(job_id: str, user: User = Depends(get_current_user)):
    job = await _get_pipeline_job(job_id, user.id)
    profile_doc = await career_profile_col.find_one({"user_id": user.id})
    profile_text = (profile_doc or {}).get("profile_text", "").strip()
    if not profile_text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Add a profile summary first (Career → Pipeline).")
    result = await salary_negotiation_coach(job, profile_text, user_id=user.id)
    billing = await spend(user.id, "career_salary_coach", skip_charge=(result["source"] == "kb"),
                          provider_override=result.get("provider"), description="Salary negotiation coaching")
    await log_event("career_salary_coach", user_id=user.id, payload={"job_id": job_id, "source": result["source"]})
    return {**result, "credits_used": billing["credits_used"], "balance": billing["balance"]}


class AddonChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    context: dict = Field(default_factory=dict)  # the original tailor/prep/salary result, for grounding
    history: List[dict] = Field(default_factory=list)  # [{role, content}] prior turns, most-recent-last


@router.post("/pipeline/{job_id}/{addon_type}/chat")
async def addon_chat(
    job_id: str,
    addon_type: Literal["tailor", "interview-prep", "salary-coach"],
    req: AddonChatRequest,
    user: User = Depends(get_current_user),
):
    job = await _get_pipeline_job(job_id, user.id)
    await precheck(user.id, "career_addon_chat")
    reply = await continue_addon_chat(addon_type, job, req.context, req.history[-8:], req.message, user_id=user.id)
    billing = await spend(user.id, "career_addon_chat", description=f"Follow-up on {addon_type}")
    await log_event("career_addon_chat", user_id=user.id, payload={"job_id": job_id, "addon_type": addon_type})
    return {"reply": reply, "credits_used": billing["credits_used"], "balance": billing["balance"]}
