"""Mock Interview analysis report — hybrid deterministic + bounded LLM narrative.

`proctoring_integrity` is computed purely deterministically from violation
counts (no LLM involvement, fully auditable). The other four dimensions are
aggregated from the per-question `interview_score_events` the agent logged
live during the session (grounded in real per-question judgments, not a
single cold end-of-interview guess). One final bounded LLM pass produces the
narrative (strengths/weaknesses/verdict) and may nudge the aggregated scores
by at most +/-10 points if its holistic read disagrees — the deterministic
aggregate stays the anchor so the LLM can't invent an ungrounded score.
"""
import os
import re
import json
import logging
from typing import Any, Dict, List, Optional

from fpdf import FPDF

from db import (
    now_iso, users_col,
    interview_sessions_col, interview_turns_col, interview_violations_col,
    interview_score_events_col, interview_reports_col,
)
from services.llm_client import LlmChat, UserMessage
from services import career_service
from services.capability_manifest import with_capability
from services.contest_service import _FONT_CANDIDATES_REGULAR, _FONT_CANDIDATES_BOLD

logger = logging.getLogger(__name__)

DIMENSIONS = ["communication", "technical_correctness", "problem_solving", "confidence"]

TOPIC_WEIGHTS = {
    "dsa":    {"technical_correctness": 0.35, "problem_solving": 0.35, "communication": 0.15, "confidence": 0.10, "proctoring_integrity": 0.05},
    "hld":    {"technical_correctness": 0.30, "problem_solving": 0.35, "communication": 0.20, "confidence": 0.10, "proctoring_integrity": 0.05},
    "lld":    {"technical_correctness": 0.30, "problem_solving": 0.35, "communication": 0.20, "confidence": 0.10, "proctoring_integrity": 0.05},
    "design": {"technical_correctness": 0.25, "problem_solving": 0.30, "communication": 0.25, "confidence": 0.15, "proctoring_integrity": 0.05},
    "hr":     {"technical_correctness": 0.10, "problem_solving": 0.15, "communication": 0.35, "confidence": 0.35, "proctoring_integrity": 0.05},
}

NARRATIVE_SYSTEM_PROMPT = """You are a senior technical interviewer writing a detailed, candid post-interview report for the candidate to actually learn from — the kind of thorough written feedback a real interviewer would give, not a generic summary. You will be given the full transcript, a per-question list of what was already scored live during the interview (with the live interviewer's own notes — ground your feedback in these, don't contradict them), and the computed rubric scores per dimension. Reply with ONLY a strict JSON object, no markdown fences, no prose outside it. Schema:

{
  "strengths": [str] (4-8 bullets — SPECIFIC to what this candidate actually did, e.g. "Correctly identified the O(n) hash-map optimization after starting with brute force" not generic praise like "good communication"),
  "weaknesses": [str] (4-8 bullets — equally specific: name the exact gap, mistake, or missed edge case, not a vague category),
  "verdict": str (a genuine multi-paragraph assessment, 150-300 words — cover overall performance, communication/thought-process clarity, technical depth actually demonstrated, problem-solving approach, and confidence/composure; write it as real prose a candidate would read carefully, not a one-line summary),
  "per_question_feedback": [
    {
      "round": str, "question_index": int,
      "question_summary": str (one line naming/restating the question asked),
      "went_well": str (specific, concrete — what the candidate did right on THIS question; "Nothing notable" if genuinely nothing was),
      "went_wrong": str (specific, concrete — the actual mistake/gap on THIS question; "No significant issues" if genuinely none),
      "how_to_improve": str (one actionable, specific suggestion tied to THIS question — not generic advice)
    }
    ... one entry per distinct question actually covered, using the provided per-question score notes as your source of truth for what happened
  ],
  "score_adjustments": {"communication": int, "technical_correctness": int, "problem_solving": int, "confidence": int}
}

Each value in score_adjustments must be an integer from -10 to 10 — how much to nudge the given score, based on your holistic read of the transcript. Use 0 if you agree with the computed score. If a dimension's computed score is null, the candidate was never genuinely assessed on it — use 0 for that dimension's adjustment (there is nothing to nudge) and do not describe it as weak or absent anywhere in the report; only comment on dimensions and questions that actually have evidence. Do not invent facts, dialogue, or outcomes not supported by the transcript/notes — an honest "nothing notable" beats a fabricated specific."""


def _extract_json(text: str) -> Dict[str, Any]:
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


# A session needs at least this many DISTINCT (round, question) pairs with a
# real record_score call behind them before it gets a confident, numeric
# overall score — below this, a candidate who mostly didn't engage (gave an
# intro and never reached/answered the actual problem, got terminated almost
# immediately, etc.) would otherwise still receive one, because
# _deterministic_scores' missing-dimension handling has to resolve to
# SOMETHING. A real interviewer doesn't average a no-show into "50, i.e.
# average" — they say there isn't enough to judge. See _mark_insufficient_data.
MIN_SCORED_QUESTIONS_FOR_REPORT = 2


async def _distinct_scored_questions(session_id: str) -> int:
    pairs = {
        (e["round"], e["question_index"])
        async for e in interview_score_events_col.find({"session_id": session_id}, {"round": 1, "question_index": 1})
    }
    return len(pairs)


async def _deterministic_scores(session_id: str) -> Dict[str, Optional[float]]:
    """None (not a fabricated neutral 50.0) for any dimension with zero
    record_score events — the caller must decide what to do with a missing
    dimension rather than averaging in a made-up number that looks exactly
    like a real, judged score. See MIN_SCORED_QUESTIONS_FOR_REPORT and the
    renormalized overall-score math in _generate_report_inner."""
    scores: Dict[str, List[int]] = {d: [] for d in DIMENSIONS}
    async for e in interview_score_events_col.find({"session_id": session_id}):
        if e.get("dimension") in scores:
            scores[e["dimension"]].append(e.get("score", 0))
    return {d: (sum(v) / len(v) if v else None) for d, v in scores.items()}


async def _score_events_by_question(session_id: str) -> List[Dict[str, Any]]:
    """Groups every record_score event by (round, question_index) — these
    notes were written LIVE by the interviewer agent during the actual
    conversation (see interview_agent.py's record_score tool), so they're the
    most grounded source of "what really happened on this question" available;
    the narrative pass is told to treat them as ground truth, not to
    reconstruct question boundaries from the raw transcript on its own."""
    by_question: Dict[tuple, Dict[str, Any]] = {}
    async for e in interview_score_events_col.find({"session_id": session_id}).sort("created_at", 1):
        key = (e.get("round"), e.get("question_index"))
        entry = by_question.setdefault(key, {"round": e.get("round"), "question_index": e.get("question_index"), "notes": []})
        entry["notes"].append({"dimension": e.get("dimension"), "score": e.get("score"), "note": e.get("note")})
    return sorted(by_question.values(), key=lambda x: (x["round"] or "", x["question_index"] or 0))


async def _proctoring_integrity(session_id: str) -> float:
    count = await interview_violations_col.count_documents({"session_id": session_id})
    return max(0.0, 100.0 - count * 35.0)


async def _violations_public(session_id: str) -> List[Dict[str, Any]]:
    """Every recorded violation for this session, in a shape the frontend can
    render directly (a human-readable type label lives client-side in
    interviewUtils.VIOLATION_LABEL — this just hands over the raw type/time/
    whether a clip exists). `evidence_clip_key` itself is never exposed
    directly to the client; it's only ever resolved to a short-lived signed
    URL on demand via GET .../violations/{violation_id}/evidence-url, so a
    report payload doesn't leak a durable, un-expiring path into private
    storage."""
    out = []
    async for v in interview_violations_col.find({"session_id": session_id}).sort("created_at", 1):
        out.append({
            "id": str(v["_id"]),
            "type": v.get("type"),
            "reported_at": v.get("reported_at"),
            "has_evidence": bool(v.get("evidence_clip_key")),
        })
    return out


async def _mark_no_data(session: Dict[str, Any], session_id: str,
                        det_scores: Optional[Dict[str, Optional[float]]] = None,
                        scored_question_count: int = 0) -> None:
    """A session that didn't produce enough real evidence to earn a numeric,
    authoritative-looking score. Two distinct ways to land here, told with
    different copy because they're different stories:

    1. Literally zero candidate turns (`det_scores` omitted) — a broken
       mic/camera, a dropped connection, or the candidate leaving immediately.
    2. SOME engagement happened (an intro, maybe the opening of a question)
       but it never reached MIN_SCORED_QUESTIONS_FOR_REPORT distinct scored
       exchanges — most often a proctoring termination or an early end right
       after the opening. `det_scores` carries whatever real per-dimension
       evidence DOES exist (e.g. communication scored once for an intro) so
       it can be shown honestly, labeled as partial, rather than either
       hidden entirely or diluted into a fake full report.

    Recorded distinctly (`status: "no_data"`) rather than as a scored report,
    and explicitly NOT written back into Career Intelligence — there is
    nothing genuine (case 1) or genuinely COMPLETE (case 2) to summarize."""
    violations = await _violations_public(session_id)
    status = session.get("status")
    partial_scores = {d: round(v, 1) for d, v in (det_scores or {}).items() if v is not None}

    if partial_scores:
        no_data_reason = "insufficient_engagement"
        headline = f"## Not enough of the interview happened to score it"
        body = (
            f"Only {scored_question_count} question{'s' if scored_question_count != 1 else ''} got far enough to "
            f"be assessed (at least {MIN_SCORED_QUESTIONS_FOR_REPORT} are needed for a trustworthy overall score), "
            "so no overall score is given — a partial score would look more complete and reliable than the little "
            "that actually happened. Whatever WAS genuinely observed is listed below; everything else is simply "
            "unassessed, not averaged into a number that was never earned."
        )
    elif status == "terminated_violations":
        no_data_reason = "terminated_violations"
        n = len(violations)
        headline = f"## Session ended — {n} proctoring violation{'s' if n != 1 else ''}"
        body = (
            f"This session was automatically ended after {n} confirmed proctoring violation{'s' if n != 1 else ''} "
            "before a single answer was recorded. See the violation list below for exactly what was flagged and when."
        )
    elif status == "abandoned":
        no_data_reason = "abandoned_by_candidate"
        headline = "## Session ended early"
        body = "You ended this session before any content was recorded, so there is nothing to score."
    elif status in ("expired", "terminated_error"):
        no_data_reason = status
        headline = "## Session ended — technical issue"
        body = (
            "This session ended (a dropped connection or a technical error) before any content was recorded, "
            "through no fault of your own."
        )
    else:
        no_data_reason = "unknown"
        headline = "## No analysis available"
        body = (
            "This session ended without a single recorded answer, so there is nothing to score. "
            "This usually means microphone/camera access wasn't granted, the connection dropped, "
            "or the session was left before answering anything."
        )

    partial_lines = "".join(f"- {d.replace('_', ' ').title()}: {v}/100 (partial — see above)\n" for d, v in partial_scores.items())
    doc = {
        "session_id": session_id, "user_id": session["user_id"],
        "dimension_scores": partial_scores, "overall_score": None,
        "strengths": [], "weaknesses": [],
        "per_question_feedback": [],
        "proctoring_summary": {"violation_count": len(violations)},
        "violations": violations,
        "no_data_reason": no_data_reason,
        "report_markdown": (
            f"{headline}\n\n{body}\n\n{partial_lines}\n"
            "This attempt was not evaluated — start a new session when you're ready."
        ),
        "status": "no_data", "generated_at": now_iso(),
    }
    await interview_reports_col.update_one({"session_id": session_id}, {"$set": doc}, upsert=True)
    report = await interview_reports_col.find_one({"session_id": session_id})
    await interview_sessions_col.update_one({"_id": session_id}, {"$set": {"final_report_id": str(report["_id"])}})


async def generate_report(session_id: str) -> None:
    """Fire-and-forget entry point — called via asyncio.create_task from
    interview_service/proctoring_service on session completion/termination."""
    try:
        await _generate_report_inner(session_id)
    except Exception:
        logger.exception(f"interview_report_service: report generation failed for session {session_id}")
        await interview_reports_col.update_one(
            {"session_id": session_id}, {"$set": {"status": "failed", "generated_at": now_iso()}}, upsert=True,
        )


async def _generate_report_inner(session_id: str) -> None:
    session = await interview_sessions_col.find_one({"_id": session_id})
    if not session:
        return
    existing = await interview_reports_col.find_one({"session_id": session_id})
    if existing and existing.get("status") == "ready":
        return  # idempotent — don't regenerate on a duplicate completion/termination trigger

    turns = [t async for t in interview_turns_col.find({"session_id": session_id}).sort("turn_index", 1)]
    candidate_turns = [t for t in turns if t["speaker"] == "candidate"]

    if not candidate_turns:
        # Zero real interaction happened — never emit a numeric,
        # authoritative-looking score for a session nothing was actually
        # evaluated in. Without this guard, every dimension silently falls
        # back to a fabricated default and the narrative pass gets skipped
        # for an empty transcript, producing a normal-looking ~48/100 report
        # with "No verdict/strengths/gaps recorded" for a session where the
        # candidate never said or typed a single word — indistinguishable
        # from a real, if weak, evaluation. That's a bug in judgment, not
        # just numbers.
        await _mark_no_data(session, session_id)
        return

    det_scores = await _deterministic_scores(session_id)
    scored_question_count = await _distinct_scored_questions(session_id)

    if scored_question_count < MIN_SCORED_QUESTIONS_FOR_REPORT:
        # SOME engagement happened (candidate_turns is non-empty — e.g. an
        # intro, or the start of an answer) but not enough of the actual
        # interview to trust a full numeric score. Without this, every
        # dimension the candidate never really got to would fall back to
        # _deterministic_scores' old 50.0-default behavior and blend into a
        # normal-looking overall score — e.g. a candidate who gave only their
        # introduction before the session ended landed 51.7/100, which reads
        # as "roughly average" for someone who never touched the actual
        # problem. Whatever real signal DOES exist (det_scores' non-None
        # entries) is preserved and shown honestly — see _mark_no_data.
        await _mark_no_data(session, session_id, det_scores, scored_question_count)
        return

    proctoring_integrity = await _proctoring_integrity(session_id)
    transcript = "\n\n".join(f"{t['speaker'].upper()}: {t['text']}" for t in turns)[:24000]

    narrative: Dict[str, Any] = {"strengths": [], "weaknesses": [], "verdict": "", "per_question_feedback": [], "score_adjustments": {}}
    if transcript.strip():
        try:
            per_question_notes = await _score_events_by_question(session_id)
            chat = LlmChat(system_message=with_capability(NARRATIVE_SYSTEM_PROMPT)).with_model(
                "anthropic", "claude-sonnet-5", max_tokens=4000,
            )
            prompt = (
                f"TOPIC: {session.get('topic')}\n"
                f"COMPUTED SCORES (null = not enough evidence to score that dimension at all — "
                f"do not invent an adjustment for it, leave it at 0): {json.dumps(det_scores)}\n\n"
                f"LIVE PER-QUESTION NOTES (written during the interview itself — ground your per_question_feedback "
                f"in these, one entry per item here): {json.dumps(per_question_notes)}\n\n"
                f"TRANSCRIPT:\n{transcript}"
            )
            resp = await chat.send_message(UserMessage(text=prompt))
            content = resp if isinstance(resp, str) else getattr(resp, "content", str(resp))
            narrative = _extract_json(content)
        except Exception:
            logger.warning(f"interview_report_service: narrative pass failed for {session_id}, using deterministic scores only")

    final_scores: Dict[str, Optional[float]] = dict(det_scores)
    adjustments = narrative.get("score_adjustments") or {}
    for d in DIMENSIONS:
        if final_scores[d] is None:
            continue  # no evidence for this dimension at all — leave it unscored, don't nudge a number into existence
        try:
            adj = max(-10, min(10, int(adjustments.get(d, 0))))
        except Exception:
            adj = 0
        final_scores[d] = max(0.0, min(100.0, final_scores[d] + adj))
    final_scores["proctoring_integrity"] = proctoring_integrity

    # Weighted average over only the dimensions with real evidence,
    # renormalized so the remaining weights still sum to 1 — a dimension the
    # candidate never got to isn't "50, i.e. average," it's simply excluded
    # from the overall score rather than silently dragging it toward the
    # middle. (With scored_question_count >= MIN_SCORED_QUESTIONS_FOR_REPORT,
    # at least SOME real dimensions always exist here.)
    weights = TOPIC_WEIGHTS.get(session.get("topic"), TOPIC_WEIGHTS["dsa"])
    scored_weight_total = sum(w for d, w in weights.items() if final_scores.get(d) is not None)
    overall = sum(final_scores[d] * w for d, w in weights.items() if final_scores.get(d) is not None) / scored_weight_total
    unscored_dimensions = [d for d in DIMENSIONS if final_scores[d] is None]

    report_markdown = _render_markdown(session, final_scores, overall, narrative, unscored_dimensions)
    violations = await _violations_public(session_id)

    doc = {
        "session_id": session_id, "user_id": session["user_id"],
        "dimension_scores": {d: round(final_scores[d], 1) for d in DIMENSIONS + ["proctoring_integrity"] if final_scores[d] is not None},
        "unscored_dimensions": unscored_dimensions,
        "overall_score": round(overall, 1),
        "strengths": narrative.get("strengths") or [],
        "weaknesses": narrative.get("weaknesses") or [],
        "verdict": narrative.get("verdict") or "",
        "per_question_feedback": narrative.get("per_question_feedback") or [],
        "proctoring_summary": {"violation_count": len(violations)},
        "violations": violations,
        "report_markdown": report_markdown,
        "status": "ready", "generated_at": now_iso(),
    }
    await interview_reports_col.update_one({"session_id": session_id}, {"$set": doc}, upsert=True)
    report = await interview_reports_col.find_one({"session_id": session_id})
    await interview_sessions_col.update_one({"_id": session_id}, {"$set": {"final_report_id": str(report["_id"])}})

    # Actual duration, not a fixed assumption — technical_minutes/behavioral_minutes
    # are candidate-adjustable per session (see interview_service.create_session).
    actual_total_minutes = int(session.get("technical_minutes", 45)) + int(session.get("behavioral_minutes", 0))
    summary = (
        f"Completed a {actual_total_minutes} min mock interview ({str(session.get('topic', '')).upper()} focus): "
        f"scored {round(overall)}/100 overall — "
        + ", ".join(f"{d.replace('_', ' ')} {round(final_scores[d])}" for d in DIMENSIONS if final_scores[d] is not None)
        + (f". Gap: {narrative['weaknesses'][0]}" if narrative.get("weaknesses") else "")
        + (f". Strength: {narrative['strengths'][0]}" if narrative.get("strengths") else "")
    )
    try:
        await career_service.append_interview_summary(session["user_id"], summary)
    except Exception:
        logger.exception(f"interview_report_service: career profile write-path failed for {session_id}")


def _render_markdown(session: Dict[str, Any], scores: Dict[str, Optional[float]], overall: float,
                     narrative: Dict[str, Any], unscored_dimensions: Optional[List[str]] = None) -> str:
    lines = [
        f"## Overall Score: {round(overall)}/100",
        f"**Topic:** {str(session.get('topic', '')).upper()}  |  **Seniority:** {session.get('seniority', 'mid')}",
        "",
        "### Dimension Scores",
    ]
    for d, v in scores.items():
        if v is None:
            continue
        lines.append(f"- {d.replace('_', ' ').title()}: {round(v)}/100")
    for d in unscored_dimensions or []:
        lines.append(f"- {d.replace('_', ' ').title()}: Not assessed (no questions reached this dimension)")
    lines += ["", "### Verdict", narrative.get("verdict") or "No verdict generated.", "", "### Strengths"]
    for s in narrative.get("strengths") or []:
        lines.append(f"- {s}")
    lines += ["", "### Areas to Improve"]
    for w in narrative.get("weaknesses") or []:
        lines.append(f"- {w}")
    per_question = narrative.get("per_question_feedback") or []
    if per_question:
        lines += ["", "### Question-by-Question Breakdown"]
        for i, q in enumerate(per_question, 1):
            lines += [
                "",
                f"**{i}. {q.get('question_summary', 'Question')}** _{(q.get('round') or '').title()} round_",
                f"- What went well: {q.get('went_well', 'n/a')}",
                f"- What went wrong: {q.get('went_wrong', 'n/a')}",
                f"- How to improve: {q.get('how_to_improve', 'n/a')}",
            ]
    return "\n".join(lines)


async def get_report(session_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    return await interview_reports_col.find_one({"session_id": session_id, "user_id": user_id})


def _first_existing(paths: List[str]) -> Optional[str]:
    return next((p for p in paths if os.path.exists(p)), None)


def _register_body_font(pdf: FPDF) -> str:
    """Registers a real Unicode TTF font (same system-font candidates
    contest_service.py's PNG stats card already uses) on `pdf` and returns
    its family name. Without this, fpdf2's core "Helvetica" font —
    Latin-1/WinAnsi only — hard-crashes the instant any text contains an
    em-dash, curly quote, ellipsis, etc., which LLM-generated narrative text
    (and even this app's own hand-written copy) uses routinely. Falls back
    to "Helvetica" only if no system TTF exists at all, which reintroduces
    that same crash risk but is an extreme/unlikely environment to hit.
    Must be called BEFORE the first add_page() on a _ReportPDF — its
    header() fires immediately on add_page() and needs the font already
    registered."""
    regular = _first_existing(_FONT_CANDIDATES_REGULAR)
    bold = _first_existing(_FONT_CANDIDATES_BOLD) or regular
    if not regular:
        logger.warning("interview_report_service: no system Unicode TTF found — falling back to Helvetica (non-Unicode)")
        return "Helvetica"
    pdf.add_font("ReportBody", "", regular)
    pdf.add_font("ReportBody", "B", bold)
    return "ReportBody"


PLATFORM_NAME = "supercreater.ai"

# A small, consistent palette (RGB) rather than default-black-on-white —
# roughly matches the web report's primary/muted/border tokens so the PDF
# reads as the same product, not a generic fpdf2 default.
_ACCENT = (79, 70, 229)      # indigo — headings, score bars, the wordmark's accent dot
_INK = (15, 23, 42)          # primary body text
_MUTED = (100, 116, 139)     # secondary/meta text
_LIGHT = (226, 232, 240)     # rules, unfilled bar track
_GOOD = (16, 150, 72)        # strengths
_WARN = (180, 83, 9)         # weaknesses/areas to improve


class _ReportPDF(FPDF):
    """A tiny FPDF subclass purely so header()/footer() — which fpdf2 calls
    automatically on every add_page()/page-break — can stamp the platform
    name and page number on EVERY page, not just the first. `font_family`
    must already be registered (see _register_body_font) before the first
    add_page() call, since header() fires immediately on that call."""
    def __init__(self, font_family: str, subtitle: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.font_family = font_family
        self.subtitle = subtitle
        self.set_auto_page_break(True, margin=22)

    def header(self):
        self.set_y(10)
        self.set_font(self.font_family, "B", 13)
        self.set_text_color(*_INK)
        word_w = self.get_string_width("supercreater")
        self.cell(word_w, 7, "supercreater", border=0)
        self.set_text_color(*_ACCENT)
        dot_w = self.get_string_width(".")
        self.cell(dot_w, 7, ".", border=0)
        self.set_text_color(*_INK)
        self.cell(self.get_string_width("ai") + 2, 7, "ai", border=0)
        self.set_font(self.font_family, "", 9)
        self.set_text_color(*_MUTED)
        self.set_xy(-self.r_margin - 70, 10)
        self.cell(70, 7, self.subtitle, align="R")
        self.set_draw_color(*_LIGHT)
        self.set_line_width(0.3)
        self.line(self.l_margin, 19, self.w - self.r_margin, 19)
        self.set_y(25)

    def footer(self):
        self.set_y(-15)
        self.set_font(self.font_family, "", 8)
        self.set_text_color(*_MUTED)
        self.cell(0, 10, f"{PLATFORM_NAME} Mock Interview Report — Page {self.page_no()}", align="C")


def generate_report_pdf(session: Dict[str, Any], report: Dict[str, Any], user_name: str) -> bytes:
    """A detailed, branded multi-section report: candidate/session summary,
    a prominent overall score, a horizontal bar per dimension, the LLM's
    verdict as real prose (not just bullet fragments), strengths/areas to
    improve, and the proctoring/violation record if anything was flagged."""
    from services.interview_service import get_interviewer_public  # local import avoids a circular top-level import

    topic_label = str(session.get("topic", "")).upper()
    subtitle = f"{topic_label} · {session.get('seniority', 'mid').title()}"
    # Family name is deterministic from what's actually on disk (see
    # _register_body_font) — safe to compute before the real pdf object
    # exists, which _ReportPDF's constructor needs for header()/footer().
    font = "Helvetica" if not _first_existing(_FONT_CANDIDATES_REGULAR) else "ReportBody"
    pdf = _ReportPDF(font, subtitle)
    _register_body_font(pdf)
    pdf.add_page()
    W = pdf.w
    margin = pdf.l_margin
    content_w = W - 2 * margin

    def _text(text: str, size: int, bold: bool = False, color=_INK, line_h_mult: float = 0.62):
        pdf.set_x(margin)
        pdf.set_font(font, "B" if bold else "", size)
        pdf.set_text_color(*color)
        pdf.multi_cell(content_w, size * line_h_mult, text)

    def _rule(gap_before: float = 3, gap_after: float = 3):
        pdf.ln(gap_before)
        pdf.set_draw_color(*_LIGHT)
        pdf.set_line_width(0.25)
        pdf.line(margin, pdf.get_y(), W - margin, pdf.get_y())
        pdf.ln(gap_after)

    def _score_bar(label: str, score: float):
        y = pdf.get_y()
        label_w = 52
        score_w = 16
        bar_x = margin + label_w
        bar_w = content_w - label_w - score_w
        pdf.set_xy(margin, y)
        pdf.set_font(font, "", 10.5)
        pdf.set_text_color(*_INK)
        pdf.cell(label_w, 6, label)
        pdf.set_fill_color(*_LIGHT)
        pdf.rect(bar_x, y + 1, bar_w, 4, style="F")
        filled = bar_w * max(0.0, min(100.0, score)) / 100.0
        pdf.set_fill_color(*_ACCENT)
        if filled > 0:
            pdf.rect(bar_x, y + 1, filled, 4, style="F")
        pdf.set_xy(bar_x + bar_w + 2, y)
        pdf.set_font(font, "B", 10.5)
        pdf.set_text_color(*_INK)
        pdf.cell(score_w, 6, f"{round(score)}", align="R")
        pdf.set_y(y + 7.5)

    # ---- Header block: candidate + session metadata ----
    _text("Mock Interview Report", 22, bold=True, color=_INK)
    pdf.ln(1)
    created_at = str(session.get("created_at", ""))[:10]
    interviewer = get_interviewer_public(session.get("interviewer_id")) or {}
    total_minutes = int(session.get("technical_minutes", 0) or 0) + int(session.get("behavioral_minutes", 0) or 0)
    meta_lines = [f"Candidate: {user_name}"]
    if created_at:
        meta_lines.append(f"Date: {created_at}")
    if total_minutes:
        meta_lines.append(f"Duration: {total_minutes} min")
    if interviewer.get("name"):
        meta_lines.append(f"Interviewer: {interviewer['name']}")
    if session.get("language"):
        meta_lines.append(f"Language: {str(session['language']).title()}")
    _text("  ·  ".join(meta_lines), 10.5, color=_MUTED)
    _rule(gap_before=4, gap_after=2)

    # ---- Overall score ----
    _text("Overall Score", 11, bold=True, color=_MUTED)
    pdf.set_x(margin)
    pdf.set_font(font, "B", 30)
    pdf.set_text_color(*_ACCENT)
    pdf.cell(40, 14, f"{report['overall_score']}", border=0)
    pdf.set_font(font, "", 13)
    pdf.set_text_color(*_MUTED)
    pdf.cell(20, 14, "/ 100", border=0)
    pdf.ln(14)
    _rule(gap_before=1, gap_after=3)

    # ---- Dimension breakdown ----
    _text("Dimension Breakdown", 13, bold=True)
    pdf.ln(2)
    for d, v in report["dimension_scores"].items():
        _score_bar(d.replace("_", " ").title(), v)
    _rule()

    # ---- Verdict (full narrative prose, not fragments) ----
    verdict = report.get("verdict")
    if verdict:
        _text("Verdict", 13, bold=True)
        pdf.ln(1)
        _text(verdict, 11, color=_INK, line_h_mult=0.68)
        _rule()

    # ---- Strengths / Areas to improve ----
    _text("Strengths", 13, bold=True, color=_GOOD)
    pdf.ln(1)
    strengths = report.get("strengths") or []
    _text("\n".join(f"+  {s}" for s in strengths) if strengths else "No strengths recorded.", 11, line_h_mult=0.68)
    pdf.ln(3)
    _text("Areas to Improve", 13, bold=True, color=_WARN)
    pdf.ln(1)
    weaknesses = report.get("weaknesses") or []
    _text("\n".join(f"–  {w}" for w in weaknesses) if weaknesses else "No gaps recorded.", 11, line_h_mult=0.68)

    # ---- Question-by-question breakdown ----
    per_question = report.get("per_question_feedback") or []
    if per_question:
        _rule()
        _text("Question-by-Question Breakdown", 13, bold=True)
        pdf.ln(2)
        for i, q in enumerate(per_question, 1):
            _text(f"{i}. {q.get('question_summary', 'Question')}", 11.5, bold=True)
            _text(f"Went well: {q.get('went_well', 'n/a')}", 10.5, color=_GOOD, line_h_mult=0.62)
            _text(f"Went wrong: {q.get('went_wrong', 'n/a')}", 10.5, color=_WARN, line_h_mult=0.62)
            _text(f"How to improve: {q.get('how_to_improve', 'n/a')}", 10.5, color=_MUTED, line_h_mult=0.62)
            pdf.ln(2)

    # ---- Proctoring record ----
    violations = report.get("violations") or []
    if violations:
        _rule()
        _text(f"Proctoring Record — {len(violations)} violation{'s' if len(violations) != 1 else ''}", 13, bold=True, color=_WARN)
        pdf.ln(1)
        for v in violations:
            when = (v.get("reported_at") or "")[:19].replace("T", " ")
            label = str(v.get("type") or "unknown").replace("_", " ").title()
            clip_note = "" if v.get("has_evidence") else "  (no evidence clip captured)"
            _text(f"•  {label} — {when}{clip_note}", 10.5, color=_MUTED, line_h_mult=0.6)

    return bytes(pdf.output())
