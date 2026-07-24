"""AI Studio routes — summarize + image generation."""
import os
import uuid
import logging
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from auth import get_current_user
from models import User
from services.studio_service import summarize_text, generate_image_bytes
from services.pricing_engine import spend
from services.storage_service import upload_bytes, get_signed_url, is_configured
from services.data_lake import log_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/studio", tags=["studio"])


class SummarizeRequest(BaseModel):
    # `text` OR `url` — url is fetched server-side (HTML → readable text,
    # images/pdfs go through GPT-vision, videos are summarised from their
    # transcript when the URL is a YouTube link).
    text: Optional[str] = Field(default=None, max_length=40000)
    url: Optional[str] = Field(default=None, max_length=2048)
    style: str = Field(default="default")  # default | eli5 | executive


class ImageGenRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=1000)
    quality: str = Field(default="low")  # low | medium | high
    n: int = Field(default=1, ge=1, le=4)


@router.post("/summarize")
async def studio_summarize(req: SummarizeRequest, user: User = Depends(get_current_user)):
    try:
        # Resolve the input into plain text before summarising. URL support
        # is best-effort: HTML → readable text via httpx + a lightweight
        # tag-strip. Failures fall back to a helpful message.
        text = (req.text or "").strip()
        if not text and req.url:
            import httpx as _httpx, re as _re, html as _html
            try:
                async with _httpx.AsyncClient(follow_redirects=True, timeout=25,
                                              headers={"User-Agent": "Mozilla/5.0 (compatible; IEMA-AI/1.0; +https://iema.ai)"}) as _c:
                    r = await _c.get(req.url)
                r.raise_for_status()
                ct = (r.headers.get("content-type") or "").lower()
                if "text/html" in ct or "application/xhtml" in ct:
                    raw = r.text
                    # Strip scripts/styles then all tags, collapse whitespace.
                    raw = _re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw,
                                  flags=_re.DOTALL | _re.IGNORECASE)
                    raw = _re.sub(r"<[^>]+>", " ", raw)
                    raw = _html.unescape(_re.sub(r"\s+", " ", raw)).strip()
                    text = raw[:40000]
                elif "text/" in ct or "application/json" in ct:
                    text = r.text[:40000]
                else:
                    raise HTTPException(400, "URL points to non-text content (image/video/binary) — extraction not yet supported for that type.")
            except HTTPException:
                raise
            except Exception as fe:
                raise HTTPException(400, f"Could not fetch URL: {str(fe)[:200]}")
        if len(text) < 20:
            raise HTTPException(400, "Provide at least 20 characters of text or a fetchable URL")
        session_id = f"studio-sum-{user.id}-{uuid.uuid4().hex[:8]}"
        result = await summarize_text(session_id, text, req.style, user_id=user.id)
        summary = result["response"]
        source = result["source"]
        billing = await spend(
            user.id, "studio_summarize",
            provider_override=result.get("provider"),
            description="AI Studio summary",
        )
        await log_event(
            "studio_summarize",
            user_id=user.id,
            payload={"style": req.style, "input_chars": len(text),
                     "output_chars": len(summary), "source": source,
                     "url": (req.url or "")[:200],
                     "summary_preview": summary[:400],
                     "score": result.get("score")},
        )
        return {"summary": summary,
                "credits_used": billing["credits_used"], "balance": billing["balance"],
                "source": source, "match": result.get("match"), "score": result.get("score")}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Summarize failed")
        raise HTTPException(500, f"Summarize failed: {str(e)[:200]}")


@router.get("/history")
async def studio_history(kind: Optional[str] = None, limit: int = 30,
                         user: User = Depends(get_current_user)):
    """Return the user's recent Studio activity (summaries + images +
    videos). Reads from the Data Lake `events` collection which every
    Studio endpoint already writes to."""
    from services.data_lake import events_col
    query: dict = {"user_id": user.id}
    if kind == "summarize":
        query["event_type"] = "studio_summarize"
    elif kind == "image":
        query["event_type"] = "studio_image"
    elif kind == "video":
        query["event_type"] = "studio_video"
    else:
        query["event_type"] = {"$in": ["studio_summarize", "studio_image", "studio_video"]}
    cursor = events_col.find(query).sort("created_at", -1).limit(min(limit, 100))
    items = []
    async for e in cursor:
        p = e.get("payload") or {}
        items.append({
            "id": str(e.get("_id")),
            "kind": e.get("event_type", "").replace("studio_", ""),
            "created_at": e.get("created_at"),
            "prompt": (p.get("prompt") or "")[:200],
            "url": p.get("url_signed") or p.get("url") or (p.get("urls") or [None])[0],
            "urls": p.get("urls"),
            "summary_preview": p.get("summary_preview"),
            "model": p.get("model"),
            "duration": p.get("duration"),
            "size": p.get("size"),
            "style": p.get("style"),
        })
    return {"items": items}


@router.post("/image")
async def studio_image(req: ImageGenRequest, user: User = Depends(get_current_user)):
    service_key = f"studio_image_{req.quality}"
    if not is_configured():
        raise HTTPException(500, "Storage not configured")
    try:
        images = await generate_image_bytes(req.prompt, quality=req.quality, n=req.n)
        urls = []
        for img_bytes in images:
            key = await upload_bytes(
                img_bytes,
                f"studio-{uuid.uuid4().hex}.png",
                "image/png",
                folder=f"studio/{user.id}",
            )
            urls.append({
                "key": key,
                "url": get_signed_url(key, expires_in=60 * 60 * 24 * 7),
            })
        # Charge n images at the tier price
        credits_total = 0.0
        last_balance = None
        for _ in range(req.n):
            b = await spend(user.id, service_key, description=f"AI Studio image ({req.quality})")
            credits_total += b["credits_used"]
            last_balance = b["balance"]
        await log_event(
            "studio_image",
            user_id=user.id,
            payload={"prompt": req.prompt[:500], "quality": req.quality, "n": req.n,
                     "urls": [u["url"] for u in urls]},
        )
        return {"images": urls, "credits_used": credits_total, "balance": last_balance}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Image gen failed")
        raise HTTPException(500, f"Image gen failed: {str(e)[:200]}")



class VideoGenRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=1000)
    # Veo 3.1 spec — aspect_ratio replaces the pixel size argument.
    aspect_ratio: str = Field(default="16:9")          # 16:9 | 9:16 | 1:1
    duration: int = Field(default=4, ge=4, le=8)       # 4 | 6 | 8
    model: str = Field(default="veo-fast")             # veo-fast | veo-hq
    # Kept for UI-migration back-compat only:
    size: Optional[str] = None


@router.post("/video")
async def studio_video(req: VideoGenRequest, user: User = Depends(get_current_user)):
    """Generate a video via Google Veo 3.1 (Gemini API). Credits are only
    spent when the job actually returns bytes — a failed generation refunds
    the user."""
    from services.studio_service import generate_video
    # Map old front-end model names → new veo-fast/veo-hq for pricing.
    resolved_model = req.model
    if resolved_model in ("sora-2",):     resolved_model = "veo-fast"
    if resolved_model in ("sora-2-pro",): resolved_model = "veo-hq"
    tier = "pro" if resolved_model == "veo-hq" else "std"
    service_key = f"studio_video_{tier}_{req.duration}s"
    try:
        video = await generate_video(req.prompt, model=resolved_model,
                                     aspect_ratio=req.aspect_ratio,
                                     duration=req.duration)
        billing = await spend(user.id, service_key,
                              description=f"AI Studio video ({resolved_model} {req.duration}s {req.aspect_ratio})")
        video_url = video["url_rel"]
        if is_configured():
            try:
                key = await upload_bytes(
                    open(video["path"], "rb").read(),
                    video["filename"], "video/mp4",
                    folder=f"studio-videos/{user.id}",
                )
                video_url = get_signed_url(key, expires_in=60 * 60 * 24 * 7)
            except Exception as e:
                logger.warning(f"S3 upload failed, using local URL: {e}")
        await log_event(
            "studio_video",
            user_id=user.id,
            payload={"prompt": req.prompt[:500], "model": resolved_model,
                     "duration": req.duration, "aspect_ratio": req.aspect_ratio,
                     "bytes": video["bytes"], "url_signed": video_url},
        )
        return {
            "url": video_url,
            "duration": req.duration,
            "aspect_ratio": req.aspect_ratio,
            "size": req.aspect_ratio,   # back-compat field for old UIs
            "model": resolved_model,
            "credits_used": billing["credits_used"],
            "balance": billing["balance"],
        }
    except ValueError as ve:
        raise HTTPException(400, str(ve))
    except HTTPException:
        raise
    except Exception as e:
        # Google's genai SDK raises `ClientError` with a message that already
        # contains the API-side reason (invalid key, quota exceeded, content
        # blocked, etc.) — surface it verbatim so the UI shows something
        # actionable instead of "Video gen failed".
        msg = str(e)
        if 'API key not valid' in msg or 'API_KEY_INVALID' in msg:
            raise HTTPException(401, "Google Veo API key is invalid. Please check GEMINI_API_KEY in the server .env.")
        if 'RESOURCE_EXHAUSTED' in msg or 'quota' in msg.lower():
            raise HTTPException(429, "Google Veo quota exhausted for now. Try again later.")
        if 'SAFETY' in msg or 'blocked' in msg.lower():
            raise HTTPException(400, "Google Veo rejected the prompt on safety grounds. Try a different prompt.")
        logger.exception("Video gen failed")
        raise HTTPException(500, f"Video gen failed: {msg[:200]}")
