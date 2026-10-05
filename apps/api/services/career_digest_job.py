"""Career Pipeline daily digest — global scheduled job, same shape as
services/knowledge_engine.py: one AsyncIOScheduler, one job, iterating all
opted-in users rather than a per-user job.

Runs once a day. For each user with `career_profile.digest_enabled=True`:
derive short search terms from their profile blurb, search all job boards,
skip anything already tracked, fit-score up to a small cap of the newest
jobs, store them, and — if anything new was found — send one digest email
plus one in-app notification.
"""
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from db import db, now_iso, users_col
from bson import ObjectId
from services.job_sources import search_all
from services.career_service import derive_search_terms, score_and_draft_job
from services.email_service import send_email, career_digest_template
from services.notification_service import notify

logger = logging.getLogger(__name__)

career_profile_col = db["career_profile"]
career_pipeline_col = db["career_pipeline"]

_scheduler: Optional[AsyncIOScheduler] = None

# Bounded so one run can't fan out into an unbounded number of LLM calls —
# same reasoning as the Gmail scan's implicit cap via Gmail's own maxResults.
MAX_NEW_JOBS_PER_USER = int(os.environ.get("CAREER_DIGEST_MAX_JOBS", "10"))


async def _run_for_user(profile_doc: dict) -> int:
    """Returns the number of new jobs found for this user."""
    user_id = profile_doc["user_id"]
    profile_text = (profile_doc.get("profile_text") or "").strip()
    if not profile_text:
        return 0

    terms = await derive_search_terms(profile_text, user_id=user_id)
    search_result = await search_all(terms["keywords"], terms["location"])

    new_jobs = []
    for job in search_result["results"]:
        job_url = job.get("job_url")
        if not job_url:
            continue
        existing = await career_pipeline_col.find_one({"user_id": user_id, "job_url": job_url})
        if existing:
            continue
        new_jobs.append(job)
        if len(new_jobs) >= MAX_NEW_JOBS_PER_USER:
            break

    if not new_jobs:
        return 0

    scored_for_email = []
    for job in new_jobs:
        try:
            analysis = await score_and_draft_job(job, profile_text, user_id=user_id)
        except Exception:
            logger.exception(f"career_digest: scoring failed for a job (user {user_id}), skipping")
            continue
        doc = {
            "user_id": user_id,
            "title": job.get("title"),
            "company": job.get("company"),
            "location": job.get("location"),
            "job_url": job.get("job_url"),
            "source": "daily_search",
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
        try:
            await career_pipeline_col.insert_one(doc)
            scored_for_email.append(doc)
        except Exception:
            logger.warning("career_digest: duplicate job_url on insert, skipping")

    if scored_for_email:
        user = await users_col.find_one({"_id": ObjectId(user_id)}, {"email": 1, "name": 1})
        if user and user.get("email"):
            await send_email(user["email"], "New job matches", career_digest_template(user.get("name", "there"), scored_for_email))
        await notify(user_id, "New job matches",
                     f"Found {len(scored_for_email)} new job{'s' if len(scored_for_email) != 1 else ''} in your Career Pipeline.",
                     kind="job_match", action_url="/career")
    return len(scored_for_email)


async def run_daily_digest() -> dict:
    users_processed = 0
    jobs_found = 0
    async for profile_doc in career_profile_col.find({"digest_enabled": True}):
        users_processed += 1
        try:
            jobs_found += await _run_for_user(profile_doc)
        except Exception:
            logger.exception(f"career_digest: run failed for user {profile_doc.get('user_id')}")
    logger.info(f"CareerDigest: users_processed={users_processed} jobs_found={jobs_found}")
    return {"users_processed": users_processed, "jobs_found": jobs_found}


def start(hour_utc: int = 7):
    """Boot the daily digest scheduler. First run is scheduled for the next
    occurrence of `hour_utc` UTC, then once every 24h after that."""
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    now = datetime.now(timezone.utc)
    first_run = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if first_run <= now:
        first_run += timedelta(days=1)
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(run_daily_digest, "interval", hours=24,
                       id="career_digest", replace_existing=True,
                       next_run_time=first_run)
    _scheduler.start()
    logger.info(f"CareerDigest scheduler started — first run at {first_run.isoformat()}, then every 24h")


async def status() -> dict:
    job = _scheduler.get_job("career_digest") if _scheduler else None
    return {
        "running": bool(_scheduler and _scheduler.running),
        "next_run_at": job.next_run_time.isoformat() if job and job.next_run_time else None,
    }
