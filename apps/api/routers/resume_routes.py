"""Resume Intelligence routes — ATS scoring against an optional job description."""
import logging
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from auth import get_current_user
from models import User
from services.resume_service import analyze, extract_text, MIN_RESUME_CHARS
from services.pricing_engine import spend, precheck
from services.data_lake import log_event
from services import resume_profile_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/resume", tags=["resume"])

# Nothing upstream caps the body — starlette has no limit and the Procfile passes no
# uvicorn flag — so this read() ceiling IS the limit.
MAX_SIZE = 5 * 1024 * 1024  # 5 MB


@router.post("/analyze")
async def analyze_resume(
    file: UploadFile = File(None),
    resume_text: str = Form(""),
    job_description: str = Form(""),
    target_role: str = Form(""),
    user: User = Depends(get_current_user),
):
    # An untouched <input type="file"> still sends a part with filename="" — truthy
    # UploadFile, empty file. Check the filename, not the object.
    if file and file.filename:
        # Read MAX_SIZE+1 to detect oversize without buffering a hostile upload whole
        # (same trick as uploads_routes.py).
        data = await file.read(MAX_SIZE + 1)
        if len(data) > MAX_SIZE:
            raise HTTPException(400, "File too large. Max 5MB.")
        resume_text = extract_text(file.filename, data)

    if len((resume_text or "").strip()) < MIN_RESUME_CHARS:
        raise HTTPException(400, f"Upload a resume (PDF/DOCX/TXT) or paste at least {MIN_RESUME_CHARS} characters of resume text.")

    try:
        # gate runs only on a KB miss, right before the LLM call — so a cached report
        # stays free, but we never pay a provider for a report we'd then have to throw
        # away because spend()'s own _guard raised 429/402.
        result = await analyze(
            resume_text, job_description, target_role,
            user_id=user.id,
            gate=lambda: precheck(user.id, "resume_analyze"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Resume analysis failed")
        raise HTTPException(500, f"Resume analysis failed: {str(e)[:200]}")

    billing = await spend(
        user.id, "resume_analyze",
        provider_override=result.get("provider"),
        skip_charge=(result["source"] == "kb"),
        description="Resume analysis",
    )
    await log_event(
        "resume_analyze", user_id=user.id,
        payload={"chars_in": len(resume_text), "chars_out": len(result["response"]),
                 "has_jd": bool(job_description.strip()), "role": target_role.strip()[:120],
                 "ats_score": result.get("ats_score"), "source": result["source"],
                 "report": result["response"]},
    )
    return {
        "response": result["response"],
        "ats_score": result.get("ats_score"),
        "shortlist_chance": result.get("shortlist_chance"),
        # What the parser actually saw. The user's own resume going back to the user who
        # just uploaded it — and for an ATS tool it doubles as the parse-quality check.
        "resume_text": resume_text,
        "source": result["source"],
        "score": result.get("score"),
        "match": result.get("match"),
        "credits_used": billing["credits_used"],
        "balance": billing["balance"],
    }


# ================= Persisted resume profile =================
# Unlike /analyze above (stateless, per-request), this builds and stores a
# structured CV once so Career Intelligence and Mock Interviews can reference
# "the candidate's resume" without re-uploading it every time. Free — the
# structuring LLM call is cheap and this isn't a billed feature on its own.

@router.get("/profile")
async def get_resume_profile(user: User = Depends(get_current_user)):
    doc = await resume_profile_service.get_profile(user.id)
    if not doc:
        return {"profile": None}
    return {"profile": resume_profile_service.to_public(doc)}


@router.post("/profile")
async def save_resume_profile(
    file: UploadFile = File(None),
    resume_text: str = Form(""),
    ats_score: str = Form(""),
    shortlist_chance: str = Form(""),
    user: User = Depends(get_current_user),
):
    file_bytes, filename = None, None
    if file and file.filename:
        file_bytes = await file.read(MAX_SIZE + 1)
        if len(file_bytes) > MAX_SIZE:
            raise HTTPException(400, "File too large. Max 5MB.")
        filename = file.filename
    elif len((resume_text or "").strip()) < MIN_RESUME_CHARS:
        raise HTTPException(400, f"Upload a resume (PDF/DOCX/TXT) or paste at least {MIN_RESUME_CHARS} characters of resume text.")

    try:
        doc = await resume_profile_service.build_profile(
            user.id, filename=filename, file_bytes=file_bytes, pasted_text=resume_text,
            ats_score=int(ats_score) if ats_score.strip().isdigit() else None,
            shortlist_chance=int(shortlist_chance) if shortlist_chance.strip().isdigit() else None,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Resume profile build failed")
        raise HTTPException(500, f"Could not build resume profile: {str(e)[:200]}")
    return {"profile": resume_profile_service.to_public(doc)}
