"""Resume Profile — persisted, structured CV.

Unlike `resume_service.py` (deliberately stateless per its own docstring),
this module OWNS `resume_profiles_col`: one structured profile per user,
built once from an uploaded/pasted resume and reused by Resume Intelligence
("save as profile"), Career Intelligence, and Mock Interviews' `get_candidate_context`
agent tool — none of which should have to re-upload/re-parse a resume every time.
"""
import re
import json
import logging
from typing import Optional, Dict, Any

from db import resume_profiles_col, now_iso
from services.llm_client import LlmChat, UserMessage
from services.provider_selector import pick_provider
from services.resume_service import extract_text
from services.capability_manifest import with_capability

logger = logging.getLogger(__name__)

STRUCTURE_SYSTEM_PROMPT = """You extract structured data from a resume. Reply with ONLY a strict JSON object, no markdown fences, no prose. Schema:
{"skills": [str], "years_experience": number, "work_history": [{"company": str, "title": str, "start": str, "end": str, "bullets": [str]}], "projects": [{"name": str, "description": str, "tech": [str]}], "education": [{"institution": str, "degree": str, "year": str}], "certifications": [str]}
Infer years_experience from the work history dates (0 if none found). Keep bullets concise (one line each). Omit fields you truly cannot find (empty list / 0) — never invent employers, titles or dates."""


def _extract_json(text: str) -> Dict[str, Any]:
    """Same small strip-fences-then-parse helper duplicated across this codebase's
    other LLM-returns-JSON call sites (career_service, builder_service, practice_ai_service)."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    start, end = text.find("{"), text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError("LLM did not return JSON")


async def get_profile(user_id: str) -> Optional[dict]:
    return await resume_profiles_col.find_one({"user_id": user_id})


async def build_profile(
    user_id: str,
    *,
    filename: Optional[str] = None,
    file_bytes: Optional[bytes] = None,
    pasted_text: str = "",
    ats_score: Optional[int] = None,
    shortlist_chance: Optional[int] = None,
) -> dict:
    """Parse (file or pasted text) into raw_text, then run one structured-JSON LLM
    pass over it. Upserts `resume_profiles_col` — one profile per user, replacing
    any prior one (a candidate has exactly one current CV on file).

    `ats_score`/`shortlist_chance` are optional pass-throughs from a Resume
    Intelligence analysis run in the same request, so "analyze then save as
    profile" doesn't need a second LLM call just to recompute them.
    """
    if file_bytes and filename:
        raw_text = extract_text(filename, file_bytes)
        source = "upload"
    else:
        raw_text = (pasted_text or "").strip()
        source = "paste"
    if len(raw_text) < 50:
        raise ValueError("Not enough resume text to build a profile")

    provider, model = await pick_provider(user_id)
    chat = LlmChat(
        session_id=f"resume-profile-{user_id[:12]}",
        system_message=with_capability(STRUCTURE_SYSTEM_PROMPT),
    ).with_model(provider, model, max_tokens=2000)
    resp = await chat.send_message(UserMessage(text=raw_text[:20000]))
    content = resp if isinstance(resp, str) else getattr(resp, "content", str(resp))
    try:
        structured = _extract_json(content)
    except Exception:
        logger.warning("resume_profile_service: unparseable structuring response, saving raw text only")
        structured = {}

    doc = {
        "user_id": user_id,
        "raw_text": raw_text,
        "structured": structured,
        "ats_score": ats_score,
        "shortlist_chance": shortlist_chance,
        "source": source,
        "filename": filename,
        "updated_at": now_iso(),
    }
    existing = await resume_profiles_col.find_one({"user_id": user_id})
    if existing:
        await resume_profiles_col.update_one({"user_id": user_id}, {"$set": doc})
    else:
        doc["created_at"] = now_iso()
        await resume_profiles_col.insert_one(doc)
    return await resume_profiles_col.find_one({"user_id": user_id})


def to_public(doc: dict) -> dict:
    return {
        "id": str(doc["_id"]),
        "structured": doc.get("structured", {}),
        "ats_score": doc.get("ats_score"),
        "shortlist_chance": doc.get("shortlist_chance"),
        "source": doc.get("source", "upload"),
        "filename": doc.get("filename"),
        "updated_at": doc.get("updated_at"),
    }


def condensed_context(doc: Optional[dict]) -> str:
    """Short plain-text summary for the interview agent's `get_candidate_context`
    tool — grounded in the structured fields, capped so it can't dominate the
    per-turn system prompt on a candidate with a very long work history."""
    if not doc:
        return "No resume on file for this candidate — ask about background directly."
    s = doc.get("structured") or {}
    lines = []
    if s.get("years_experience") is not None:
        lines.append(f"Years of experience: {s['years_experience']}")
    if s.get("skills"):
        lines.append(f"Skills: {', '.join(s['skills'][:20])}")
    for job in (s.get("work_history") or [])[:4]:
        bullets = "; ".join((job.get("bullets") or [])[:3])
        lines.append(f"- {job.get('title', '')} at {job.get('company', '')} "
                     f"({job.get('start', '')}–{job.get('end', '')}): {bullets}")
    for proj in (s.get("projects") or [])[:3]:
        lines.append(f"Project: {proj.get('name', '')} — {proj.get('description', '')}")
    text = "\n".join(lines)[:3000]
    return text or "Resume on file but no structured detail could be extracted."
