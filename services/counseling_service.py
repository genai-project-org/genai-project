"""Counseling — Career, Psychology, Academic AI advisor.

Every call:
 1. Data-lake first (semantic retrieval)
 2. Fall through to Claude Haiku with a specialized system prompt
 3. Store the fresh response back to the KB
"""
import os
import logging
from typing import Optional
from emergentintegrations.llm.chat import LlmChat, UserMessage
from services.knowledge_retriever import retrieve, store as kb_store
from services.settings_service import get_setting
from services.capability_manifest import with_capability
from services.provider_selector import pick_provider
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
COUNSEL_MODEL = os.environ.get("COUNSEL_MODEL", "claude-haiku-4-5-20251001")

SYSTEM_PROMPTS = {
    "career": (
        "You are a warm, no-BS career counselor with 20 years of India-tech-industry experience. "
        "Give concrete, actionable advice, not platitudes. Ask clarifying questions ONLY if the user's goal is genuinely unclear. "
        "Structure long answers with clear headers and bullets. Cite realistic salary bands, timelines, and free resources when relevant."
    ),
    "psychology": (
        "You are a compassionate, evidence-based mental-wellness companion. You are NOT a licensed therapist and you say so up-front. "
        "Practice active listening, validate feelings, and share CBT/mindfulness-based coping strategies with concrete steps. "
        "If the user hints at self-harm or crisis, gently share the iCall India helpline (9152987821) and encourage professional help immediately."
    ),
    "academic": (
        "You are an expert academic coach for Indian students (school and university). Give concrete study plans, resource lists, "
        "exam strategies (JEE/NEET/CAT/GATE/UPSC/board exams), and habit systems. Be specific about timelines, and use free resources first (NPTEL, NCERT, Khan Academy, MIT OCW)."
    ),
}


async def counsel(mode: str, message: str, user_id: Optional[str] = None) -> dict:
    """Return {response, source, score, match, disclaimer}. Assumes `mode` is validated by the router."""
    kind = f"counseling:{mode}"

    if await get_setting("kb_enabled", True):
        hit = await retrieve(kind, message, user_id=user_id)
        if hit:
            return {
                "response": hit["response"],
                "source": "kb",
                "match": hit["match"],
                "score": hit["score"],
                "mode": mode,
            }

    if await get_setting("kb_only_mode", False):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Knowledge-only mode is on and no cached answer was found. Try rephrasing.")

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"counsel-{mode}-{(user_id or 'anon')[:12]}",
        system_message=with_capability(SYSTEM_PROMPTS[mode]),
    )
    provider, model = await pick_provider(user_id)
    chat = chat.with_model(provider, model)
    resp = await chat.send_message(UserMessage(text=message))
    content = resp if isinstance(resp, str) else getattr(resp, "content", str(resp))
    await kb_store(kind, message, content, user_id=user_id, meta={"mode": mode, "provider": provider})
    return {"response": content, "source": "llm", "mode": mode, "provider": provider}
