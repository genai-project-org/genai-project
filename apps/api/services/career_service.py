"""Career Intelligence — Adzuna free tier job search + cached learning paths.

Fallback: if ADZUNA_APP_ID / ADZUNA_APP_KEY are not configured,
returns a curated set of mocked India-focused listings so the UI is functional.
Cache: MongoDB-backed to avoid duplicate LLM calls (major credit saver).
"""
import os
import hashlib
import logging
from typing import List, Optional, Dict, Any
import httpx
from services.llm_client import LlmChat, UserMessage
from db import db, now_iso
from services.knowledge_retriever import retrieve, store as kb_store
from services.settings_service import get_setting
from services.capability_manifest import with_capability

logger = logging.getLogger(__name__)

ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")
ADZUNA_COUNTRY = os.environ.get("ADZUNA_COUNTRY", "in")  # India by default
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")

career_cache_col = db["career_cache"]
job_cache_col = db["job_cache"]


def _cache_key(*parts: str) -> str:
    return hashlib.sha256("::".join(p.lower().strip() for p in parts).encode()).hexdigest()


async def search_jobs(query: str, location: str = "", page: int = 1) -> Dict[str, Any]:
    """Search jobs. Cached 6h. Falls back to mock data when Adzuna keys absent."""
    key = _cache_key("jobs", query, location, str(page), ADZUNA_COUNTRY)
    cached = await job_cache_col.find_one({"_id": key})
    if cached:
        return cached.get("payload", {})

    if not (ADZUNA_APP_ID and ADZUNA_APP_KEY):
        payload = _mock_jobs(query, location)
    else:
        try:
            async with httpx.AsyncClient(timeout=15) as http:
                r = await http.get(
                    f"https://api.adzuna.com/v1/api/jobs/{ADZUNA_COUNTRY}/search/{page}",
                    params={
                        "app_id": ADZUNA_APP_ID,
                        "app_key": ADZUNA_APP_KEY,
                        "what": query,
                        "where": location or "",
                        "results_per_page": 20,
                        "content-type": "application/json",
                    },
                )
                r.raise_for_status()
                data = r.json()
                payload = {
                    "count": data.get("count", 0),
                    "results": [
                        {
                            "id": str(j.get("id")),
                            "title": j.get("title"),
                            "company": (j.get("company") or {}).get("display_name"),
                            "location": (j.get("location") or {}).get("display_name"),
                            "salary_min": j.get("salary_min"),
                            "salary_max": j.get("salary_max"),
                            "description": (j.get("description") or "")[:400],
                            "url": j.get("redirect_url"),
                            "created": j.get("created"),
                        }
                        for j in data.get("results", [])
                    ],
                    "source": "adzuna",
                }
        except Exception as e:
            logger.warning(f"Adzuna failed, falling back: {e}")
            payload = _mock_jobs(query, location)

    await job_cache_col.update_one(
        {"_id": key},
        {"$set": {"payload": payload, "created_at": now_iso()}},
        upsert=True,
    )
    return payload


def _mock_jobs(query: str, location: str) -> Dict[str, Any]:
    loc = location or "Bengaluru, India"
    base_titles = [
        f"Senior {query.title()}",
        f"{query.title()} Engineer",
        f"Lead {query.title()}",
        f"{query.title()} Specialist",
        f"Junior {query.title()}",
    ]
    companies = ["Zerodha", "Razorpay", "Freshworks", "InMobi", "Postman", "CRED"]
    results = []
    for i, title in enumerate(base_titles):
        results.append({
            "id": f"mock-{i}",
            "title": title,
            "company": companies[i % len(companies)],
            "location": loc,
            "salary_min": 800000 + i * 300000,
            "salary_max": 1500000 + i * 500000,
            "description": f"We are hiring for {title}. Strong problem-solving, ownership mindset. Remote-friendly.",
            "url": "https://example.com/apply",
            "created": now_iso(),
        })
    return {"count": len(results), "results": results, "source": "mock"}


async def get_or_generate_learning_path(role: str, skills: List[str], user_id: Optional[str] = None) -> Dict[str, Any]:
    """Retrieve-first learning path generator. Massive credit saver."""
    skills_sorted = sorted([s.lower().strip() for s in skills if s.strip()])
    prompt_key = f"role={role.strip()} skills={','.join(skills_sorted)}"

    # (1) Data lake first (exact + semantic)
    if await get_setting("kb_enabled", True):
        hit = await retrieve("career_learning_path", prompt_key, user_id=user_id)
        if hit:
            payload = hit["response"] if isinstance(hit["response"], dict) else {"roadmap_markdown": hit["response"]}
            return {"cached": True, "source": "kb", "match": hit["match"], "score": hit["score"], **payload}

    # (2) Legacy hash cache (kept for backwards compatibility)
    key = _cache_key("learning_path_v1", role, ",".join(skills_sorted))
    cached = await career_cache_col.find_one({"_id": key})
    if cached:
        return {"cached": True, "source": "cache", **cached.get("payload", {})}

    prompt = (
        f"Design a concise, execution-ready learning roadmap for the role: {role}.\n"
        f"Candidate current skills: {', '.join(skills) or 'none'}.\n\n"
        "Return strict markdown with these sections:\n"
        "## Skill Gap Analysis (bullets)\n"
        "## 90-Day Roadmap (Week 1-2, Week 3-4, Month 2, Month 3 — with concrete deliverables)\n"
        "## Free Resources (5 links style items, format: - Name — description)\n"
        "## Portfolio Projects (3 project ideas with clear scope)\n"
        "## Interview Prep Focus (5 topics)\n"
        "Keep total under 700 words. Be specific, India-market aware."
    )
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"career-lp-{key[:12]}",
        system_message=with_capability("You are a senior career coach for the Indian tech job market."),
    ).with_model("anthropic", "claude-haiku-4-5-20251001")
    resp = await chat.send_message(UserMessage(text=prompt))
    content = resp if isinstance(resp, str) else getattr(resp, "content", str(resp))
    payload = {
        "role": role,
        "skills": skills_sorted,
        "roadmap_markdown": content,
        "generated_at": now_iso(),
    }
    await career_cache_col.update_one(
        {"_id": key},
        {"$set": {"payload": payload, "created_at": now_iso()}},
        upsert=True,
    )
    await kb_store("career_learning_path", prompt_key, payload, user_id=user_id,
                   meta={"role": role, "skills": skills_sorted})
    return {"cached": False, "source": "llm", **payload}
