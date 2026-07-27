"""Unified AI provider layer with failover Claude → OpenAI, with vision support."""
import os
import base64
import logging
from typing import AsyncGenerator, List, Dict, Optional
import httpx
from services.llm_client import LlmChat, UserMessage, TextDelta, StreamDone, ImageContent
from services.capability_manifest import with_capability

logger = logging.getLogger(__name__)

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
DEFAULT_PROVIDER = os.environ.get("DEFAULT_AI_PROVIDER", "anthropic")
DEFAULT_MODEL = os.environ.get("DEFAULT_AI_MODEL", "claude-haiku-4-5-20251001")
FALLBACK_PROVIDER = os.environ.get("FALLBACK_AI_PROVIDER", "openai")
FALLBACK_MODEL = os.environ.get("FALLBACK_AI_MODEL", "gpt-5-mini")

# User-facing model catalog. provider=None ("iema") means auto-route via the default path.
# max_tokens: Claude 5 / Sonnet 5 run adaptive thinking by default, and thinking
# shares the max_tokens budget with the answer — the 4096 default truncates them.
MODEL_CATALOG = [
    {"id": "iema",                       "provider": None,        "name": "IEMA Knowledge Engine", "label": "Recommended", "description": "Smart auto-routing (recommended)"},
    {"id": "claude-haiku-4-5-20251001",  "provider": "anthropic", "name": "Claude Haiku 4.5",      "label": "Fast",     "description": "Quick everyday answers", "default": True},
    {"id": "claude-sonnet-4-5-20250929", "provider": "anthropic", "name": "Claude Sonnet 4.5",     "label": "Balanced", "description": "Deeper reasoning, still snappy", "premium": True},
    {"id": "claude-sonnet-5",            "provider": "anthropic", "name": "Claude Sonnet 5",       "label": "Smart",    "description": "Near-flagship quality, Sonnet speed", "max_tokens": 32000, "premium": True},
    {"id": "claude-opus-5",              "provider": "anthropic", "name": "Claude Opus 5",         "label": "Flagship", "description": "Deepest reasoning & long context", "max_tokens": 32000, "premium": True},
    {"id": "gpt-5",                      "provider": "openai",    "name": "GPT-5",                 "label": "Powerful", "description": "Hardest tasks & long context", "premium": True},
    {"id": "gpt-5-mini",                 "provider": "openai",    "name": "GPT-5 mini",            "label": "Quick",    "description": "Lightweight versatile model"},
    {"id": "gpt-5-nano",                 "provider": "openai",    "name": "GPT-5 nano",            "label": "Cheapest", "description": "Simple tasks at the lowest cost", "max_tokens": 16000},
    {"id": "gpt-4.1-mini",               "provider": "openai",    "name": "GPT-4.1 mini",          "label": "Snappy",   "description": "Fast replies, no reasoning delay"},
    {"id": "gemini-3.6-flash",           "provider": "google",    "name": "Gemini 3.6 Flash",      "label": "Versatile", "description": "Google's fast multimodal model"},
    {"id": "gemini-3.5-flash-lite",      "provider": "google",    "name": "Gemini 3.5 Flash Lite", "label": "Economy",  "description": "Lowest-cost Google model"},
]
_MODEL_BY_ID = {m["id"]: m for m in MODEL_CATALOG}


def resolve_provider_model(model_id: Optional[str]):
    """Map a catalog model id to (provider, model). Returns None for auto-route (iema/unknown)."""
    sel = _MODEL_BY_ID.get(model_id)
    if sel and sel["provider"]:
        return sel["provider"], sel["id"]
    return None


def max_tokens_for(model: str) -> Optional[int]:
    """Per-model output budget, or None to use the client default."""
    sel = _MODEL_BY_ID.get(model)
    return sel.get("max_tokens") if sel else None


# ---- premium (paid-plan-only) models -------------------------------------
# The high-cost models burn several times the tokens of Haiku/mini for the same
# flat credit price, so they are reserved for paid plans and admins.
PREMIUM_MODEL_IDS = frozenset(m["id"] for m in MODEL_CATALOG if m.get("premium"))


def is_premium_model(model_id: Optional[str]) -> bool:
    return model_id in PREMIUM_MODEL_IDS


def plan_allows_premium(plan: dict, role: Optional[str] = None) -> bool:
    """Paid plans and admins only. Unknown/missing plan is treated as free."""
    if role == "admin":
        return True
    return not bool((plan or {}).get("is_free", True))


async def user_allows_premium(user_id: str, role: Optional[str] = None) -> bool:
    if role == "admin":       # skip the DB read for admins
        return True
    from services.pricing_engine import get_user_plan
    return plan_allows_premium(await get_user_plan(user_id), role)


async def ensure_premium_access(user_id: str, role: Optional[str],
                                premium: bool, name: str) -> None:
    """Raise 403 when a free-plan user reaches for a premium chat/image/video model.

    The one place the paid boundary is enforced. Pickers also grey these out, but
    that is cosmetic — this is what actually stops the spend.
    """
    if not premium:
        return
    if await user_allows_premium(user_id, role):
        return
    from fastapi import HTTPException
    raise HTTPException(403, f"{name} is available on Pro and Team plans. Upgrade to use it.")


async def ensure_model_allowed(user_id: str, role: Optional[str], model_id: Optional[str]) -> None:
    """Chat-catalog wrapper around ensure_premium_access()."""
    await ensure_premium_access(
        user_id, role, is_premium_model(model_id),
        (_MODEL_BY_ID.get(model_id) or {}).get("name", model_id),
    )

SYSTEM_PROMPT = (
    "You are IEMA.ai, a premium AI assistant. Be concise, helpful, and precise. "
    "Format responses in markdown when useful. Use fenced code blocks with language for code."
)


def _build_chat(session_id: str, provider: str, model: str) -> LlmChat:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id,
        system_message=with_capability(SYSTEM_PROMPT),
    ).with_model(provider, model, max_tokens=max_tokens_for(model))
    return chat


async def _url_to_base64(url: str) -> Optional[str]:
    """Fetch an image URL and return base64-encoded content."""
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            r = await http.get(url)
            if r.status_code == 200:
                return base64.b64encode(r.content).decode("ascii")
    except Exception as e:
        logger.warning(f"Failed fetching image {url}: {e}")
    return None


async def stream_ai_response(
    session_id: str,
    user_message: str,
    history: List[Dict],
    model_override: Optional[str] = None,
    attachments: Optional[List[Dict]] = None,
) -> AsyncGenerator[Dict, None]:
    """
    Stream tokens from AI. Yields dicts: {"type": "meta"|"delta"|"done"|"error", ...}
    attachments: list of {"url": ..., "content_type": "image/png"} — fetched and passed as base64.
    """
    tried = []
    primary = resolve_provider_model(model_override) or (DEFAULT_PROVIDER, DEFAULT_MODEL)
    providers_to_try = [primary]
    if (FALLBACK_PROVIDER, FALLBACK_MODEL) != primary:  # dedupe when user picked the fallback
        providers_to_try.append((FALLBACK_PROVIDER, FALLBACK_MODEL))

    # Preload attachments to base64 once
    image_contents = []
    if attachments:
        for att in attachments:
            if not att.get("content_type", "").startswith("image/"):
                continue
            b64 = await _url_to_base64(att["url"]) if att.get("url") else None
            if b64:
                image_contents.append(ImageContent(image_base64=b64))

    for provider, model in providers_to_try:
        tried.append(f"{provider}:{model}")
        try:
            chat = _build_chat(session_id, provider, model)
            prefix = _history_prefix(history)
            final_text = (prefix + "\n\nUser: " + user_message) if prefix else user_message
            um = UserMessage(text=final_text, file_contents=image_contents or None)
            yield {"type": "meta", "provider": provider, "model": model}
            full_text = ""
            async for event in chat.stream_message(um):
                if isinstance(event, TextDelta):
                    full_text += event.content
                    yield {"type": "delta", "content": event.content}
                elif isinstance(event, StreamDone):
                    break
            yield {"type": "done", "content": full_text, "provider": provider, "model": model}
            return
        except Exception as e:
            logger.exception(f"AI provider {provider} failed: {e}")
            yield {"type": "warn", "message": f"Provider {provider} failed, switching..."}
            continue

    yield {"type": "error", "message": f"All AI providers failed. Tried: {', '.join(tried)}"}


def _history_prefix(history: List[Dict], max_msgs: int = 10) -> str:
    if not history:
        return ""
    recent = history[-max_msgs:]
    lines = []
    for m in recent:
        role = "User" if m.get("role") == "user" else "Assistant"
        lines.append(f"{role}: {m.get('content', '')}")
    return "Previous conversation:\n" + "\n".join(lines)
