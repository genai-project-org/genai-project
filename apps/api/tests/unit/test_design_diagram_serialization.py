"""Unit tests for the Excalidraw-based diagram grading path added on top of
`grade_design_submission()` for HLD problems (`supports_diagram`/
`supports_calculation`): the best-effort structured text hint extracted from
Excalidraw's raw scene-elements JSON (`summarize_excalidraw_elements`), and
the diagram/calculation-aware grading-prompt construction (including that the
diagram image is threaded through to the LLM call as a real image via
`file_contents`, not just described in text). The LLM call itself is mocked
at the same call-site level `tests/integration/test_practice_paths_flows.py`
already uses for design grading, so these stay hermetic — no real
network/API key needed.

(This file's name predates the Excalidraw switch — kept as-is since nothing
outside this file imports it by name, and renaming isn't required.)
"""
import json

import pytest

from services import practice_ai_service as pai

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# Excalidraw elements -> best-effort plain-text hint — pure function, no LLM.
# ---------------------------------------------------------------------------
def test_summarize_excalidraw_elements_extracts_labeled_shapes_and_connections():
    elements = [
        {"id": "r1", "type": "rectangle", "isDeleted": False},
        {"id": "r2", "type": "rectangle", "isDeleted": False},
        {"id": "t1", "type": "text", "text": "API Server", "containerId": "r1", "isDeleted": False},
        {"id": "t2", "type": "text", "text": "Redis Cache", "containerId": "r2", "isDeleted": False},
        {
            "id": "a1", "type": "arrow", "isDeleted": False,
            "startBinding": {"elementId": "r1"}, "endBinding": {"elementId": "r2"},
        },
    ]
    result = pai.summarize_excalidraw_elements(elements)
    assert result == (
        "Labeled shapes drawn: API Server, Redis Cache. "
        "Arrows connecting labeled shapes: API Server -> Redis Cache."
    )


def test_summarize_excalidraw_elements_handles_missing_or_empty_scene():
    assert pai.summarize_excalidraw_elements(None) == ""
    assert pai.summarize_excalidraw_elements([]) == ""
    # Only freedraw strokes (a pen sketch with no shapes/text) — nothing
    # structured to extract; the image is the only signal for this scene.
    assert pai.summarize_excalidraw_elements(
        [{"id": "f1", "type": "freedraw", "points": [[0, 0], [10, 10]], "isDeleted": False}]
    ) == ""


def test_summarize_excalidraw_elements_lists_unbound_loose_text_separately():
    elements = [
        {"id": "r1", "type": "rectangle", "isDeleted": False},
        {"id": "t1", "type": "text", "text": "Load Balancer", "containerId": "r1", "isDeleted": False},
        # A caption dropped on the canvas, not bound inside any shape.
        {"id": "t2", "type": "text", "text": "~100M req/day", "containerId": None, "isDeleted": False},
    ]
    result = pai.summarize_excalidraw_elements(elements)
    assert result == (
        "Labeled shapes drawn: Load Balancer. Other text on the canvas: ~100M req/day."
    )


def test_summarize_excalidraw_elements_skips_deleted_and_blank_text():
    elements = [
        {"id": "r1", "type": "rectangle", "isDeleted": False},
        {"id": "t1", "type": "text", "text": "  ", "containerId": "r1", "isDeleted": False},  # blank -> skipped
        {"id": "r2", "type": "rectangle", "isDeleted": True},  # deleted shape -> ignored entirely
        {"id": "t2", "type": "text", "text": "Ghost", "containerId": "r2", "isDeleted": False},
    ]
    result = pai.summarize_excalidraw_elements(elements)
    # Nothing labeled (r1's text is blank, r2 is deleted so "Ghost" is loose
    # unbound text, not attributed to a deleted shape).
    assert result == "Other text on the canvas: Ghost."


def test_summarize_excalidraw_elements_only_connects_arrows_between_two_labeled_shapes():
    elements = [
        {"id": "r1", "type": "rectangle", "isDeleted": False},
        {"id": "t1", "type": "text", "text": "Client", "containerId": "r1", "isDeleted": False},
        # Arrow ending at an unlabeled/unknown shape — not enough to form a
        # clean "A -> B" connection, so it's dropped rather than guessed at.
        {
            "id": "a1", "type": "arrow", "isDeleted": False,
            "startBinding": {"elementId": "r1"}, "endBinding": {"elementId": "unknown"},
        },
    ]
    result = pai.summarize_excalidraw_elements(elements)
    assert result == "Labeled shapes drawn: Client."


# ---------------------------------------------------------------------------
# Grading-prompt construction — mock the LLM call the same way the
# integration suite's _FakeDesignChat does, but capture the prompt text AND
# file_contents (image) sent so we can assert on both.
# ---------------------------------------------------------------------------
class _CapturingChat:
    """Records the last prompt text/file_contents sent, and returns a canned
    rubric response shaped to whatever rubric the calling test's problem
    declares."""
    last_prompt = None
    last_file_contents = None
    next_response = None

    def __init__(self, *args, **kwargs):
        pass

    def with_model(self, *args, **kwargs):
        return self

    async def send_message(self, msg):
        _CapturingChat.last_prompt = msg.text
        _CapturingChat.last_file_contents = msg.file_contents
        return _CapturingChat.next_response


@pytest.fixture(autouse=True)
def _capture_llm(monkeypatch):
    monkeypatch.setattr(pai, "LlmChat", _CapturingChat)


def _canned_response(criteria_names_and_max):
    payload = {
        "criteria": [
            {"criterion": name, "score": max_score, "max_score": max_score, "feedback": f"Good use of {name}."}
            for name, max_score in criteria_names_and_max
        ],
        "overall_feedback": "Solid.",
    }
    _CapturingChat.next_response = json.dumps(payload)


PLAIN_PROBLEM = {
    "title": "Design a Widget Service",
    "description": "Design something.",
    "rubric": [
        {"criterion": "Scalability", "max_score": 10, "description": "Scales."},
        {"criterion": "Clarity", "max_score": 10, "description": "Is clear."},
    ],
}

HLD_PROBLEM_WITH_DIAGRAM_CALC = {
    "title": "Design a Widget Service",
    "description": "Design something at scale.",
    "supports_diagram": True,
    "supports_calculation": True,
    "rubric": [
        {"criterion": "Scalability", "max_score": 10, "description": "Scales."},
        {"criterion": "Diagram shows caching", "max_score": 10, "applies_to": "diagram", "description": "Cache is drawn."},
        {"criterion": "Realistic estimate", "max_score": 10, "applies_to": "calculation", "description": "Has a real number."},
    ],
}

# 1x1 transparent PNG, base64 — same fixture pattern llm_client.py's own
# self-check (`demo()`) uses for a minimal real image payload.
TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nG"
    "NgYGAAAAAEAAH2FzhVAAAAAElFTkSuQmCC"
)


async def test_grading_prompt_and_image_included_when_diagram_present():
    _canned_response([("Scalability", 10), ("Diagram shows caching", 10), ("Realistic estimate", 10)])
    await pai.grade_design_submission(
        HLD_PROBLEM_WITH_DIAGRAM_CALC,
        answer_text="I would add a cache.",
        diagram_image_base64=TINY_PNG_B64,
        diagram_text_hint="Labeled shapes drawn: Client, Cache. Arrows connecting labeled shapes: Client -> Cache.",
        calculation_text="500e6 / 86400 = ~5787 req/sec",
    )
    prompt = _CapturingChat.last_prompt
    assert "Labeled shapes drawn: Client, Cache." in prompt
    assert "500e6 / 86400 = ~5787 req/sec" in prompt
    assert "hand-drawn architecture diagram is attached" in prompt
    assert "back-of-envelope calculations" in prompt.lower()
    # The diagram/calculation-tagged criteria are annotated in the rubric text
    # so the LLM is told what each one judges.
    assert "evaluate against the DIAGRAM" in prompt
    assert "evaluate against the CALCULATIONS" in prompt
    # The actual image is threaded through as a real image, not just described.
    file_contents = _CapturingChat.last_file_contents
    assert file_contents is not None and len(file_contents) == 1
    assert file_contents[0].image_base64 == TINY_PNG_B64


async def test_grading_prompt_omits_diagram_and_calculation_sections_when_absent():
    _canned_response([("Scalability", 10), ("Clarity", 10)])
    await pai.grade_design_submission(PLAIN_PROBLEM, answer_text="A plain design answer.")
    prompt = _CapturingChat.last_prompt
    assert "hand-drawn architecture diagram" not in prompt
    assert "back-of-envelope calculations" not in prompt.lower()
    assert "evaluate against" not in prompt
    assert _CapturingChat.last_file_contents is None


async def test_grading_works_with_only_diagram_text_hint_and_no_image():
    """The image is the primary signal, but nothing here should require it —
    e.g. a future caller that only has the structured hint (or an image that
    failed to render client-side) still produces a sensible prompt."""
    _canned_response([("Scalability", 10), ("Diagram shows caching", 10), ("Realistic estimate", 10)])
    await pai.grade_design_submission(
        HLD_PROBLEM_WITH_DIAGRAM_CALC,
        answer_text="I would add a cache.",
        diagram_text_hint="Labeled shapes drawn: Client, Cache.",
    )
    prompt = _CapturingChat.last_prompt
    assert "Labeled shapes drawn: Client, Cache." in prompt
    assert "hand-drawn architecture diagram is attached" not in prompt
    assert _CapturingChat.last_file_contents is None


# ---------------------------------------------------------------------------
# Backward compatibility — the exact scenario the task calls out: a design
# problem with NO supports_diagram/supports_calculation and a rubric with no
# `applies_to` anywhere must grade with a byte-identical prompt shape to
# before this feature existed (no new sections, no per-criterion annotation,
# no image).
# ---------------------------------------------------------------------------
async def test_backward_compatible_grading_prompt_for_a_problem_without_new_fields():
    payload = {
        "criteria": [
            {"criterion": "Scalability", "score": 8, "max_score": 10, "feedback": "Good."},
            {"criterion": "Clarity", "score": 9, "max_score": 10, "feedback": "Clear."},
        ],
        "overall_feedback": "Solid.",
    }
    _CapturingChat.next_response = json.dumps(payload)
    result = await pai.grade_design_submission(PLAIN_PROBLEM, "A plain design answer with no diagram or calc.")

    prompt = _CapturingChat.last_prompt
    expected_rubric_text = (
        '- "Scalability" (max 10): Scales.\n'
        '- "Clarity" (max 10): Is clear.'
    )
    assert expected_rubric_text in prompt
    # Exactly the two original sections (prompt + rubric + answer) joined with
    # the same separator as before — no extra diagram/calc section appended.
    assert prompt.count("Candidate's") == 1  # only "Candidate's written answer:", never diagram/calc labels
    assert _CapturingChat.last_file_contents is None
    assert result["total_score"] == 17
    assert result["max_total_score"] == 20
    assert result["pct"] == 85
