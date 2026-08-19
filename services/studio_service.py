"""AI Studio — text summarization, image generation & Google Veo 3.1 video generation."""
import os
import io
import asyncio
import shutil
import subprocess
import logging
import time
import uuid
from pathlib import Path
from typing import List, Optional
from PIL import Image, ImageDraw, ImageFont
from services.llm_client import LlmChat, UserMessage, OpenAIImageGeneration
from google import genai
from google.genai import types as genai_types
from services.knowledge_retriever import retrieve, store
from services.settings_service import get_setting
from services.capability_manifest import with_capability
from services.provider_selector import pick_provider
from services.ai_service import resolve_provider_model

logger = logging.getLogger(__name__)


# ================= REAL-PERSON IMPERSONATION GUARDRAIL =================
# App Store / Play Store Restricted Content policies require apps not use AI
# to generate deceptive content or impersonate real people. The image/video
# vendors (OpenAI, Veo) apply their own moderation, but that's inconsistent
# across providers/versions — this is a first-party check we control.
IMPERSONATION_SYSTEM = (
    "You are a safety classifier for an AI image/video generator. Decide "
    "whether the prompt asks for a realistic depiction of a SPECIFIC named or "
    "otherwise clearly identifiable real person (a public figure, celebrity, "
    "politician, or private individual named or described uniquely enough to "
    "identify them) — as opposed to a generic/anonymous person or a named "
    "FICTIONAL character. Reply with exactly one word: BLOCK or ALLOW."
)


async def check_impersonation_risk(prompt: str) -> Optional[str]:
    """Returns a user-facing block reason, or None if the prompt looks safe."""
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"studio-mod-{uuid.uuid4().hex[:8]}",
        system_message=IMPERSONATION_SYSTEM,
    ).with_model("openai", "gpt-5-nano")
    try:
        resp = await chat.send_message(UserMessage(text=prompt))
        verdict = (resp if isinstance(resp, str) else getattr(resp, "content", str(resp))).strip().upper()
        if verdict.startswith("BLOCK"):
            return ("This prompt appears to request a realistic depiction of a specific "
                    "real person, which isn't allowed. Try a generic or fictional "
                    "description instead.")
    except Exception:
        logger.exception("Impersonation guardrail check failed; allowing by default")
    return None


# ================= AI-GENERATED CONTENT LABELING =================
# Play/App Store guidance calls for AI-generated media to stay identifiable
# once it leaves the app (export/share) — the in-app "GPT Image 1" badge
# never survives a save/share, so the label needs to be burned into the
# asset itself.
_WATERMARK_LABEL = "AI-generated · IEMA.ai"


def _watermark_image(img_bytes: bytes) -> bytes:
    """Stamp a visible, semi-transparent label in a corner. Best-effort —
    any failure here must not block image generation, so it falls back to
    returning the untouched bytes."""
    try:
        img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        font_size = max(14, img.width // 40)
        try:
            font = ImageFont.truetype("DejaVuSans-Bold.ttf", font_size)
        except Exception:
            font = ImageFont.load_default()  # bundled with Pillow, always available
        bbox = draw.textbbox((0, 0), _WATERMARK_LABEL, font=font)
        text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        pad = font_size // 2
        x = img.width - text_w - pad * 2
        y = img.height - text_h - pad * 2
        draw.rectangle([x, y, x + text_w + pad * 2, y + text_h + pad * 2], fill=(0, 0, 0, 120))
        draw.text((x + pad, y + pad - bbox[1]), _WATERMARK_LABEL, font=font, fill=(255, 255, 255, 230))
        out = Image.alpha_composite(img, overlay).convert("RGB")
        buf = io.BytesIO()
        out.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        logger.exception("Image watermarking failed; returning unwatermarked image")
        return img_bytes


def _watermark_video_if_possible(path: Path) -> None:
    """Best-effort burn-in via ffmpeg's drawtext filter. Silently no-ops when
    ffmpeg isn't installed on this host rather than failing generation — this
    host doesn't currently ship ffmpeg, so treat this as pending until it's
    added to the deployment."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logger.warning("ffmpeg not found — video generated without a visible AI-generated watermark")
        return
    tmp = path.with_suffix(".tmp.mp4")
    cmd = [
        ffmpeg, "-y", "-i", str(path),
        "-vf", "drawtext=text='AI-generated - IEMA.ai':fontcolor=white@0.85:fontsize=h/25:"
               "box=1:boxcolor=black@0.45:boxborderw=8:x=w-tw-16:y=h-th-16",
        "-codec:a", "copy", str(tmp),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=120)
        tmp.replace(path)
    except Exception as e:
        logger.warning(f"ffmpeg watermark burn-in failed, keeping original video: {e}")
        tmp.unlink(missing_ok=True)

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
    block_reason = await check_impersonation_risk(prompt)
    if block_reason:
        raise ValueError(block_reason)
    sel = image_model_meta(model)
    gen = OpenAIImageGeneration(provider=sel["provider"])
    images = await gen.generate_images(
        prompt=prompt,
        model=sel["id"],
        number_of_images=n,
        quality=quality,
    )
    return await asyncio.gather(*(asyncio.to_thread(_watermark_image, b) for b in images))



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
    block_reason = await check_impersonation_risk(prompt)
    if block_reason:
        raise ValueError(block_reason)

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
        _watermark_video_if_possible(out)
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
