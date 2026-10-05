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

logger = logging.getLogger(__name__)

DIMENSIONS = ["communication", "technical_correctness", "problem_solving", "confidence"]

TOPIC_WEIGHTS = {
    "dsa":    {"technical_correctness": 0.35, "problem_solving": 0.35, "communication": 0.15, "confidence": 0.10, "proctoring_integrity": 0.05},
    "hld":    {"technical_correctness": 0.30, "problem_solving": 0.35, "communication": 0.20, "confidence": 0.10, "proctoring_integrity": 0.05},
    "lld":    {"technical_correctness": 0.30, "problem_solving": 0.35, "communication": 0.20, "confidence": 0.10, "proctoring_integrity": 0.05},
    "design": {"technical_correctness": 0.25, "problem_solving": 0.30, "communication": 0.25, "confidence": 0.15, "proctoring_integrity": 0.05},
    "hr":     {"technical_correctness": 0.10, "problem_solving": 0.15, "communication": 0.35, "confidence": 0.35, "proctoring_integrity": 0.05},
}

NARRATIVE_SYSTEM_PROMPT = """You are a senior technical interviewer writing a candid post-interview report. You will be given a full interview transcript and a set of already-computed rubric scores (0-100) per dimension. Reply with ONLY a strict JSON object, no markdown fences, no prose. Schema:
{"strengths": [str] (3-5 bullets), "weaknesses": [str] (3-5 bullets), "verdict": str (2-3 sentences, an honest hire-signal style read), "score_adjustments": {"communication": int, "technical_correctness": int, "problem_solving": int, "confidence": int}}
Each value in score_adjustments must be an integer from -10 to 10 — how much to nudge the given score, based on your holistic read of the transcript. Use 0 if you agree with the computed score. Do not invent facts not supported by the transcript."""


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


async def _deterministic_scores(session_id: str) -> Dict[str, float]:
    scores: Dict[str, List[int]] = {d: [] for d in DIMENSIONS}
    async for e in interview_score_events_col.find({"session_id": session_id}):
        if e.get("dimension") in scores:
            scores[e["dimension"]].append(e.get("score", 0))
    return {d: (sum(v) / len(v) if v else 50.0) for d, v in scores.items()}


async def _proctoring_integrity(session_id: str) -> float:
    count = await interview_violations_col.count_documents({"session_id": session_id})
    return max(0.0, 100.0 - count * 35.0)


async def _mark_no_data(session: Dict[str, Any], session_id: str) -> None:
    """A session that ended (completed/terminated/expired) with literally zero
    candidate turns — most often a broken mic/camera, a connectivity issue, or
    the candidate leaving immediately. Recorded distinctly (`status: "no_data"`)
    rather than as a scored report, and explicitly NOT written back into
    Career Intelligence — there is nothing genuine to summarize."""
    violation_count = await interview_violations_col.count_documents({"session_id": session_id})
    doc = {
        "session_id": session_id, "user_id": session["user_id"],
        "dimension_scores": {}, "overall_score": None,
        "strengths": [], "weaknesses": [],
        "per_question_feedback": [],
        "proctoring_summary": {"violation_count": violation_count},
        "report_markdown": (
            "## No analysis available\n\n"
            "This session ended without a single recorded answer, so there is nothing to score. "
            "This usually means microphone/camera access wasn't granted, the connection dropped, "
            "or the session was left before answering anything.\n\n"
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
        # back to _deterministic_scores' 50.0 default (no score_events to
        # average) and the narrative pass gets skipped for an empty
        # transcript, producing a normal-looking ~48/100 report with "No
        # verdict/strengths/gaps recorded" for a session where the candidate
        # never said or typed a single word — indistinguishable from a real,
        # if weak, evaluation. That's a bug in judgment, not just numbers.
        await _mark_no_data(session, session_id)
        return

    det_scores = await _deterministic_scores(session_id)
    proctoring_integrity = await _proctoring_integrity(session_id)
    transcript = "\n\n".join(f"{t['speaker'].upper()}: {t['text']}" for t in turns)[:24000]

    narrative: Dict[str, Any] = {"strengths": [], "weaknesses": [], "verdict": "", "score_adjustments": {}}
    if transcript.strip():
        try:
            chat = LlmChat(system_message=with_capability(NARRATIVE_SYSTEM_PROMPT)).with_model(
                "anthropic", "claude-sonnet-5", max_tokens=2000,
            )
            prompt = f"TOPIC: {session.get('topic')}\nCOMPUTED SCORES: {json.dumps(det_scores)}\n\nTRANSCRIPT:\n{transcript}"
            resp = await chat.send_message(UserMessage(text=prompt))
            content = resp if isinstance(resp, str) else getattr(resp, "content", str(resp))
            narrative = _extract_json(content)
        except Exception:
            logger.warning(f"interview_report_service: narrative pass failed for {session_id}, using deterministic scores only")

    final_scores = dict(det_scores)
    adjustments = narrative.get("score_adjustments") or {}
    for d in DIMENSIONS:
        try:
            adj = max(-10, min(10, int(adjustments.get(d, 0))))
        except Exception:
            adj = 0
        final_scores[d] = max(0.0, min(100.0, final_scores[d] + adj))
    final_scores["proctoring_integrity"] = proctoring_integrity

    weights = TOPIC_WEIGHTS.get(session.get("topic"), TOPIC_WEIGHTS["dsa"])
    overall = sum(final_scores[d] * w for d, w in weights.items())

    report_markdown = _render_markdown(session, final_scores, overall, narrative)
    violation_count = await interview_violations_col.count_documents({"session_id": session_id})

    doc = {
        "session_id": session_id, "user_id": session["user_id"],
        "dimension_scores": {d: round(final_scores[d], 1) for d in DIMENSIONS + ["proctoring_integrity"]},
        "overall_score": round(overall, 1),
        "strengths": narrative.get("strengths") or [],
        "weaknesses": narrative.get("weaknesses") or [],
        "per_question_feedback": [],
        "proctoring_summary": {"violation_count": violation_count},
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
        + ", ".join(f"{d.replace('_', ' ')} {round(final_scores[d])}" for d in DIMENSIONS)
        + (f". Gap: {narrative['weaknesses'][0]}" if narrative.get("weaknesses") else "")
        + (f". Strength: {narrative['strengths'][0]}" if narrative.get("strengths") else "")
    )
    try:
        await career_service.append_interview_summary(session["user_id"], summary)
    except Exception:
        logger.exception(f"interview_report_service: career profile write-path failed for {session_id}")


def _render_markdown(session: Dict[str, Any], scores: Dict[str, float], overall: float, narrative: Dict[str, Any]) -> str:
    lines = [
        f"## Overall Score: {round(overall)}/100",
        f"**Topic:** {str(session.get('topic', '')).upper()}  |  **Seniority:** {session.get('seniority', 'mid')}",
        "",
        "### Dimension Scores",
    ]
    for d, v in scores.items():
        lines.append(f"- {d.replace('_', ' ').title()}: {round(v)}/100")
    lines += ["", "### Verdict", narrative.get("verdict") or "No verdict generated.", "", "### Strengths"]
    for s in narrative.get("strengths") or []:
        lines.append(f"- {s}")
    lines += ["", "### Areas to Improve"]
    for w in narrative.get("weaknesses") or []:
        lines.append(f"- {w}")
    return "\n".join(lines)


async def get_report(session_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    return await interview_reports_col.find_one({"session_id": session_id, "user_id": user_id})


def generate_report_pdf(session: Dict[str, Any], report: Dict[str, Any], user_name: str) -> bytes:
    """Modeled directly on contest_service.generate_certificate_pdf()'s fpdf2 layout
    conventions — a real, text-based PDF, not a rasterized image."""
    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    W = pdf.w
    margin = pdf.l_margin

    def _text(y: float, text: str, size: int, bold: bool = False, color=(15, 23, 42)):
        pdf.set_xy(margin, y)
        pdf.set_font("Helvetica", "B" if bold else "", size)
        pdf.set_text_color(*color)
        pdf.multi_cell(W - 2 * margin, size * 0.6, text)

    pdf.set_y(20)
    _text(pdf.get_y(), "Mock Interview Report", 24, bold=True)
    pdf.ln(2)
    _text(pdf.get_y(), f"{user_name}  —  {str(session.get('topic', '')).upper()} ({session.get('seniority', 'mid')})",
          12, color=(90, 90, 90))
    pdf.ln(10)
    _text(pdf.get_y(), f"Overall Score: {report['overall_score']}/100", 18, bold=True)
    pdf.ln(6)
    for d, v in report["dimension_scores"].items():
        _text(pdf.get_y(), f"{d.replace('_', ' ').title()}: {v}/100", 12)
        pdf.ln(2)
    pdf.ln(4)
    _text(pdf.get_y(), "Verdict", 14, bold=True)
    pdf.ln(2)
    body = "".join(f"+ {s}\n" for s in report.get("strengths", []))
    body += "".join(f"- {w}\n" for w in report.get("weaknesses", []))
    _text(pdf.get_y(), body or "No detailed feedback available.", 11)

    return bytes(pdf.output())
