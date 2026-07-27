"""AI Studio — text summarization, image generation & Google Veo 3.1 video generation."""
import os
import logging
import time
import uuid
from pathlib import Path
from typing import List, Optional
from services.llm_client import LlmChat, UserMessage, OpenAIImageGeneration
from google import genai
from google.genai import types as genai_types
from services.knowledge_retriever import retrieve, store
from services.settings_service import get_setting
from services.capability_manifest import with_capability
from services.provider_selector import pick_provider
from services.ai_service import resolve_provider_model

logger = logging.getLogger(__name__)

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")

SUMMARIZE_SYSTEM = (
    "You are a concise summarizer. Produce structured markdown with: "
    "1) TL;DR (2 sentences), 2) Key Points (5 bullets), 3) Action Items (if any). "
    "Preserve numeric facts and named entities. No fluff."
)


async def summarize_text(session_id: str, text: str, style: str = "default", user_id: Optional[str] = None, model_override: Optional[str] = None) -> dict:
    """Summarize text. Returns {response, source, score} where source is 'kb'|'llm'."""
    kb_kind = f"studio_summarize:{style}"
    if await get_setting("kb_enabled", True):
        hit = await retrieve(kb_kind, text, user_id=user_id)
        if hit:
            return {"response": hit["response"], "source": "kb", "match": hit["match"], "score": hit["score"]}

    if await get_setting("kb_only_mode", False):
        from fastapi import HTTPException, status
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Knowledge-only mode is on and no cached answer was found.")

    system_prompt = SUMMARIZE_SYSTEM
    if style == "eli5":
        system_prompt += " Rewrite everything so a 12-year-old can understand it."
    elif style == "executive":
        system_prompt += " Tone: crisp executive brief. Focus on business impact."

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id,
        system_message=with_capability(system_prompt),
    )
    provider, model = resolve_provider_model(model_override) or await pick_provider(user_id)
    chat = chat.with_model(provider, model)
    resp = await chat.send_message(UserMessage(text=text))
    summary = resp if isinstance(resp, str) else getattr(resp, "content", str(resp))
    await store(kb_kind, text, summary, user_id=user_id, meta={"style": style, "provider": provider})
    return {"response": summary, "source": "llm", "provider": provider}


# User-facing image-model picker. "quality" applies to OpenAI models only.
# premium=True -> paid plans and admins only (see ai_service.ensure_premium_access).
IMAGE_MODEL_CATALOG = [
    {"id": "gpt-image-1",           "provider": "openai", "name": "GPT Image 1",      "description": "Balanced quality and speed", "default": True},
    {"id": "gpt-image-1-mini",      "provider": "openai", "name": "GPT Image 1 mini", "description": "Cheapest, quick drafts"},
    {"id": "gpt-image-2",           "provider": "openai", "name": "GPT Image 2",      "description": "Newest, best detail", "premium": True},
    {"id": "gemini-2.5-flash-image", "provider": "google", "name": "Gemini Flash Image", "description": "Google's fast image model"},
]
_IMAGE_MODEL_BY_ID = {m["id"]: m for m in IMAGE_MODEL_CATALOG}
DEFAULT_IMAGE_MODEL = next(m["id"] for m in IMAGE_MODEL_CATALOG if m.get("default"))

# Veo tiers. `tier` drives the pricing key (studio_video_{tier}_{duration}s) so
# adding a model here is all that is needed — no branching in the route.
VIDEO_MODEL_CATALOG = [
    {"id": "veo-lite", "tier": "lite", "name": "Veo Lite", "description": "Cheapest, quick drafts"},
    {"id": "veo-fast", "tier": "std",  "name": "Veo Fast", "description": "Faster, lower cost", "default": True},
    {"id": "veo-hq",   "tier": "pro",  "name": "Veo HQ",   "description": "Highest quality", "premium": True},
]
_VIDEO_MODEL_BY_ID = {m["id"]: m for m in VIDEO_MODEL_CATALOG}


def image_model_meta(model_id: Optional[str]) -> dict:
    """Catalog entry for an image model id, falling back to the default."""
    return _IMAGE_MODEL_BY_ID.get(model_id or "") or _IMAGE_MODEL_BY_ID[DEFAULT_IMAGE_MODEL]


def video_model_meta(model_id: Optional[str]) -> dict:
    return _VIDEO_MODEL_BY_ID.get(model_id or "") or _VIDEO_MODEL_BY_ID["veo-fast"]


async def generate_image_bytes(prompt: str, quality: str = "low", n: int = 1,
                               model: Optional[str] = None) -> List[bytes]:
    """Generate images with a catalog model; unknown ids fall back to the default."""
    sel = image_model_meta(model)
    gen = OpenAIImageGeneration(provider=sel["provider"])
    return await gen.generate_images(
        prompt=prompt,
        model=sel["id"],
        number_of_images=n,
        quality=quality,
    )



# ================= GOOGLE VEO 3.1 VIDEO GENERATION =================

# Resolve uploads directory in a platform-independent way.
BASE_DIR = Path(__file__).resolve().parent.parent

VIDEO_OUT_DIR = Path(
    os.environ.get(
        "BACKEND_UPLOADS_DIR",
        str(BASE_DIR / "uploads")
    )
) / "videos"

VIDEO_OUT_DIR.mkdir(parents=True, exist_ok=True)

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Veo 3.1 accepts a small set of durations and aspect ratios.
_ALLOWED_ASPECTS = {"16:9", "9:16", "1:1"}
_ALLOWED_DURATIONS = {4, 6, 8}
_MODEL_MAP = {
    # Public-facing names → Google model IDs (July 2026)
    "veo-lite": "veo-3.1-lite-generate-preview",
    "veo-fast": "veo-3.1-fast-generate-preview",
    "veo-hq":   "veo-3.1-generate-preview",
    # Backwards-compat: earlier UI still sends 'sora-2' / 'sora-2-pro' — route them.
    "sora-2":     "veo-3.1-fast-generate-preview",
    "sora-2-pro": "veo-3.1-generate-preview",
}


async def generate_video(prompt: str, model: str = "veo-fast",
                         aspect_ratio: str = "16:9", duration: int = 4,
                         negative_prompt: Optional[str] = None) -> dict:
    """Generate a video via Google Veo 3.1 using the Gemini API. Returns
    ``{filename, path, url_rel, aspect_ratio, duration, model, bytes}``.
    Raises on failure so the caller can refund credits."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured on the server.")
    google_model = _MODEL_MAP.get(model)
    if not google_model:
        raise ValueError(f"Unsupported model {model}; use one of {list(_MODEL_MAP)}")
    if aspect_ratio not in _ALLOWED_ASPECTS:
        raise ValueError(f"Unsupported aspect_ratio {aspect_ratio}; use one of {sorted(_ALLOWED_ASPECTS)}")
    if duration not in _ALLOWED_DURATIONS:
        raise ValueError(f"Unsupported duration {duration}s; use one of {sorted(_ALLOWED_DURATIONS)}")

    import asyncio as _aio

    def _run():
        client = genai.Client(api_key=GEMINI_API_KEY)
        cfg = genai_types.GenerateVideosConfig(
            aspect_ratio=aspect_ratio,
            resolution="720p",
            duration_seconds=duration,
            number_of_videos=1,
            **({"negative_prompt": negative_prompt} if negative_prompt else {}),
        )
        op = client.models.generate_videos(
            model=google_model,
            prompt=prompt,
            config=cfg,
        )
        # Veo takes 1–3 minutes for a fast preview; poll until done.
        deadline = time.monotonic() + 480   # 8-min hard cap
        while not op.done:
            if time.monotonic() > deadline:
                raise RuntimeError("Veo timed out after 8 minutes without returning a video.")
            time.sleep(10)
            op = client.operations.get(op)

        # Some Veo error paths surface via op.error; surface that verbatim.
        err = getattr(op, "error", None)
        if err:
            raise RuntimeError(f"Veo error: {getattr(err, 'message', str(err))}")

        gen_videos = getattr(op.response, "generated_videos", None) or []
        if not gen_videos:
            raise RuntimeError("Veo returned no videos — often a content-policy block. Try a different prompt.")
        gv = gen_videos[0]
        # Download the video bytes into memory / file.
        client.files.download(file=gv.video)
        filename = f"veo_{uuid.uuid4().hex}.mp4"
        out = VIDEO_OUT_DIR / filename
        gv.video.save(str(out))
        return filename, out

    filename, out = await _aio.to_thread(_run)
    return {
        "filename": filename,
        "path": str(out),
        "url_rel": f"/api/media-static/videos/{filename}",
        "aspect_ratio": aspect_ratio,
        "duration": duration,
        "model": model,
        "bytes": out.stat().st_size,
    }
