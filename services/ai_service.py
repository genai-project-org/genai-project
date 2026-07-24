"""Unified AI provider layer with failover Claude → OpenAI, with vision support."""
import os
import base64
import logging
from typing import AsyncGenerator, List, Dict, Optional
import httpx
from emergentintegrations.llm.chat import LlmChat, UserMessage, TextDelta, StreamDone, ImageContent
from services.capability_manifest import with_capability

logger = logging.getLogger(__name__)

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
DEFAULT_PROVIDER = os.environ.get("DEFAULT_AI_PROVIDER", "anthropic")
DEFAULT_MODEL = os.environ.get("DEFAULT_AI_MODEL", "claude-haiku-4-5-20251001")
FALLBACK_PROVIDER = os.environ.get("FALLBACK_AI_PROVIDER", "openai")
FALLBACK_MODEL = os.environ.get("FALLBACK_AI_MODEL", "gpt-5-mini")

SYSTEM_PROMPT = (
    "You are IEMA.ai, a premium AI assistant. Be concise, helpful, and precise. "
    "Format responses in markdown when useful. Use fenced code blocks with language for code."
)


def _build_chat(session_id: str, provider: str, model: str) -> LlmChat:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id,
        system_message=with_capability(SYSTEM_PROMPT),
    ).with_model(provider, model)
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
    providers_to_try = [(DEFAULT_PROVIDER, model_override or DEFAULT_MODEL), (FALLBACK_PROVIDER, FALLBACK_MODEL)]

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
