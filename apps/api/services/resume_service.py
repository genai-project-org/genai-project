"""Resume Intelligence — ATS scoring, keyword match, rewritten bullets.

Every call:
 1. Extract plain text from the upload (PDF / DOCX / TXT) or take pasted text
 2. Data-lake first (semantic retrieval, scoped per-user)
 3. Fall through to the LLM with a recruiter system prompt
 4. Store the fresh response back to the KB
"""
import io
import os
import re
import html
import logging
import zipfile
from typing import Optional
from fastapi import HTTPException, status
from pypdf import PdfReader
from services.llm_client import LlmChat, UserMessage
from services.knowledge_retriever import retrieve, store as kb_store
from services.settings_service import get_setting
from services.capability_manifest import with_capability
from services.provider_selector import pick_provider

logger = logging.getLogger(__name__)

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")

# Input caps. Truncated in code, never via Form(max_length=) — a 422 detail is a *list*,
# and api.js only unwraps dict details, so the user would just see "Request failed".
MAX_CHARS = 20000          # ~5 resume pages
MAX_JD_CHARS = 8000
MAX_ROLE_CHARS = 120
# A full report with rewritten bullets overruns the 4096 LLM_MAX_TOKENS default, and
# send_message never inspects stop_reason — truncation would be silent.
REPORT_MAX_TOKENS = int(os.environ.get("RESUME_MAX_TOKENS", "8000"))
# Below this, there is no resume to analyze (also catches scanned/image-only PDFs).
MIN_RESUME_CHARS = 200

SYSTEM_PROMPT = """You are a senior technical recruiter and ATS specialist. Your reply is ONE markdown report and nothing else. No preamble, no sign-off, and do not recommend any IEMA feature — the user is already inside Resume Intelligence.

The VERY FIRST TWO lines must be exactly these, in this order, with no heading above them:
**ATS Score: NN/100**
**Shortlist Chance: NN%**
where each NN is an integer 0-100. Never omit either line, never write a number in words, never give a range, never add a band or label inside those two lines. ATS Score rates machine-parseability and keyword coverage; Shortlist Chance is your honest estimate that a human recruiter screening for this role calls this candidate back. Then continue with:

## Verdict (2 sentences)
## Shortlist Outlook (why that chance — name the 2-3 factors moving it most, and what single change would raise it fastest)
## Keyword Match vs the Job Description (matched / missing, as bullets)
## Fix These First (max 5, each: problem -> rewritten line)
## Rewritten Bullets (3-5, quantified)
## Formatting & ATS Parsing Issues

Keep the whole report under 900 words. If no job description was given, score against general ATS best practice for the target role and say so in the Verdict."""


def extract_text(filename: str, data: bytes) -> str:
    """Plain text out of a resume upload. Raises 400 with an actionable message on failure.

    Dispatches on extension, not content_type: browsers send application/octet-stream for
    .docx often enough, and application/msword for both .doc and some .docx.
    """
    name = (filename or "").lower()
    try:
        if name.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(data))
            # An owner-password-only PDF decrypts with the empty string; a real user
            # password returns 0 and there is nothing we can do with it.
            if reader.is_encrypted and reader.decrypt("") == 0:
                raise HTTPException(400, "This PDF is password-protected. Remove the password and re-upload.")
            text = "\n".join(p.extract_text() or "" for p in reader.pages)
        elif name.endswith(".docx"):
            # ponytail: a .docx is a zip of XML — same tag-strip idiom as studio_routes.py:63.
            # Loses table cell boundaries but keeps every word. Add python-docx if layout matters.
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                xml = z.read("word/document.xml").decode("utf-8", "ignore")
            text = html.unescape(re.sub(r"<[^>]+>", "", xml.replace("</w:p>", "\n")))
        elif name.endswith((".txt", ".md")):
            text = data.decode("utf-8", "ignore")
        elif name.endswith(".doc"):
            raise HTTPException(400, "Old .doc files aren't supported. Open it in Word and 'Save As' → .docx, or paste the text.")
        else:
            raise HTTPException(400, "Unsupported file. Upload a PDF, DOCX or TXT.")
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"resume extract failed ({name}): {e}")
        raise HTTPException(400, "Could not read that file — it may be corrupt. Try a different export, or paste the text.")
    if len(re.sub(r"\s+", "", text)) < MIN_RESUME_CHARS:
        raise HTTPException(400, "No selectable text found — this looks like a scanned or image-only PDF. Paste your resume text instead.")
    return text[:MAX_CHARS]


# Search the whole report, not just line 1: the capability manifest sometimes makes the
# model open with a feature plug before the score lines.
_ATS_RE = re.compile(r"ATS\s*Score\D{0,8}?(\d{1,3})\s*/\s*100", re.I)
_SHORTLIST_RE = re.compile(r"Shortlist\s*Chance\D{0,8}?(\d{1,3})\s*%", re.I)


def _metric(rx: re.Pattern, text: str) -> Optional[int]:
    """Pull a 0-100 integer metric out of the report, or None if the model didn't emit one."""
    m = rx.search(text or "")
    if not m:
        return None
    n = int(m.group(1))
    return n if 0 <= n <= 100 else None


def _scores(text: str) -> dict:
    return {"ats_score": _metric(_ATS_RE, text), "shortlist_chance": _metric(_SHORTLIST_RE, text)}


async def analyze(
    resume_text: str,
    job_description: str = "",
    target_role: str = "",
    user_id: Optional[str] = None,
    gate=None,
) -> dict:
    """Return {response, ats_score, shortlist_chance, source, score, match, provider}.

    `gate` (if given) is awaited right before the expensive LLM call, so cached hits
    stay free of the usage window. Assumes `resume_text` is length-validated by the router.
    """
    resume_text = (resume_text or "").strip()[:MAX_CHARS]
    job_description = (job_description or "").strip()[:MAX_JD_CHARS]
    target_role = (target_role or "").strip()[:MAX_ROLE_CHARS]

    # Per-user KB namespace. retrieve() filters on `kind` only — it accepts user_id and
    # never uses it — and store() truncates prompt_norm to 4000 chars. Two resumes off the
    # same college template could clear the Jaccard threshold and serve someone else's
    # report, so the user goes in the kind. Same precedent as builder_service._kb_kind.
    # v2 namespace: v1 reports predate the Shortlist Chance line, and an exact-hash hit on
    # one would silently serve a report with the metric missing forever.
    kind = f"resume_analyze:v2:{user_id or 'anon'}"
    kb_key = f"role={target_role.lower()}\njd={job_description}\ncv={resume_text}"

    if await get_setting("kb_enabled", True):
        hit = await retrieve(kind, kb_key, user_id=user_id)
        if hit:
            return {
                "response": hit["response"],
                **_scores(hit["response"]),
                "source": "kb",
                "match": hit["match"],
                "score": hit["score"],
            }

    if await get_setting("kb_only_mode", False):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Knowledge-only mode is on and no cached analysis was found.")

    if gate:
        await gate()

    parts = [f"TARGET ROLE: {target_role}"] if target_role else []
    parts.append(f"RESUME:\n{resume_text}")
    if job_description:
        parts.append(f"JOB DESCRIPTION:\n{job_description}")

    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"resume-{(user_id or 'anon')[:12]}",
        system_message=with_capability(SYSTEM_PROMPT),
    )
    provider, model = await pick_provider(user_id)
    chat = chat.with_model(provider, model, max_tokens=REPORT_MAX_TOKENS)
    resp = await chat.send_message(UserMessage(text="\n\n".join(parts)))
    content = resp if isinstance(resp, str) else getattr(resp, "content", str(resp))
    await kb_store(kind, kb_key, content, user_id=user_id,
                   meta={"provider": provider, "has_jd": bool(job_description), "role": target_role})
    return {"response": content, **_scores(content), "source": "llm", "provider": provider}


def _docx_bytes(*paragraphs: str) -> bytes:
    """Minimal in-memory .docx for the self-check below."""
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f"<w:document><w:body>{body}</w:body></w:document>")
    return buf.getvalue()


def demo() -> None:
    """Offline self-check: python -m services.resume_service"""
    filler = "Senior Python engineer. " * 20  # clears MIN_RESUME_CHARS

    # -- score extraction --
    ats = lambda t: _metric(_ATS_RE, t)
    assert ats("**ATS Score:** 91/100\n## Verdict") == 91
    assert ats("| ATS Score | 55/100 |") == 55
    assert ats("ATS Score — 7/100") == 7
    assert ats("**Career Intelligence** shows live jobs.\n\n**ATS Score: 62/100**") == 62
    assert ats("ATS Score: 250/100") is None, "out-of-range must not be trusted"
    assert ats("roughly 70 out of 100") is None, "prose is not a score"
    assert ats("") is None

    # -- both metrics off one real report head, and they must not cross-read --
    head = "**ATS Score: 82/100**\n**Shortlist Chance: 34%**\n\n## Verdict"
    assert _scores(head) == {"ats_score": 82, "shortlist_chance": 34}, _scores(head)
    assert _scores("**Shortlist Chance:** 5%") == {"ats_score": None, "shortlist_chance": 5}
    assert _scores("**ATS Score: 82/100**")["shortlist_chance"] is None
    # a v1 cached report has no shortlist line — must degrade to None, not to the ATS number
    assert _scores("**ATS Score: 70/100**\nShortlist odds look decent.")["shortlist_chance"] is None
    assert _scores("Shortlist Chance: 140%")["shortlist_chance"] is None

    # -- docx via stdlib zip --
    out = extract_text("cv.docx", _docx_bytes("Rahul Pal &amp; Co", filler))
    assert "Rahul Pal & Co" in out, out[:80]          # entities unescaped
    assert out.startswith("Rahul Pal & Co\n"), repr(out[:40])  # paragraph break kept

    # -- rejections, each with an actionable message --
    for fname, blob, needle in [
        ("cv.doc", b"\xd0\xcf" + b"x" * 400, ".docx"),
        ("cv.pdf", b"not a pdf at all" * 40, "corrupt"),
        ("cv.png", b"\x89PNG" + b"x" * 400, "Unsupported file"),
        ("cv.txt", b"too short", "scanned"),
    ]:
        try:
            extract_text(fname, blob)
            raise AssertionError(f"{fname} should have been rejected")
        except HTTPException as e:
            assert e.status_code == 400, (fname, e.status_code)
            assert needle.lower() in str(e.detail).lower(), (fname, e.detail)

    # -- truncation --
    assert len(extract_text("big.txt", ("x" * 30000).encode())) == MAX_CHARS

    print("resume_service demo OK")


if __name__ == "__main__":
    demo()
