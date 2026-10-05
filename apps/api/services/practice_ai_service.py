"""AI-native layer on top of the Practice Engine — three interlocking pieces:

1. Mistake Memory — classify *why* a failed submission is wrong (not just
   pass/fail, which stays Piston-only and untouched here), log it per-user
   over time, surface recurring patterns. Free, automatic.
2. AI Feedback — credit-gated: explain the conceptual issue in a specific
   failed submission, referencing the user's own recurring pattern history.
3. AI Variants — credit-gated: generate a fresh, never-seen variant of a
   solved problem to test real understanding vs memorization. Optionally
   biased toward re-testing a user's own unresolved mistake pattern.

Correctness safeguard for variants: an LLM asked to invent test data AND
state its own expected outputs will sometimes get its own expected values
wrong. We never trust an LLM-stated expected output — we have it generate a
reference solution instead, then actually RUN that solution through Piston
for each test input to derive real ground truth, the same way a real judge
validates generated test data.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

from db import db, now_iso
from services.llm_client import LlmChat, UserMessage, ImageContent
from services.practice_service import (
    LANGUAGE_RUNTIMES,
    _py_harness,
    _piston_execute,
    PistonUnavailableError,
)

logger = logging.getLogger(__name__)

practice_mistake_log_col = db["practice_mistake_log"]
practice_variants_col = db["practice_variants"]

FEEDBACK_MODEL = "claude-haiku-4-5-20251001"
VARIANT_MODEL = "claude-sonnet-5"  # variant generation needs to reason about correctness, not just chat
DESIGN_GRADING_MODEL = "claude-sonnet-5"  # a real rubric-based judgment call, not a chat reply

MISTAKE_TAXONOMY_DEFS = {
    "off-by-one": "An index/bound is one too high or low — e.g. `<` vs `<=`, `i+1` vs `i`.",
    "wrong-base-case": "A recursive or DP base case is missing, wrong, or handled at the wrong point.",
    "inverted-logic": "A value and its complement/inverse are swapped — e.g. storing or looking up "
                       "`target - n` as the key instead of storing `n` and looking up `target - n`, or "
                       "checking `not condition` where `condition` was meant.",
    "mutation-during-iteration": "The collection being iterated is modified (inserted into/removed from) "
                                  "while the loop is still iterating over it, causing skipped or repeated elements.",
    "incomplete-edge-case-handling": "The logic is right for the common case but doesn't account for an "
                                      "edge case explicitly covered in the constraints (empty input, single "
                                      "element, all-duplicates, negative numbers, etc.).",
    "wrong-data-structure-choice": "A fundamentally different data structure was needed (e.g. used a list "
                                    "with linear lookups where a hash map/set was needed for the required "
                                    "time complexity) — the algorithm's shape is right but the container is wrong.",
    "type-or-overflow-error": "A type mismatch, integer overflow, or language-specific numeric issue.",
    "wrong-comparison-direction": "A comparison operator points the wrong way — e.g. `>` where `<` was "
                                   "needed, sorting ascending where descending was needed.",
    "other": "Doesn't clearly fit any category above.",
}
MISTAKE_TAXONOMY = list(MISTAKE_TAXONOMY_DEFS.keys())


def _extract_json(text: str) -> Dict[str, Any]:
    """Same tolerant strategy as builder_service._extract_json — duplicated
    locally rather than cross-importing, since it's a 10-line pure function."""
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError("No JSON object found in LLM response")


# ---------------------------------------------------------------------------
# 1. Mistake Memory
# ---------------------------------------------------------------------------
_TAXONOMY_LIST = "\n".join(f"- \"{k}\": {v}" for k, v in MISTAKE_TAXONOMY_DEFS.items())
CLASSIFY_SYSTEM_PROMPT = (
    "You classify why a coding-practice submission failed, using EXACTLY one of these categories "
    f"(pick the one whose definition actually matches the code, not just the closest-sounding name):\n{_TAXONOMY_LIST}\n\n"
    "Respond with ONLY a JSON object: {\"mistake_type\": \"<one of the category keys above>\", "
    "\"description\": a one-sentence, specific explanation of the actual bug in THIS code — not "
    "generic advice}. No markdown, no prose outside the JSON."
)


async def classify_mistake(problem: dict, code: str, language: str, results: List[dict]) -> Dict[str, str]:
    failing = [r for r in results if not r.get("passed")]
    prompt = (
        f"Problem: {problem.get('title')}\n{problem.get('description', '')[:500]}\n\n"
        f"Submitted {language} code:\n```\n{code[:3000]}\n```\n\n"
        f"Failing test case(s) (up to 2 shown): {json.dumps(failing[:2], default=str)[:1500]}"
    )
    chat = LlmChat(system_message=CLASSIFY_SYSTEM_PROMPT).with_model("anthropic", FEEDBACK_MODEL, max_tokens=300)
    resp = await chat.send_message(UserMessage(text=prompt))
    data = _extract_json(resp)
    mistake_type = data.get("mistake_type") if data.get("mistake_type") in MISTAKE_TAXONOMY else "other"
    return {"mistake_type": mistake_type, "description": data.get("description", "")}


async def log_mistake(user_id: str, problem_id: str, submission_id: str, mistake_type: str, description: str) -> None:
    await practice_mistake_log_col.insert_one({
        "user_id": user_id,
        "problem_id": problem_id,
        "submission_id": submission_id,
        "mistake_type": mistake_type,
        "description": description,
        "resolved": False,
        "created_at": now_iso(),
    })


async def get_recurring_mistakes(user_id: str, only_unresolved: bool = True) -> List[Dict[str, Any]]:
    """Aggregate this user's mistake types by count, most-frequent first."""
    match: Dict[str, Any] = {"user_id": user_id}
    if only_unresolved:
        match["resolved"] = False
    pipeline = [
        {"$match": match},
        {"$group": {"_id": "$mistake_type", "count": {"$sum": 1}, "last_seen": {"$max": "$created_at"}}},
        {"$sort": {"count": -1}},
    ]
    out = []
    async for row in practice_mistake_log_col.aggregate(pipeline):
        out.append({"mistake_type": row["_id"], "count": row["count"], "last_seen": row["last_seen"]})
    return out


async def resolve_mistake_pattern(user_id: str, mistake_type: str) -> None:
    await practice_mistake_log_col.update_many(
        {"user_id": user_id, "mistake_type": mistake_type, "resolved": False},
        {"$set": {"resolved": True, "resolved_at": now_iso()}},
    )


# ---------------------------------------------------------------------------
# 2. AI Feedback
# ---------------------------------------------------------------------------
FEEDBACK_SYSTEM_PROMPT = (
    "You are a patient but direct coding mentor. A student's submission failed. "
    "Explain the CONCEPTUAL misconception behind the bug — not a fixed version of "
    "their code, not a generic tip. Point at the specific flawed assumption in "
    "THEIR code. If told this is a repeat of a pattern they've done before, say so "
    "plainly and explain why it keeps happening. 3-5 sentences, no code blocks, no fluff."
)


async def generate_feedback(
    problem: dict, code: str, language: str, results: List[dict], recurring: List[Dict[str, Any]]
) -> str:
    failing = [r for r in results if not r.get("passed")]
    repeat_note = ""
    for r in recurring:
        if r["count"] >= 2:
            repeat_note += f"\nNote: this student has made a '{r['mistake_type']}' mistake {r['count']} times before."
    prompt = (
        f"Problem: {problem.get('title')}\n{problem.get('description', '')[:500]}\n\n"
        f"Their {language} code:\n```\n{code[:3000]}\n```\n\n"
        f"What failed: {json.dumps(failing[:2], default=str)[:1500]}"
        f"{repeat_note}"
    )
    chat = LlmChat(system_message=FEEDBACK_SYSTEM_PROMPT).with_model("anthropic", FEEDBACK_MODEL, max_tokens=400)
    return await chat.send_message(UserMessage(text=prompt))


# ---------------------------------------------------------------------------
# 3. AI Variants — generate, then validate expected outputs by EXECUTION,
#    never trust the LLM's own stated expected values.
# ---------------------------------------------------------------------------
VARIANT_SYSTEM_PROMPT = (
    "You invent a variant of a coding practice problem — same underlying pattern "
    "and same function signature (same params/output shape), but a genuinely "
    "different surface so someone who memorized the original can't just paste the "
    "same code unchanged. If told to target a specific past mistake, design the "
    "variant so that exact mistake would cause a wrong answer.\n\n"
    "Respond with ONLY a JSON object:\n"
    "{\"title\": str, \"description\": str, \"examples\": [{\"input\":str,\"output\":str,\"explanation\":str}], "
    "\"constraints\": [str], \"entry_point\": str (same as original), "
    "\"starter_code_python\": str (function signature only, body is `pass`), "
    "\"reference_solution_python\": str (a full, correct, working solution — this will "
    "be EXECUTED to derive real expected outputs, so it must be genuinely correct "
    "runnable Python, not pseudocode), "
    "\"test_inputs\": [ {<param_name>: value, ...}, ... ] (5-6 inputs, matching the "
    "given params exactly, covering normal + edge cases for the NEW variant)}\n"
    "No markdown fences, no prose outside the JSON."
)


async def generate_variant(problem: dict, target_mistake: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Returns a full variant problem dict (same shape run_submission expects)
    with `test_cases` whose `expected` values were derived by actually
    executing the LLM's reference solution, not by trusting its own claims."""
    target_note = ""
    if target_mistake:
        target_note = (
            f"\nThis student has repeatedly made a '{target_mistake['mistake_type']}' mistake "
            f"({target_mistake['count']} times). Specifically design this variant so that exact "
            f"mistake would produce a wrong answer, to test whether they've actually fixed it."
        )
    prompt = (
        f"Original problem: {problem.get('title')}\n{problem.get('description', '')[:500]}\n"
        f"params: {json.dumps(problem.get('params', []))}\n"
        f"output_type: {problem.get('output_type')}\n"
        f"entry_point: {problem.get('entry_point', {}).get('python')}"
        f"{target_note}"
    )
    # 16000, not a smaller number: claude-sonnet-5 defaults to extended
    # thinking, which spends tokens BEFORE producing visible answer text —
    # too low a budget here means the thinking pass consumes it all and the
    # response comes back empty (confirmed happening at 2000). Same reason
    # builder_service.py uses 16000 for its own Sonnet calls.
    chat = LlmChat(system_message=VARIANT_SYSTEM_PROMPT).with_model("anthropic", VARIANT_MODEL, max_tokens=16000)
    resp = await chat.send_message(UserMessage(text=prompt))
    spec = _extract_json(resp)

    params = problem.get("params", [])
    output_type = problem.get("output_type")
    entry_point = spec["entry_point"]
    reference_code = spec["reference_solution_python"]
    harness = _py_harness(entry_point, params, output_type)
    full_source = reference_code + harness
    lang_cfg = LANGUAGE_RUNTIMES["python"]

    test_cases = []
    for i, inp in enumerate(spec.get("test_inputs", [])):
        stdin = json.dumps(inp)
        try:
            run = await _piston_execute(lang_cfg["piston_language"], lang_cfg["piston_version"], full_source, stdin)
        except PistonUnavailableError as e:
            raise RuntimeError(f"Reference solution execution failed for input {i}: {e}") from e
        stdout = (run.get("stdout") or "").strip()
        exit_code = run.get("code")
        signal = run.get("signal")
        if signal or (exit_code not in (0, None)) or not stdout:
            # The reference solution itself is broken — don't serve broken test
            # data. Caller should treat this as a failed generation attempt.
            raise RuntimeError(
                f"Reference solution crashed/produced no output for input {i}: "
                f"stderr={(run.get('stderr') or '')[:300]}"
            )
        try:
            expected = json.loads(stdout)
        except Exception as e:
            raise RuntimeError(f"Reference solution output wasn't valid JSON for input {i}: {stdout[:200]}") from e
        test_cases.append({"input": inp, "expected": expected, "is_sample": i < 2})

    return {
        "title": spec["title"],
        "description": spec["description"],
        "examples": spec.get("examples", []),
        "constraints": spec.get("constraints", []),
        "difficulty": problem.get("difficulty", "Medium"),
        "tags": problem.get("tags", []),
        "params": params,
        "output_type": output_type,
        "entry_point": {"python": entry_point},
        "starter_code": {"python": spec["starter_code_python"]},
        "test_cases": test_cases,
    }


async def create_variant(
    user_id: str, source_problem_id: str, problem: dict, target_mistake: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    variant_problem = await generate_variant(problem, target_mistake)
    doc = {
        "user_id": user_id,
        "source_problem_id": source_problem_id,
        "target_mistake_type": target_mistake["mistake_type"] if target_mistake else None,
        "problem": variant_problem,
        "created_at": now_iso(),
    }
    ins = await practice_variants_col.insert_one(doc)
    doc["_id"] = str(ins.inserted_id)
    return doc


async def get_variant(variant_id: str, user_id: str) -> Optional[dict]:
    from bson import ObjectId
    doc = await practice_variants_col.find_one({"_id": ObjectId(variant_id), "user_id": user_id})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


# ---------------------------------------------------------------------------
# 4. AI Design Grading — `question_type: "design"` (System Design: HLD/LLD).
# The most novel and most expensive question type: no Piston, no single
# correct answer to compare against — a free-text written answer is graded
# by the LLM against the problem's own explicit `rubric` (a hand-written list
# of {criterion, description, max_score}), returning a per-criterion
# score/feedback breakdown rather than a bare pass/fail, since there's no
# single correct answer here to reduce this to.
# ---------------------------------------------------------------------------
DESIGN_GRADING_SYSTEM_PROMPT = (
    "You are a strict but fair system-design interviewer grading a candidate's submission "
    "against an explicit rubric. The submission may include up to three parts: a WRITTEN "
    "answer, a hand-sketched ARCHITECTURE DIAGRAM, and BACK-OF-ENVELOPE CALCULATIONS (a "
    "scratchpad of scale estimates). The diagram is a FREEFORM DRAWING — the candidate used a "
    "whiteboard-style tool (pen, shapes, arrows, text) exactly like they would on a real "
    "whiteboard or napkin, not a structured node/edge graph. When a diagram is present, an "
    "IMAGE of it is attached to this message — look at the image directly and judge what is "
    "actually visible: which boxes/shapes are drawn, what their text labels say, which shapes "
    "arrows connect and in which direction, and the overall layout. A best-effort plain-text "
    "hint mechanically extracted from the drawing's raw shape/text data may also appear below "
    "— treat it only as a hint that might be incomplete or miss freehand strokes; the IMAGE is "
    "the authoritative source of what was actually drawn.\n\n"
    "Some rubric criteria are tagged with which part they judge — a criterion tagged 'evaluate "
    "against the diagram' must be scored based on what is VISUALLY RECOGNIZABLE in the image "
    "(e.g. 'a load-balancing layer is drawn fanning out to multiple boxes', 'a box labeled "
    "cache sits between the API and database boxes with arrows connecting them'), NOT the "
    "written prose, and a criterion tagged 'evaluate against the calculations' must be scored "
    "based on the actual numbers/assumptions written there. If a tagged part is missing, blank, "
    "or the image shows nothing meaningful for that criterion, score it low and say so — never "
    "invent content that isn't actually visible or written. Score EACH criterion independently "
    "on a 0 to <max_score> integer scale, with 1-3 sentences of feedback tied to SPECIFICS in "
    "the relevant part (describe what you actually saw drawn, or quote/paraphrase what they "
    "wrote, or name the specific numbers they used) — never generic advice, and never give "
    "credit for something they didn't actually show or say.\n\n"
    "Respond with ONLY a JSON object:\n"
    "{\"criteria\": [{\"criterion\": str (copy EXACTLY as given in the rubric), "
    "\"score\": int, \"max_score\": int (copy exactly as given), \"feedback\": str}], "
    "\"overall_feedback\": str (2-4 sentences on what would most improve this answer)}\n"
    "No markdown fences, no prose outside the JSON."
)

# Rubric criteria may optionally carry `applies_to`: "diagram" | "calculation" | "answer"
# (default "answer" when absent, matching every criterion authored before this field
# existed). This only changes the prompt's per-criterion annotation — a rubric with no
# `applies_to` fields anywhere produces byte-identical rubric text to before this feature.
_APPLIES_TO_NOTE = {
    "diagram": " — evaluate against the DIAGRAM below, not the written answer.",
    "calculation": " — evaluate against the CALCULATIONS below, not the written answer.",
    "answer": "",
}


def summarize_excalidraw_elements(elements: Optional[List[Dict[str, Any]]]) -> str:
    """Best-effort, SECONDARY plain-text hint mechanically extracted from
    Excalidraw's raw scene JSON (a flat list of elements: rectangles,
    ellipses, diamonds, arrows, freedraw strokes, and text — see
    https://github.com/excalidraw/excalidraw's `ExcalidrawElement` type).
    This supplements the rendered PNG image sent to the grader; it is never
    the primary signal (freehand strokes and loosely-placed text carry no
    clean structure to extract), so this stays intentionally simple:

    - A text element bound to a shape (`containerId` pointing at a
      rectangle/ellipse/diamond) becomes that shape's label.
    - An arrow whose `startBinding`/`endBinding` both resolve to a labeled
      shape becomes a "A -> B" connection.
    - Any other non-empty text element (not bound to a shape — a loose
      caption, e.g.) is listed separately.

    Freedraw strokes are deliberately not summarized as text at all here
    (there is nothing meaningful to extract from raw pen-stroke points) —
    they're only ever conveyed via the image. Returns "" for no/empty
    elements so callers can treat that as "nothing to include"."""
    if not elements:
        return ""
    shape_types = {"rectangle", "ellipse", "diamond"}
    shape_labels: Dict[str, str] = {}
    for el in elements:
        if el.get("isDeleted"):
            continue
        if el.get("type") in shape_types and el.get("id"):
            shape_labels[el["id"]] = ""  # placeholder until a bound text element fills it in

    loose_texts: List[str] = []
    for el in elements:
        if el.get("isDeleted") or el.get("type") != "text":
            continue
        text = str(el.get("text") or "").strip()
        if not text:
            continue
        container = el.get("containerId")
        if container and container in shape_labels:
            shape_labels[container] = text
        else:
            loose_texts.append(text)

    connections: List[str] = []
    for el in elements:
        if el.get("isDeleted") or el.get("type") != "arrow":
            continue
        start_id = (el.get("startBinding") or {}).get("elementId")
        end_id = (el.get("endBinding") or {}).get("elementId")
        start_label = shape_labels.get(start_id)
        end_label = shape_labels.get(end_id)
        if start_label and end_label:
            connections.append(f"{start_label} -> {end_label}")

    labeled_shapes = [label for label in shape_labels.values() if label]
    parts = []
    if labeled_shapes:
        parts.append("Labeled shapes drawn: " + ", ".join(labeled_shapes) + ".")
    if connections:
        parts.append("Arrows connecting labeled shapes: " + ", ".join(connections) + ".")
    if loose_texts:
        parts.append("Other text on the canvas: " + ", ".join(loose_texts) + ".")
    return " ".join(parts)


async def grade_design_submission(
    problem: dict,
    answer_text: str,
    diagram_image_base64: Optional[str] = None,
    diagram_text_hint: Optional[str] = None,
    calculation_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Grades a design submission against `problem["rubric"]`. Returns a
    per-criterion score/feedback breakdown plus a total/pct — there's no
    pass/fail concept here, only a structured score (the route layer decides
    what score counts as "solved" for roadmap/streak purposes).

    `diagram_image_base64` (a rendered PNG of the candidate's Excalidraw
    canvas, base64-encoded) is the PRIMARY diagram signal — it's attached to
    the grading call as a real image via the same vision-input path used
    elsewhere in this codebase (see `services.ai_service.stream_ai_response`
    for the established pattern this reuses exactly). `diagram_text_hint` is
    an OPTIONAL, best-effort supplementary text summary (see
    `summarize_excalidraw_elements`) — included alongside the image, never
    instead of it.

    All three of `diagram_image_base64`/`diagram_text_hint`/`calculation_text`
    are optional and additive: called with just `answer_text` (as every call
    site did before diagram/calculation support existed), the rubric text and
    prompt are byte-identical to the pre-existing behavior — a rubric
    criterion with no `applies_to` renders exactly as it always has, and no
    extra prompt sections/image are appended."""
    rubric = problem.get("rubric", [])
    rubric_text = "\n".join(
        f"- \"{c['criterion']}\" (max {c['max_score']})"
        f"{_APPLIES_TO_NOTE.get(c.get('applies_to', 'answer'), '')}: {c.get('description', '')}"
        for c in rubric
    )
    sections = [
        f"Design prompt: {problem.get('title')}\n{problem.get('description', '')}\n\n"
        f"Rubric:\n{rubric_text}\n\n"
        f"Candidate's written answer:\n{answer_text[:8000]}"
    ]
    if diagram_image_base64:
        sections.append(
            "An image of the candidate's hand-drawn architecture diagram is attached to this "
            "message — evaluate any diagram-tagged rubric criteria against what is actually "
            "visible in it."
        )
    if diagram_text_hint:
        sections.append(
            "Best-effort text hint mechanically extracted from the diagram's raw shape/text "
            f"data (a hint only — the attached image, if present, is authoritative):\n{diagram_text_hint[:2000]}"
        )
    if calculation_text:
        sections.append(f"Candidate's back-of-envelope calculations:\n{calculation_text[:3000]}")
    prompt = "\n\n".join(sections)
    file_contents = [ImageContent(image_base64=diagram_image_base64)] if diagram_image_base64 else None
    # 16000, not a smaller number — same reasoning as generate_variant() above:
    # claude-sonnet-5 defaults to extended thinking, which spends tokens BEFORE
    # producing visible output text, so too low a budget here silently returns
    # an empty response (confirmed happening at 2000 for the variant-generation
    # call this mirrors) rather than raising any error.
    chat = LlmChat(system_message=DESIGN_GRADING_SYSTEM_PROMPT).with_model(
        "anthropic", DESIGN_GRADING_MODEL, max_tokens=16000
    )
    resp = await chat.send_message(UserMessage(text=prompt, file_contents=file_contents))
    data = _extract_json(resp)

    # The grading prompt only asks the LLM to echo criterion/score/max_score/
    # feedback (see DESIGN_GRADING_SYSTEM_PROMPT) — `applies_to` is stitched
    # back in here from the rubric itself (matched by criterion text) so the
    # API response stays self-descriptive without relying on the LLM to
    # faithfully echo a field it was never asked to reason about. Additive:
    # a criterion with no rubric match (or a rubric with no `applies_to`
    # anywhere) simply gets "answer", identical to before this field existed.
    applies_to_by_criterion = {c["criterion"]: c.get("applies_to", "answer") for c in rubric}
    criteria = data.get("criteria", [])
    for c in criteria:
        c["applies_to"] = applies_to_by_criterion.get(c.get("criterion"), "answer")
    total_score = sum(float(c.get("score", 0)) for c in criteria)
    # Prefer the LLM-echoed max_scores (should match the rubric exactly since
    # the prompt tells it to copy them); fall back to the rubric itself if the
    # LLM ever drops the field, so a total is never silently wrong/zero.
    max_total = sum(float(c.get("max_score", 0)) for c in criteria) or sum(
        float(c.get("max_score", 0)) for c in rubric
    ) or 1.0
    return {
        "criteria": criteria,
        "overall_feedback": data.get("overall_feedback", ""),
        "total_score": total_score,
        "max_total_score": max_total,
        "pct": round(100 * total_score / max_total) if max_total else 0,
    }
