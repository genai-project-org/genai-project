"""Continuous Knowledge Engine — zero-third-party enrichment worker.

Every N hours:
1. Sample the top N most-searched prompts across the data lake.
2. For each, fetch a public-domain summary from Wikipedia REST + DuckDuckGo Instant Answer.
3. Store enriched entries in the KB with kind='public_knowledge:<topic>' so future
   retrieval can serve them instead of hitting a paid LLM.

No paid APIs. No rate limits worth worrying about at beta scale.
"""
import asyncio
import logging
import re
from typing import List, Optional
import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from services.data_lake import events_col
from services.knowledge_retriever import ai_responses_col, store as kb_store
from services.settings_service import get_setting, set_setting
from db import now_iso

logger = logging.getLogger(__name__)

_scheduler: Optional[AsyncIOScheduler] = None
_STOP = set(
    "a an the and or but for of on in at to from with by is are was were be been being "
    "i me my we our you your do does did have has had can could should would will just "
    "as if then than that this these those about into over under out up down off no not "
    "so too very please help me want need what how why when where which".split()
)
_WORD = re.compile(r"[a-z][a-z\-']+", re.I)


def _extract_topic(text: str) -> str:
    """Pull the most meaningful noun-phrase-ish token cluster from a prompt."""
    if not text:
        return ""
    tokens = [t for t in _WORD.findall(text.lower()) if t not in _STOP and len(t) > 3]
    # take 2–4 most 'weighty' tokens (by length as a crude proxy)
    tokens = sorted(set(tokens), key=lambda t: -len(t))[:3]
    return " ".join(tokens)


async def _top_prompts(limit: int = 20) -> List[str]:
    """Pull recent prompts from ai_responses_col + events for enrichment targets."""
    pipe = [
        {"$match": {"kind": {"$regex": r"^(counseling:|studio_summarize:|builder_generate|career_learning_path)"}}},
        {"$sort": {"created_at": -1}},
        {"$limit": 200},
        {"$group": {"_id": "$prompt", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
        {"$limit": limit},
    ]
    prompts = []
    async for row in ai_responses_col.aggregate(pipe):
        if row.get("_id"):
            prompts.append(row["_id"])
    return prompts


async def _fetch_wikipedia(topic: str, http: httpx.AsyncClient) -> Optional[dict]:
    """Wikipedia REST — free, no API key."""
    if not topic:
        return None
    slug = topic.strip().replace(" ", "_")
    try:
        r = await http.get(f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}",
                           headers={"User-Agent": "IEMA.ai KnowledgeEngine/1.0"})
        if r.status_code != 200:
            return None
        j = r.json()
        if not j.get("extract"):
            return None
        return {
            "title": j.get("title"),
            "extract": j.get("extract"),
            "url": (j.get("content_urls") or {}).get("desktop", {}).get("page"),
            "source": "wikipedia",
        }
    except Exception:
        return None


async def _fetch_duckduckgo(topic: str, http: httpx.AsyncClient) -> Optional[dict]:
    """DuckDuckGo Instant Answer — free."""
    if not topic:
        return None
    try:
        r = await http.get("https://api.duckduckgo.com/",
                           params={"q": topic, "format": "json", "no_html": 1, "skip_disambig": 1},
                           headers={"User-Agent": "IEMA.ai KnowledgeEngine/1.0"})
        if r.status_code != 200:
            return None
        j = r.json()
        abstract = j.get("AbstractText") or j.get("Answer")
        if not abstract:
            return None
        return {
            "title": j.get("Heading"),
            "extract": abstract,
            "url": j.get("AbstractURL") or j.get("AnswerURL"),
            "source": "duckduckgo",
        }
    except Exception:
        return None


async def enrich_once(max_prompts: int = 10) -> dict:
    """One enrichment pass. Fires public-domain lookups for top recent prompts."""
    prompts = await _top_prompts(limit=max_prompts)
    enriched = 0
    skipped = 0
    async with httpx.AsyncClient(timeout=12) as http:
        for prompt in prompts:
            topic = _extract_topic(prompt)
            if not topic:
                skipped += 1; continue
            wiki = await _fetch_wikipedia(topic, http)
            ddg = None
            if not wiki:
                ddg = await _fetch_duckduckgo(topic, http)
            hit = wiki or ddg
            if not hit:
                skipped += 1; continue
            kind = f"public_knowledge:{hit['source']}"
            await kb_store(
                kind, topic, hit["extract"],
                user_id=None,
                meta={"title": hit.get("title"), "url": hit.get("url"),
                      "source_prompt": prompt[:200], "harvested_at": now_iso()},
            )
            enriched += 1
    await events_col.insert_one({
        "event_type": "knowledge_engine_run",
        "user_id": None,
        "payload": {"enriched": enriched, "skipped": skipped, "sampled": len(prompts)},
        "meta": {},
        "created_at": now_iso(),
    })
    logger.info(f"KnowledgeEngine: enriched={enriched} skipped={skipped} sampled={len(prompts)}")
    return {"enriched": enriched, "skipped": skipped, "sampled": len(prompts)}


def start(interval_hours: int = 4):
    """Boot the background scheduler.

    Schedules the *first* run 30 s after server boot so the engine actually
    begins enriching without waiting a full interval. Subsequent runs happen
    on the configured cadence.
    """
    global _scheduler
    if _scheduler and _scheduler.running:
        return
    from datetime import datetime, timedelta, timezone
    first_run = datetime.now(timezone.utc) + timedelta(seconds=30)
    _scheduler = AsyncIOScheduler(timezone="UTC")
    _scheduler.add_job(enrich_once, "interval", hours=interval_hours,
                       id="knowledge_engine", replace_existing=True,
                       next_run_time=first_run)
    _scheduler.start()
    logger.info(f"KnowledgeEngine scheduler started — first run at {first_run.isoformat()}, then every {interval_hours}h")


async def status() -> dict:
    job = _scheduler.get_job("knowledge_engine") if _scheduler else None
    return {
        "running": bool(_scheduler and _scheduler.running),
        "next_run_at": job.next_run_time.isoformat() if job and job.next_run_time else None,
        "interval_hours": int(await get_setting("kb_engine_interval_hours", 4)),
    }
