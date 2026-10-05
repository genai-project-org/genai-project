"""Practice Engine routes — problem list/detail, code submission + grading."""
import logging
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user
from models import User
from services.pricing_engine import spend, precheck
from services.practice_service import (
    list_problems,
    get_problem_public,
    get_problem_raw,
    run_submission,
    run_sql_submission,
    grade_mcq,
    record_submission,
    list_submissions,
    get_submission,
    list_roadmap,
    get_solved_problem_ids,
    get_progress,
    PistonUnavailableError,
)
from services.practice_ai_service import (
    classify_mistake,
    log_mistake,
    get_recurring_mistakes,
    resolve_mistake_pattern,
    generate_feedback,
    create_variant,
    get_variant,
    grade_design_submission,
    summarize_excalidraw_elements,
)
from services.data_lake import log_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/practice", tags=["practice"])

PRICE_KEY_SUBMIT = "practice_submit"
PRICE_KEY_FEEDBACK = "practice_ai_feedback"
PRICE_KEY_VARIANT = "practice_variant_generate"
PRICE_KEY_MCQ = "practice_mcq_submit"
PRICE_KEY_DESIGN = "practice_design_submit"

# A design submission is scored (0-100%) by an LLM against a rubric, not
# pass/failed against a fixed test — there's no natural pass/fail line the
# way there is for code/SQL/MCQ. To still let a design problem count toward
# roadmap/streak progress (both of which key off `all_passed`), a submission
# scoring at or above this threshold is considered "solved". Documented here
# rather than buried in the route so the number's meaning is easy to find.
DESIGN_PASS_THRESHOLD_PCT = 70


class SubmitRequest(BaseModel):
    code: str = Field(min_length=1, max_length=20000)
    language: Literal["python", "javascript", "cpp", "java", "sql"] = "python"


class FeedbackRequest(BaseModel):
    submission_id: str


class VariantRequest(BaseModel):
    # If set, bias generation toward re-testing this specific recurring
    # mistake instead of a generic variant.
    target_mistake_type: Optional[str] = None


class McqSubmitRequest(BaseModel):
    selected_option_id: str = Field(min_length=1, max_length=100)


class DiagramSubmission(BaseModel):
    """What the Excalidraw canvas hands the backend: a rendered PNG of the
    drawn scene (the PRIMARY grading signal — see
    `practice_ai_service.grade_design_submission`) plus, optionally, the raw
    Excalidraw scene elements (rectangles/ellipses/arrows/text/freedraw
    strokes with positions and, for arrows, shape bindings) for a best-effort
    supplementary text hint. `image_base64` has no `data:image/png;base64,`
    prefix — just the raw base64 payload, matching every other image-input
    call site in this codebase (see `services.llm_client.ImageContent`)."""
    image_base64: str = Field(min_length=1, max_length=8_000_000)
    elements: Optional[List[Dict[str, Any]]] = None


class DesignSubmitRequest(BaseModel):
    answer_text: str = Field(min_length=1, max_length=20000)
    # Both optional and additive — a problem that doesn't set
    # `supports_diagram`/`supports_calculation` ignores these even if a client
    # sends them, so an old client (or a problem seeded before this feature)
    # keeps grading exactly as before.
    diagram: Optional[DiagramSubmission] = None
    calculation_text: Optional[str] = Field(default=None, max_length=5000)


@router.get("/problems")
async def get_problems(user: User = Depends(get_current_user)):
    items = await list_problems()
    return {"items": items}


@router.get("/roadmap")
async def get_roadmap(user: User = Depends(get_current_user)):
    """Problems grouped by topic `step`, ordered within it, each flagged
    `solved` if the CURRENT user has ever gotten `all_passed: true` on it.
    A single aggregation for solved ids — never the whole submission history."""
    items = await list_roadmap()
    solved_ids = set(await get_solved_problem_ids(user.id))
    for item in items:
        item["solved"] = item["id"] in solved_ids
    return {"items": items}


@router.get("/progress")
async def get_progress_route(user: User = Depends(get_current_user)):
    """Dashboard numbers for the roadmap page: total solved/total, per-step
    completion, and the current daily streak — aggregated in Mongo."""
    return await get_progress(user.id)


@router.get("/problems/{problem_id}")
async def get_problem(problem_id: str, user: User = Depends(get_current_user)):
    doc = await get_problem_public(problem_id)
    if not doc:
        raise HTTPException(404, "Problem not found")
    return doc


@router.get("/problems/{problem_id}/submissions")
async def get_submissions(problem_id: str, user: User = Depends(get_current_user)):
    """The requesting user's own past submissions for this problem — never
    another user's, regardless of who's asking."""
    items = await list_submissions(user.id, problem_id)
    return {"items": items}


@router.post("/problems/{problem_id}/run")
async def run_solution(problem_id: str, req: SubmitRequest, user: User = Depends(get_current_user)):
    """Free — runs the query/code against the problem's sample test cases
    (or, for SQL, the same single seeded database "submit" grades against —
    there's no separate hidden-suite concept for SQL), full detail, no
    credit charge, and nothing recorded. This is deliberately separate from
    /submit. MCQ/design problems don't have a "Run" concept — use their own
    submit endpoints below."""
    problem = await get_problem_raw(problem_id)
    if not problem:
        raise HTTPException(404, "Problem not found")
    question_type = problem.get("question_type", "code")
    if question_type in ("mcq", "design"):
        raise HTTPException(400, f"This is a '{question_type}' problem — use its dedicated submit endpoint, not /run.")
    if req.language not in (problem.get("starter_code") or {}):
        raise HTTPException(400, f"Problem does not support language `{req.language}`")

    try:
        if question_type == "sql":
            run_result = await run_sql_submission(problem, req.code)
        else:
            run_result = await run_submission(problem, req.code, req.language, sample_only=True)
    except PistonUnavailableError as e:
        raise HTTPException(502, f"Code execution service unavailable: {e}")
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))

    return {
        "results": run_result["results"],
        "passed_count": run_result["passed_count"],
        "total": run_result["total"],
        "all_passed": run_result["all_passed"],
    }


@router.post("/problems/{problem_id}/submit")
async def submit_solution(problem_id: str, req: SubmitRequest, user: User = Depends(get_current_user)):
    problem = await get_problem_raw(problem_id)
    if not problem:
        raise HTTPException(404, "Problem not found")
    question_type = problem.get("question_type", "code")
    if question_type in ("mcq", "design"):
        raise HTTPException(400, f"This is a '{question_type}' problem — use its dedicated submit endpoint, not /submit.")
    if req.language not in (problem.get("starter_code") or {}):
        raise HTTPException(400, f"Problem does not support language `{req.language}`")

    # Gate on credits BEFORE burning a Piston call. SQL reuses the exact same
    # `practice_submit` price as code — see pricing_engine.DEFAULT_PRICING's
    # comment for why (grading cost is comparable: a bounded local execution
    # + result comparison either way).
    await precheck(user.id, PRICE_KEY_SUBMIT)

    try:
        if question_type == "sql":
            run_result = await run_sql_submission(problem, req.code)
        else:
            run_result = await run_submission(problem, req.code, req.language)
    except PistonUnavailableError as e:
        raise HTTPException(502, f"Code execution service unavailable: {e}")
    except RuntimeError as e:
        raise HTTPException(502, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))

    # Only charge once we actually got a result back from the execution service.
    billing = await spend(
        user.id, PRICE_KEY_SUBMIT,
        description=f"Practice submit: {problem.get('title', problem_id)}",
        ref_id=problem_id,
    )
    submission = await record_submission(user.id, problem_id, req.code, req.language, run_result)

    # Mistake Memory — free, automatic, best-effort: classify WHY a failed
    # submission is wrong so patterns can be tracked over time. Code-only (the
    # classifier's taxonomy/prompting assumes a Piston test-case failure shape
    # that doesn't apply to a SQL result-set mismatch). Never lets a
    # classification hiccup break the submit response itself.
    if question_type == "code" and not run_result["all_passed"]:
        try:
            classification = await classify_mistake(problem, req.code, req.language, run_result["results"])
            await log_mistake(
                user.id, problem_id, submission["_id"],
                classification["mistake_type"], classification["description"],
            )
        except Exception:
            logger.exception("Mistake classification failed for submission %s", submission["_id"])

    await log_event("practice_submit", user_id=user.id, payload={
        "problem_id": problem_id, "language": req.language, "question_type": question_type,
        "all_passed": run_result["all_passed"],
        "passed_count": run_result["passed_count"], "total": run_result["total"],
    })

    return {
        "submission_id": submission["_id"],
        "results": run_result["results"],
        "passed_count": run_result["passed_count"],
        "total": run_result["total"],
        "all_passed": run_result["all_passed"],
        "credits_used": billing["credits_used"],
        "balance": billing["balance"],
    }


@router.post("/problems/{problem_id}/submit-mcq")
async def submit_mcq_solution(problem_id: str, req: McqSubmitRequest, user: User = Depends(get_current_user)):
    """MCQ grading — trivial equality check, no Piston, no LLM. Priced at 0
    credits (see pricing_engine.DEFAULT_PRICING's comment) but still routed
    through precheck/spend so it's logged the same way every other practice
    action is, at zero cost. Always reveals the correct option after
    submitting, win or lose — that's the normal MCQ-practice learning loop,
    not something to gate behind a pass."""
    problem = await get_problem_raw(problem_id)
    if not problem:
        raise HTTPException(404, "Problem not found")
    if problem.get("question_type") != "mcq":
        raise HTTPException(400, "This problem is not a multiple-choice question")
    valid_ids = {o["id"] for o in problem.get("options", [])}
    if req.selected_option_id not in valid_ids:
        raise HTTPException(400, f"Unknown option id `{req.selected_option_id}`")

    await precheck(user.id, PRICE_KEY_MCQ)
    grading = grade_mcq(problem, req.selected_option_id)

    billing = await spend(
        user.id, PRICE_KEY_MCQ,
        description=f"Practice MCQ submit: {problem.get('title', problem_id)}", ref_id=problem_id,
    )
    submission = await record_submission(
        user.id, problem_id, None, None,
        {"passed_count": 1 if grading["passed"] else 0, "total": 1, "all_passed": grading["passed"]},
        extra={
            "question_type": "mcq",
            "selected_option_id": grading["selected_option_id"],
            "correct_option_id": grading["correct_option_id"],
        },
    )

    await log_event("practice_submit", user_id=user.id, payload={
        "problem_id": problem_id, "question_type": "mcq", "all_passed": grading["passed"],
    })

    return {
        "submission_id": submission["_id"],
        "passed": grading["passed"],
        "correct_option_id": grading["correct_option_id"],
        "all_passed": grading["passed"],
        "credits_used": billing["credits_used"],
        "balance": billing["balance"],
    }


@router.post("/problems/{problem_id}/submit-design")
async def submit_design_solution(problem_id: str, req: DesignSubmitRequest, user: User = Depends(get_current_user)):
    """Design (LLD/HLD) grading — credit-gated, the most expensive practice
    question type (a real Sonnet call reasoning over a full rubric — see
    pricing_engine.DEFAULT_PRICING's `practice_design_submit` comment).
    Returns a per-criterion score/feedback breakdown, not just pass/fail —
    there's no single correct answer to reduce this to."""
    problem = await get_problem_raw(problem_id)
    if not problem:
        raise HTTPException(404, "Problem not found")
    if problem.get("question_type") != "design":
        raise HTTPException(400, "This problem is not a design question")

    # Diagram/calculation are opt-in PER PROBLEM — a problem that never set
    # `supports_diagram`/`supports_calculation` (every problem seeded before
    # this feature, and any design problem the concurrent bulk-generator adds
    # without them) ignores these fields even if a client sends them, so its
    # grading call is identical to before this feature existed.
    diagram_image_base64 = None
    diagram_text_hint = None
    if problem.get("supports_diagram") and req.diagram:
        diagram_image_base64 = req.diagram.image_base64
        diagram_text_hint = summarize_excalidraw_elements(req.diagram.elements)
    calculation_text = req.calculation_text if problem.get("supports_calculation") and req.calculation_text else None

    await precheck(user.id, PRICE_KEY_DESIGN)
    try:
        grading = await grade_design_submission(
            problem, req.answer_text,
            diagram_image_base64=diagram_image_base64,
            diagram_text_hint=diagram_text_hint,
            calculation_text=calculation_text,
        )
    except Exception as e:
        raise HTTPException(502, f"AI design grading failed: {e}")

    billing = await spend(
        user.id, PRICE_KEY_DESIGN,
        description=f"Practice design submit: {problem.get('title', problem_id)}", ref_id=problem_id,
    )
    # A design answer is scored, not pass/failed against a fixed test — see
    # DESIGN_PASS_THRESHOLD_PCT's module-level comment for why this specific
    # cutoff is what counts as "solved" for roadmap/streak purposes.
    passed = grading["pct"] >= DESIGN_PASS_THRESHOLD_PCT
    extra = {
        "question_type": "design",
        "criteria": grading["criteria"],
        "overall_feedback": grading["overall_feedback"],
        "total_score": grading["total_score"],
        "max_total_score": grading["max_total_score"],
        "pct": grading["pct"],
    }
    if diagram_image_base64:
        extra["diagram"] = req.diagram.model_dump()
    if calculation_text:
        extra["calculation_text"] = calculation_text
    submission = await record_submission(
        user.id, problem_id, req.answer_text, None,
        {"passed_count": 1 if passed else 0, "total": 1, "all_passed": passed},
        extra=extra,
    )

    await log_event("practice_submit", user_id=user.id, payload={
        "problem_id": problem_id, "question_type": "design", "all_passed": passed, "pct": grading["pct"],
    })

    return {
        "submission_id": submission["_id"],
        "criteria": grading["criteria"],
        "overall_feedback": grading["overall_feedback"],
        "total_score": grading["total_score"],
        "max_total_score": grading["max_total_score"],
        "pct": grading["pct"],
        "all_passed": passed,
        "credits_used": billing["credits_used"],
        "balance": billing["balance"],
    }


@router.get("/mistakes")
async def get_my_mistakes(user: User = Depends(get_current_user)):
    """This user's recurring, unresolved mistake patterns — most frequent first."""
    return {"items": await get_recurring_mistakes(user.id)}


@router.post("/problems/{problem_id}/feedback")
async def get_ai_feedback(problem_id: str, req: FeedbackRequest, user: User = Depends(get_current_user)):
    """Credit-gated. Explains the conceptual issue in a specific past failed
    submission — never determines pass/fail, that's Piston-only and already
    happened. References the user's own recurring mistake history if one applies."""
    problem = await get_problem_raw(problem_id)
    if not problem:
        raise HTTPException(404, "Problem not found")
    submission = await get_submission(user.id, req.submission_id)
    if not submission or submission["problem_id"] != problem_id:
        raise HTTPException(404, "Submission not found")
    if submission["all_passed"]:
        raise HTTPException(400, "This submission already passed — nothing to explain")

    await precheck(user.id, PRICE_KEY_FEEDBACK)
    recurring = await get_recurring_mistakes(user.id)
    try:
        feedback = await generate_feedback(problem, submission["code"], submission["language"], submission["results"], recurring)
    except Exception as e:
        raise HTTPException(502, f"AI feedback generation failed: {e}")

    billing = await spend(
        user.id, PRICE_KEY_FEEDBACK,
        description=f"AI feedback: {problem.get('title', problem_id)}", ref_id=problem_id,
    )
    return {"feedback": feedback, "credits_used": billing["credits_used"], "balance": billing["balance"]}


@router.post("/problems/{problem_id}/variant")
async def create_ai_variant(problem_id: str, req: VariantRequest, user: User = Depends(get_current_user)):
    """Credit-gated. Generates a fresh variant of a problem — same pattern,
    different surface. If `target_mistake_type` matches a recurring pattern
    of this user's, the variant is deliberately designed to re-test it."""
    problem = await get_problem_raw(problem_id)
    if not problem:
        raise HTTPException(404, "Problem not found")
    if "python" not in (problem.get("starter_code") or {}):
        raise HTTPException(400, "Variants are only supported for problems with a Python solution")

    target_mistake = None
    if req.target_mistake_type:
        recurring = await get_recurring_mistakes(user.id)
        target_mistake = next((m for m in recurring if m["mistake_type"] == req.target_mistake_type), None)
        if not target_mistake:
            raise HTTPException(400, f"No recurring '{req.target_mistake_type}' pattern found for this user")

    await precheck(user.id, PRICE_KEY_VARIANT)
    try:
        variant = await create_variant(user.id, problem_id, problem, target_mistake)
    except Exception as e:
        raise HTTPException(502, f"Variant generation failed: {e}")

    billing = await spend(
        user.id, PRICE_KEY_VARIANT,
        description=f"AI variant: {problem.get('title', problem_id)}", ref_id=problem_id,
    )
    p = variant["problem"]
    return {
        "variant_id": variant["_id"],
        "target_mistake_type": variant["target_mistake_type"],
        "title": p["title"],
        "description": p["description"],
        "examples": p["examples"],
        "constraints": p["constraints"],
        "difficulty": p["difficulty"],
        "tags": p["tags"],
        "starter_code": p["starter_code"],
        "languages": list(p["starter_code"].keys()),
        "credits_used": billing["credits_used"],
        "balance": billing["balance"],
    }


@router.post("/variants/{variant_id}/submit")
async def submit_variant_solution(variant_id: str, req: SubmitRequest, user: User = Depends(get_current_user)):
    """Free to submit against — the credit was already spent generating the
    variant. Grading reuses the exact same Piston-based run_submission as a
    real problem; a pass resolves the targeted mistake pattern, if any."""
    variant = await get_variant(variant_id, user.id)
    if not variant:
        raise HTTPException(404, "Variant not found")
    problem = variant["problem"]
    if req.language not in (problem.get("starter_code") or {}):
        raise HTTPException(400, f"This variant does not support language `{req.language}`")

    try:
        run_result = await run_submission(problem, req.code, req.language)
    except PistonUnavailableError as e:
        raise HTTPException(502, f"Code execution service unavailable: {e}")
    except ValueError as e:
        raise HTTPException(400, str(e))

    if run_result["all_passed"] and variant.get("target_mistake_type"):
        await resolve_mistake_pattern(user.id, variant["target_mistake_type"])

    return {
        "results": run_result["results"],
        "passed_count": run_result["passed_count"],
        "total": run_result["total"],
        "all_passed": run_result["all_passed"],
        "resolved_mistake_type": variant.get("target_mistake_type") if run_result["all_passed"] else None,
    }
