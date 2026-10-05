"""Career Intelligence — Adzuna free tier job search + cached learning paths.

Fallback: if ADZUNA_APP_ID / ADZUNA_APP_KEY are not configured,
returns a curated set of mocked India-focused listings so the UI is functional.
Cache: MongoDB-backed to avoid duplicate LLM calls (major credit saver).
"""
import os
import re
import json
import hashlib
import logging
from typing import List, Optional, Dict, Any
import httpx
from services.llm_client import LlmChat, UserMessage
from db import db, now_iso
from services.knowledge_retriever import retrieve, store as kb_store
from services.settings_service import get_setting
from services.capability_manifest import with_capability
from services.provider_selector import pick_provider

logger = logging.getLogger(__name__)

ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")
ADZUNA_COUNTRY = os.environ.get("ADZUNA_COUNTRY", "in")  # India by default

career_cache_col = db["career_cache"]
job_cache_col = db["job_cache"]
career_profile_col = db["career_profile"]

MAX_INTERVIEW_SUMMARIES = 3  # keep only the most recent N appended interview summaries


async def append_interview_summary(user_id: str, summary: str) -> None:
    """Mock Interview's write-path into Career Intelligence. Appends a short,
    prefixed summary into the SAME `career_profile_col.profile_text` field that
    score_and_draft_job() already reads verbatim for Gmail-pipeline job
    scoring (see the f-string at "CANDIDATE PROFILE:\\n{profile_text}" below) —
    so interview performance factors into that existing flow with zero changes
    to score_and_draft_job() itself. One-directional: interview -> career, never
    the reverse, which is what keeps Mock Interview otherwise well-isolated.

    Keeps only the most recent MAX_INTERVIEW_SUMMARIES appended blocks so a
    prolific interview-taker's profile_text doesn't grow unbounded — older
    interview summaries are dropped, not the rest of the candidate's own
    profile text (anything not inside a "[Mock Interview — ...]" block).
    """
    doc = await career_profile_col.find_one({"user_id": user_id}) or {}
    existing_text = doc.get("profile_text", "") or ""

    block_re = re.compile(r"\[Mock Interview —[^\]]*\][^\[]*", re.DOTALL)
    other_text = block_re.sub("", existing_text).strip()
    prior_blocks = block_re.findall(existing_text)

    new_block = f"[Mock Interview — {now_iso()[:10]}] {summary.strip()}\n"
    blocks = (prior_blocks + [new_block])[-MAX_INTERVIEW_SUMMARIES:]

    new_text = (other_text + "\n\n" if other_text else "") + "".join(blocks)
    await career_profile_col.update_one(
        {"user_id": user_id},
        {"$set": {"profile_text": new_text.strip(), "updated_at": now_iso()}},
        upsert=True,
    )


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


# ================= CAREER PIPELINE (Gmail scan → fit score + outreach draft) =================

PIPELINE_MAX_TOKENS = int(os.environ.get("CAREER_PIPELINE_MAX_TOKENS", "1200"))

PIPELINE_SYSTEM_PROMPT = (
    "You are a career pipeline assistant scoring one job listing against one candidate profile.\n"
    "Output ONLY a strict JSON object (no markdown fences, no prose). Schema:\n"
    '{"fit_score": int (0-100), "fit_reason": str (2-3 sentences, specific to this job and profile), '
    '"recruiter_title": str (the likely hiring-manager/recruiter job title at this company), '
    '"linkedin_search_query": str (a LinkedIn people-search query to find that person), '
    '"outreach_message": str (a short, specific LinkedIn connection-request note, under 300 characters)}'
)


def _extract_json(text: str) -> Dict[str, Any]:
    """Strip potential markdown fences and parse the first JSON object.

    Duplicated locally rather than shared — see the same small helper in
    builder_service.py and practice_ai_service.py.
    """
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError("LLM did not return JSON")


async def score_and_draft_job(job: Dict[str, Any], profile_text: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    """Fit score + recruiter outreach draft for one job listing.

    Cached like get_or_generate_learning_path above — identical (job, profile)
    pairs are free on repeat scans.
    """
    prompt_key = f"title={job.get('title','')} company={job.get('company') or ''} profile={profile_text}"

    if await get_setting("kb_enabled", True):
        hit = await retrieve("career_pipeline_fit", prompt_key, user_id=user_id)
        if hit and isinstance(hit["response"], dict):
            return {"cached": True, "source": "kb", **hit["response"]}

    prompt = (
        f"JOB TITLE: {job.get('title','')}\n"
        f"COMPANY: {job.get('company') or 'unknown'}\n"
        f"LOCATION: {job.get('location') or 'unknown'}\n\n"
        f"CANDIDATE PROFILE:\n{profile_text}"
    )
    provider, model = await pick_provider(user_id)
    chat = LlmChat(
        session_id=f"career-pipeline-{(user_id or 'anon')[:12]}",
        system_message=with_capability(PIPELINE_SYSTEM_PROMPT),
    ).with_model(provider, model, max_tokens=PIPELINE_MAX_TOKENS)
    resp = await chat.send_message(UserMessage(text=prompt))
    content = resp if isinstance(resp, str) else getattr(resp, "content", str(resp))

    try:
        parsed = _extract_json(content)
        payload = {
            "fit_score": int(parsed["fit_score"]) if parsed.get("fit_score") is not None else None,
            "fit_reason": str(parsed.get("fit_reason") or ""),
            "recruiter_title": str(parsed.get("recruiter_title") or ""),
            "linkedin_search_query": str(parsed.get("linkedin_search_query") or ""),
            "outreach_message": str(parsed.get("outreach_message") or ""),
        }
    except Exception:
        # One bad LLM response must not abort a whole scan — degrade to an
        # unscored entry the user can still see and manually work.
        logger.warning(f"career_pipeline: unparseable LLM response for job {job.get('title')!r}")
        payload = {
            "fit_score": None,
            "fit_reason": "Could not score this listing automatically.",
            "recruiter_title": "",
            "linkedin_search_query": "",
            "outreach_message": "",
        }

    await kb_store("career_pipeline_fit", prompt_key, payload, user_id=user_id,
                   meta={"provider": provider, "job_url": job.get("job_url")})
    return {"cached": False, "source": "llm", "provider": provider, **payload}


TERMS_SYSTEM_PROMPT = (
    "You turn a free-text career profile into a short job-board search query.\n"
    "Output ONLY a strict JSON object (no markdown fences, no prose): "
    '{"keywords": str (a short job-title-style phrase, e.g. "backend python developer", '
    'under 60 characters, no boolean operators), "location": str (a city/region if the '
    "profile mentions one, else an empty string)}"
)


async def derive_search_terms(profile_text: str, user_id: Optional[str] = None) -> Dict[str, str]:
    """Turn a free-text profile blurb into a short board-search query. Cached
    per exact profile text — the same profile always derives the same terms."""
    prompt_key = f"profile={profile_text}"

    if await get_setting("kb_enabled", True):
        hit = await retrieve("career_search_terms", prompt_key, user_id=user_id)
        if hit and isinstance(hit["response"], dict):
            return hit["response"]

    provider, model = await pick_provider(user_id)
    chat = LlmChat(
        session_id=f"career-terms-{(user_id or 'anon')[:12]}",
        system_message=with_capability(TERMS_SYSTEM_PROMPT),
    ).with_model(provider, model, max_tokens=200)
    resp = await chat.send_message(UserMessage(text=f"CANDIDATE PROFILE:\n{profile_text}"))
    content = resp if isinstance(resp, str) else getattr(resp, "content", str(resp))

    try:
        parsed = _extract_json(content)
        terms = {
            "keywords": str(parsed.get("keywords") or "").strip()[:60] or "software engineer",
            "location": str(parsed.get("location") or "").strip()[:80],
        }
    except Exception:
        logger.warning("career_pipeline: unparseable search-terms response, using a generic fallback")
        terms = {"keywords": "software engineer", "location": ""}

    await kb_store("career_search_terms", prompt_key, terms, user_id=user_id, meta={"provider": provider})
    return terms


# ================= Paid per-job add-ons: tailor, interview prep, salary coach =================
# Each follows score_and_draft_job's exact shape (KB cache -> pick_provider ->
# strict-JSON system prompt -> _extract_json with a graceful fallback) so a
# bad/missing LLM response degrades instead of crashing the request.

def _job_blurb(job: Dict[str, Any]) -> str:
    return f"{job.get('title','')} at {job.get('company') or 'unknown company'} ({job.get('location') or 'location unknown'})"


TAILOR_SYSTEM_PROMPT = (
    "You help a candidate tailor their resume and write a cover letter for ONE specific job.\n"
    "Output ONLY a strict JSON object (no markdown fences, no prose). Schema:\n"
    '{"ats_score": int (0-100, estimated match against this job), '
    '"tailoring_tips": [str] (3-5 concrete edits to the resume for this job), '
    '"cover_letter": str (a complete, specific cover letter, under 300 words)}'
)


async def tailor_resume_for_job(job: Dict[str, Any], resume_text: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    prompt_key = f"tailor|{job.get('title','')}|{job.get('company') or ''}|{resume_text}"
    if await get_setting("kb_enabled", True):
        hit = await retrieve("career_tailor_resume", prompt_key, user_id=user_id)
        if hit and isinstance(hit["response"], dict):
            return {"cached": True, "source": "kb", **hit["response"]}

    prompt = f"JOB: {_job_blurb(job)}\n\nCANDIDATE RESUME:\n{resume_text}"
    provider, model = await pick_provider(user_id)
    chat = LlmChat(
        session_id=f"career-tailor-{(user_id or 'anon')[:12]}",
        system_message=with_capability(TAILOR_SYSTEM_PROMPT),
    ).with_model(provider, model, max_tokens=1200)
    resp = await chat.send_message(UserMessage(text=prompt))
    content = resp if isinstance(resp, str) else getattr(resp, "content", str(resp))

    try:
        parsed = _extract_json(content)
        payload = {
            "ats_score": int(parsed["ats_score"]) if parsed.get("ats_score") is not None else None,
            "tailoring_tips": [str(t) for t in (parsed.get("tailoring_tips") or [])][:5],
            "cover_letter": str(parsed.get("cover_letter") or ""),
        }
    except Exception:
        logger.warning(f"career_tailor: unparseable LLM response for job {job.get('title')!r}")
        payload = {"ats_score": None, "tailoring_tips": [], "cover_letter": ""}

    await kb_store("career_tailor_resume", prompt_key, payload, user_id=user_id, meta={"provider": provider})
    return {"cached": False, "source": "llm", "provider": provider, **payload}


INTERVIEW_PREP_SYSTEM_PROMPT = (
    "You prepare a candidate for an interview for ONE specific job.\n"
    "Output ONLY a strict JSON object (no markdown fences, no prose). Schema:\n"
    '{"questions": [{"question": str, "why_asked": str, "model_answer": str}] '
    "(4-6 items, mixing role-specific technical and behavioral questions), "
    '"talking_points": [str] (3-5 things to bring up that connect the candidate to this role/company)}'
)


async def generate_interview_prep(job: Dict[str, Any], resume_text: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    prompt_key = f"interview_prep|{job.get('title','')}|{job.get('company') or ''}|{resume_text}"
    if await get_setting("kb_enabled", True):
        hit = await retrieve("career_interview_prep", prompt_key, user_id=user_id)
        if hit and isinstance(hit["response"], dict):
            return {"cached": True, "source": "kb", **hit["response"]}

    prompt = f"JOB: {_job_blurb(job)}\n\nCANDIDATE RESUME:\n{resume_text}"
    provider, model = await pick_provider(user_id)
    chat = LlmChat(
        session_id=f"career-interview-prep-{(user_id or 'anon')[:12]}",
        system_message=with_capability(INTERVIEW_PREP_SYSTEM_PROMPT),
    ).with_model(provider, model, max_tokens=1800)
    resp = await chat.send_message(UserMessage(text=prompt))
    content = resp if isinstance(resp, str) else getattr(resp, "content", str(resp))

    try:
        parsed = _extract_json(content)
        payload = {
            "questions": [
                {"question": str(q.get("question", "")), "why_asked": str(q.get("why_asked", "")),
                 "model_answer": str(q.get("model_answer", ""))}
                for q in (parsed.get("questions") or []) if isinstance(q, dict)
            ][:6],
            "talking_points": [str(t) for t in (parsed.get("talking_points") or [])][:5],
        }
    except Exception:
        logger.warning(f"career_interview_prep: unparseable LLM response for job {job.get('title')!r}")
        payload = {"questions": [], "talking_points": []}

    await kb_store("career_interview_prep", prompt_key, payload, user_id=user_id, meta={"provider": provider})
    return {"cached": False, "source": "llm", "provider": provider, **payload}


SALARY_COACH_SYSTEM_PROMPT = (
    "You are a salary negotiation coach helping a candidate for ONE specific job.\n"
    "Output ONLY a strict JSON object (no markdown fences, no prose). Schema:\n"
    '{"suggested_range": str (e.g. "18-24 LPA", your best estimate for this role/location/India market), '
    '"negotiation_script": str (a short script the candidate can adapt when asked about salary expectations), '
    '"key_points": [str] (3-5 negotiation leverage points specific to this candidate and role)}'
)


async def salary_negotiation_coach(job: Dict[str, Any], profile_text: str, user_id: Optional[str] = None) -> Dict[str, Any]:
    prompt_key = f"salary_coach|{job.get('title','')}|{job.get('company') or ''}|{profile_text}"
    if await get_setting("kb_enabled", True):
        hit = await retrieve("career_salary_coach", prompt_key, user_id=user_id)
        if hit and isinstance(hit["response"], dict):
            return {"cached": True, "source": "kb", **hit["response"]}

    prompt = f"JOB: {_job_blurb(job)}\n\nCANDIDATE PROFILE:\n{profile_text}"
    provider, model = await pick_provider(user_id)
    chat = LlmChat(
        session_id=f"career-salary-coach-{(user_id or 'anon')[:12]}",
        system_message=with_capability(SALARY_COACH_SYSTEM_PROMPT),
    ).with_model(provider, model, max_tokens=900)
    resp = await chat.send_message(UserMessage(text=prompt))
    content = resp if isinstance(resp, str) else getattr(resp, "content", str(resp))

    try:
        parsed = _extract_json(content)
        payload = {
            "suggested_range": str(parsed.get("suggested_range") or ""),
            "negotiation_script": str(parsed.get("negotiation_script") or ""),
            "key_points": [str(t) for t in (parsed.get("key_points") or [])][:5],
        }
    except Exception:
        logger.warning(f"career_salary_coach: unparseable LLM response for job {job.get('title')!r}")
        payload = {"suggested_range": "", "negotiation_script": "", "key_points": []}

    await kb_store("career_salary_coach", prompt_key, payload, user_id=user_id, meta={"provider": provider})
    return {"cached": False, "source": "llm", "provider": provider, **payload}


ADDON_CHAT_SYSTEM_PROMPT = (
    "You are continuing a conversation with a candidate about advice you already gave them for "
    "one specific job. Be direct and conversational (a few sentences unless they ask for depth). "
    "Reply in plain text — no JSON, no markdown headers."
)


async def continue_addon_chat(
    addon_type: str, job: Dict[str, Any], context: Dict[str, Any],
    history: List[Dict[str, str]], message: str, user_id: Optional[str] = None,
) -> str:
    """Stateless follow-up turn on a tailor/interview-prep/salary-coach result.
    Not KB-cached (conversational, not meant to be deduped) — the caller (and
    frontend) hold the transcript; this just takes one more turn on it."""
    context_text = json.dumps(context, indent=2)[:3000]
    transcript = "\n".join(f"{h.get('role', 'user').title()}: {h.get('content', '')}" for h in history[-8:])
    prompt = (
        f"JOB: {_job_blurb(job)}\n\n"
        f"YOUR EARLIER {addon_type.upper()} SUGGESTION:\n{context_text}\n\n"
        + (f"CONVERSATION SO FAR:\n{transcript}\n\n" if transcript else "")
        + f"CANDIDATE'S NEW MESSAGE:\n{message}"
    )
    provider, model = await pick_provider(user_id)
    chat = LlmChat(
        session_id=f"career-addon-chat-{(user_id or 'anon')[:12]}",
        system_message=with_capability(ADDON_CHAT_SYSTEM_PROMPT),
    ).with_model(provider, model, max_tokens=600)
    resp = await chat.send_message(UserMessage(text=prompt))
    return resp if isinstance(resp, str) else getattr(resp, "content", str(resp))
