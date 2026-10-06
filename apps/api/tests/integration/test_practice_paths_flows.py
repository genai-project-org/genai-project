"""Integration tests for the four practice "paths" added on top of the
original DSA/code problems: SQL, Logical Reasoning + Computer Networks (both
MCQ), and System Design (LLD/HLD). Full HTTP surface via routers/practice_routes.py.

Piston is mocked the same way tests/integration/test_contest_flows.py already
does for contest flows (a real local subprocess runs the harness-wrapped
source — genuine Python semantics decide pass/fail, no container/network).
SQL grading needs no such mock — services.practice_service.run_sql_submission
uses the real stdlib `sqlite3` module directly, so these tests exercise real
SQL execution end to end.

The LLM call inside AI design grading (services.practice_ai_service.
grade_design_submission) is mocked at the same call-site level: `LlmChat` is
monkeypatched to a fake whose `send_message` returns a canned JSON rubric
response, so these tests stay hermetic (no real network/API key needed) while
still exercising the real prompt-building/JSON-parsing/scoring code.
"""
import asyncio
import json
import subprocess
import sys

import pytest

from services import practice_service, practice_ai_service, pricing_engine

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Fake Piston — identical pattern to test_contest_flows.py.
# ---------------------------------------------------------------------------
class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def post(self, _url, json):
        source = json["files"][0]["content"]
        stdin = json.get("stdin", "")
        try:
            proc = subprocess.run(
                [sys.executable, "-c", source], input=stdin,
                capture_output=True, text=True, timeout=10,
            )
            run = {"stdout": proc.stdout, "stderr": proc.stderr, "code": proc.returncode, "signal": None}
        except subprocess.TimeoutExpired:
            run = {"stdout": "", "stderr": "timeout", "code": None, "signal": "SIGKILL"}
        return _FakeResponse({"run": run})


@pytest.fixture(autouse=True)
def _fake_piston(monkeypatch):
    monkeypatch.setattr(practice_service.httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(**kw))


@pytest.fixture(autouse=True)
def _seed_practice_problems():
    asyncio.run(practice_service.seed_problems())


@pytest.fixture(autouse=True)
def _seed_pricing():
    """The `client` fixture deliberately skips the app's startup event (see
    conftest.py) — which is what normally seeds `pricing_col` via
    pricing_engine.seed_defaults() — so credit-gated assertions here need it
    seeded explicitly, same as any other test exercising real pricing."""
    asyncio.run(pricing_engine.seed_defaults())


# ---------------------------------------------------------------------------
# Fake LLM for design grading — returns a caller-controlled rubric response,
# same call-site-level mocking spirit as the Piston fake above.
# ---------------------------------------------------------------------------
class _FakeDesignChat:
    """Stands in for services.llm_client.LlmChat. `_next_response` is set on
    the CLASS (not per-instance) since grade_design_submission constructs a
    fresh LlmChat() itself — a test sets the class attribute right before
    the call it wants to control."""
    _next_response = None

    def __init__(self, *args, **kwargs):
        pass

    def with_model(self, *args, **kwargs):
        return self

    async def send_message(self, *args, **kwargs):
        return _FakeDesignChat._next_response


def _set_fake_design_response(criteria_scores, overall_feedback="Solid overall, could go deeper on failure modes."):
    """criteria_scores: list of (criterion_name, score, max_score)."""
    payload = {
        "criteria": [
            {"criterion": name, "score": score, "max_score": max_score, "feedback": f"Feedback for {name}."}
            for name, score, max_score in criteria_scores
        ],
        "overall_feedback": overall_feedback,
    }
    _FakeDesignChat._next_response = json.dumps(payload)


@pytest.fixture(autouse=True)
def _fake_llm(monkeypatch):
    monkeypatch.setattr(practice_ai_service, "LlmChat", _FakeDesignChat)


# ---------------------------------------------------------------------------
# SQL path
# ---------------------------------------------------------------------------
SQL_CORRECT_QUERY = (
    "SELECT c.name AS Customers FROM Customers c LEFT JOIN Orders o ON c.id = o.customerId WHERE o.id IS NULL;"
)
SQL_WRONG_QUERY = "SELECT c.name AS Customers FROM Customers c;"  # misses the anti-join


def test_sql_run_is_free_and_not_recorded(client, auth_user):
    _user, _tokens, headers = auth_user
    resp = client.post(
        "/api/practice/problems/sql-customers-who-never-order/run",
        json={"code": SQL_CORRECT_QUERY, "language": "sql"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["all_passed"] is True
    assert body["results"][0]["error"] is None

    subs = client.get("/api/practice/problems/sql-customers-who-never-order/submissions", headers=headers)
    assert subs.json()["items"] == []  # /run never records anything


def test_sql_correct_submission_passes_and_charges_the_same_as_code_submit(client, auth_user):
    _user, _tokens, headers = auth_user
    balance_before = client.get("/api/wallet/", headers=headers).json()["total"]

    resp = client.post(
        "/api/practice/problems/sql-customers-who-never-order/submit",
        json={"code": SQL_CORRECT_QUERY, "language": "sql"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["all_passed"] is True
    assert body["credits_used"] == 2  # same as PRICE_KEY_SUBMIT for code problems

    balance_after = client.get("/api/wallet/", headers=headers).json()["total"]
    assert balance_after == balance_before - 2


def test_sql_wrong_submission_fails_but_still_charges_and_records(client, auth_user):
    _user, _tokens, headers = auth_user
    resp = client.post(
        "/api/practice/problems/sql-customers-who-never-order/submit",
        json={"code": SQL_WRONG_QUERY, "language": "sql"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["all_passed"] is False
    assert body["credits_used"] == 2

    subs = client.get("/api/practice/problems/sql-customers-who-never-order/submissions", headers=headers)
    assert len(subs.json()["items"]) == 1
    assert subs.json()["items"][0]["all_passed"] is False


def test_sql_order_sensitive_problem_rejects_a_correct_but_wrongly_ordered_submission(client, auth_user):
    _user, _tokens, headers = auth_user
    right_rows_wrong_order = "SELECT name FROM Employee WHERE salary IN (900, 700, 500) ORDER BY salary ASC;"
    resp = client.post(
        "/api/practice/problems/sql-top-three-paid-employees/submit",
        json={"code": right_rows_wrong_order, "language": "sql"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["all_passed"] is False

    correct_order = "SELECT name FROM Employee ORDER BY salary DESC LIMIT 3;"
    resp2 = client.post(
        "/api/practice/problems/sql-top-three-paid-employees/submit",
        json={"code": correct_order, "language": "sql"},
        headers=headers,
    )
    assert resp2.json()["all_passed"] is True


def test_sql_problem_detail_exposes_table_preview_but_not_the_solution_query(client, auth_user):
    _user, _tokens, headers = auth_user
    resp = client.get("/api/practice/problems/sql-customers-who-never-order", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["question_type"] == "sql"
    table_names = {t["name"] for t in body["tables"]}
    assert table_names == {"Customers", "Orders"}
    assert "solution_query" not in body
    assert "schema_sql" not in body


# ---------------------------------------------------------------------------
# MCQ path (Logical Reasoning + Computer Networks share the same mechanism).
# ---------------------------------------------------------------------------
def test_mcq_problem_detail_never_exposes_the_correct_option(client, auth_user):
    _user, _tokens, headers = auth_user
    resp = client.get("/api/practice/problems/lr-blood-relation-1", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["question_type"] == "mcq"
    assert "correct_option_id" not in body
    assert {o["id"] for o in body["options"]} == {"a", "b", "c", "d"}


def test_mcq_correct_answer_passes_and_is_free(client, auth_user):
    _user, _tokens, headers = auth_user
    balance_before = client.get("/api/wallet/", headers=headers).json()["total"]

    resp = client.post(
        "/api/practice/problems/lr-blood-relation-1/submit-mcq",
        json={"selected_option_id": "a"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["passed"] is True
    assert body["correct_option_id"] == "a"
    assert body["credits_used"] == 0

    balance_after = client.get("/api/wallet/", headers=headers).json()["total"]
    assert balance_after == balance_before  # genuinely free, not merely cheap


def test_mcq_wrong_answer_fails_and_still_reveals_correct_option(client, auth_user):
    _user, _tokens, headers = auth_user
    resp = client.post(
        "/api/practice/problems/lr-blood-relation-1/submit-mcq",
        json={"selected_option_id": "b"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["passed"] is False
    assert body["correct_option_id"] == "a"
    assert body["credits_used"] == 0


def test_mcq_unknown_option_id_is_rejected(client, auth_user):
    _user, _tokens, headers = auth_user
    resp = client.post(
        "/api/practice/problems/lr-blood-relation-1/submit-mcq",
        json={"selected_option_id": "not-a-real-option"},
        headers=headers,
    )
    assert resp.status_code == 400


def test_computer_networks_mcq_uses_the_same_mechanism(client, auth_user):
    _user, _tokens, headers = auth_user
    resp = client.post(
        "/api/practice/problems/cn-https-port-1/submit-mcq",
        json={"selected_option_id": "d"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["passed"] is True


def test_code_endpoints_reject_an_mcq_problem_id(client, auth_user):
    _user, _tokens, headers = auth_user
    resp = client.post(
        "/api/practice/problems/lr-blood-relation-1/submit",
        json={"code": "irrelevant", "language": "python"},
        headers=headers,
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Design path (LLD/HLD) — LLM mocked, real prompt/scoring/threshold logic.
# ---------------------------------------------------------------------------
def test_design_submission_returns_real_structured_per_criterion_feedback(client, auth_user):
    _user, _tokens, headers = auth_user
    # 8 criteria, 10 each on sd-url-shortener (5 answer + 2 diagram + 1
    # calculation, since it now supports_diagram/supports_calculation) — a
    # strong-but-imperfect answer, submitted with no diagram/calc content
    # (this test only exercises the plain-answer path; the diagram/calc
    # content-consumption path is covered separately below and via the
    # real end-to-end Anthropic verification).
    _set_fake_design_response([
        ("Scalability", 9, 10),
        ("Data model correctness", 8, 10),
        ("Core algorithm (short-code generation)", 8, 10),
        ("Edge cases", 6, 10),
        ("Clarity of API surface", 9, 10),
        ("Diagram shows load-balancing / horizontal scaling", 8, 10),
        ("Diagram shows a caching layer", 8, 10),
        ("Realistic scale estimate", 8, 10),
    ], overall_feedback="Strong caching/data-model discussion; add more on alias collision handling.")

    balance_before = client.get("/api/wallet/", headers=headers).json()["total"]

    resp = client.post(
        "/api/practice/problems/sd-url-shortener/submit-design",
        json={"answer_text": "I would use a base62-encoded counter for short codes, Redis for caching reads, DynamoDB for the short_code->url mapping, and check custom aliases for uniqueness before insert."},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert len(body["criteria"]) == 8
    assert body["total_score"] == 64
    assert body["max_total_score"] == 80
    assert body["pct"] == 80
    assert body["overall_feedback"]  # not empty — real structured feedback, not a blank response
    assert all(c["feedback"] for c in body["criteria"])
    assert body["all_passed"] is True  # 80% >= 70% threshold
    assert body["credits_used"] == 15

    balance_after = client.get("/api/wallet/", headers=headers).json()["total"]
    assert balance_after == balance_before - 15


def test_design_submission_below_threshold_is_not_marked_solved(client, auth_user):
    _user, _tokens, headers = auth_user
    _set_fake_design_response([
        ("Scalability", 3, 10),
        ("Data model correctness", 3, 10),
        ("Core algorithm (short-code generation)", 3, 10),
        ("Edge cases", 2, 10),
        ("Clarity of API surface", 3, 10),
        ("Diagram shows load-balancing / horizontal scaling", 2, 10),
        ("Diagram shows a caching layer", 2, 10),
        ("Realistic scale estimate", 2, 10),
    ], overall_feedback="Too vague — no concrete data model or algorithm discussed.")

    resp = client.post(
        "/api/practice/problems/sd-url-shortener/submit-design",
        json={"answer_text": "Just use a database and a cache I guess."},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["pct"] == 25
    assert body["all_passed"] is False


# ---------------------------------------------------------------------------
# Diagram / calculation opt-in (HLD-specific) — additive on top of the plain
# design-grading path above.
# ---------------------------------------------------------------------------
def test_design_problem_detail_exposes_supports_diagram_and_calculation_flags(client, auth_user):
    _user, _tokens, headers = auth_user
    hld = client.get("/api/practice/problems/sd-url-shortener", headers=headers).json()
    assert hld["supports_diagram"] is True
    assert hld["supports_calculation"] is True
    assert any(c.get("applies_to") == "diagram" for c in hld["rubric"])
    assert any(c.get("applies_to") == "calculation" for c in hld["rubric"])

    lld = client.get("/api/practice/problems/sd-parking-lot", headers=headers).json()
    assert lld["supports_diagram"] is False
    assert lld["supports_calculation"] is False
    assert all(c.get("applies_to", "answer") == "answer" for c in lld["rubric"])


TINY_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nG"
    "NgYGAAAAAEAAH2FzhVAAAAAElFTkSuQmCC"
)


def test_design_submission_with_diagram_and_calculation_reaches_the_grading_prompt(client, auth_user, monkeypatch):
    """Doesn't assert on LLM output content (that's the fake's job, not real
    grading) — proves the ROUTE actually threads a submitted diagram image
    (plus a best-effort structured hint derived from its raw elements) and
    calculation text through to grade_design_submission, for a problem that
    supports them."""
    _user, _tokens, headers = auth_user
    _set_fake_design_response([("Scalability", 9, 10)] * 8)

    captured = {}
    from routers import practice_routes as pr

    async def _fake_grade(problem, answer_text, diagram_image_base64=None, diagram_text_hint=None, calculation_text=None):
        captured["diagram_image_base64"] = diagram_image_base64
        captured["diagram_text_hint"] = diagram_text_hint
        captured["calculation_text"] = calculation_text
        return {"criteria": [], "overall_feedback": "ok", "total_score": 0, "max_total_score": 1, "pct": 100}

    monkeypatch.setattr(pr, "grade_design_submission", _fake_grade)

    diagram = {
        "image_base64": TINY_PNG_B64,
        "elements": [
            {"id": "r1", "type": "rectangle", "isDeleted": False},
            {"id": "t1", "type": "text", "text": "Client", "containerId": "r1", "isDeleted": False},
        ],
    }
    resp = client.post(
        "/api/practice/problems/sd-url-shortener/submit-design",
        json={"answer_text": "See diagram.", "diagram": diagram, "calculation_text": "100e6 / 86400 = ~1157 writes/sec"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert captured["diagram_image_base64"] == TINY_PNG_B64
    assert captured["diagram_text_hint"] == "Labeled shapes drawn: Client."
    assert captured["calculation_text"] == "100e6 / 86400 = ~1157 writes/sec"


def test_design_submission_diagram_ignored_for_a_problem_that_does_not_support_it(client, auth_user, monkeypatch):
    """sd-parking-lot (LLD) never set supports_diagram/supports_calculation
    — a diagram sent anyway must be dropped before it ever reaches grading,
    proving the opt-in is enforced server-side, not just by the frontend
    not offering the UI."""
    _user, _tokens, headers = auth_user
    _set_fake_design_response([("Class design & OOP principles", 9, 10)] * 5)

    captured = {}
    from routers import practice_routes as pr

    async def _fake_grade(problem, answer_text, diagram_image_base64=None, diagram_text_hint=None, calculation_text=None):
        captured["diagram_image_base64"] = diagram_image_base64
        captured["diagram_text_hint"] = diagram_text_hint
        captured["calculation_text"] = calculation_text
        return {"criteria": [], "overall_feedback": "ok", "total_score": 0, "max_total_score": 1, "pct": 100}

    monkeypatch.setattr(pr, "grade_design_submission", _fake_grade)

    resp = client.post(
        "/api/practice/problems/sd-parking-lot/submit-design",
        json={
            "answer_text": "ParkingLot, Level, Spot, Vehicle, Ticket classes.",
            "diagram": {"image_base64": TINY_PNG_B64, "elements": []},
            "calculation_text": "should also be ignored",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert captured["diagram_image_base64"] is None
    assert captured["diagram_text_hint"] is None
    assert captured["calculation_text"] is None


def test_design_problem_detail_exposes_rubric(client, auth_user):
    _user, _tokens, headers = auth_user
    resp = client.get("/api/practice/problems/sd-parking-lot", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["question_type"] == "design"
    assert len(body["rubric"]) == 5
    assert all("criterion" in c and "max_score" in c for c in body["rubric"])


def test_code_endpoints_reject_a_design_problem_id(client, auth_user):
    _user, _tokens, headers = auth_user
    resp = client.post(
        "/api/practice/problems/sd-parking-lot/run",
        json={"code": "irrelevant", "language": "python"},
        headers=headers,
    )
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Roadmap / progress — path-level grouping across all five paths.
# ---------------------------------------------------------------------------
def test_roadmap_includes_all_five_paths(client, auth_user):
    _user, _tokens, headers = auth_user
    resp = client.get("/api/practice/roadmap", headers=headers)
    assert resp.status_code == 200, resp.text
    items = resp.json()["items"]
    paths = {item["path"] for item in items}
    assert paths == {"DSA", "SQL", "Logical Reasoning", "Computer Networks", "System Design"}


def test_progress_is_grouped_by_path_with_nested_steps(client, auth_user):
    _user, _tokens, headers = auth_user
    resp = client.get("/api/practice/progress", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "paths" in body
    path_names = {p["path"] for p in body["paths"]}
    assert path_names == {"DSA", "SQL", "Logical Reasoning", "Computer Networks", "System Design"}
    sql_path = next(p for p in body["paths"] if p["path"] == "SQL")
    assert sql_path["total"] == 7
    assert len(sql_path["steps"]) > 0


def test_solving_an_mcq_problem_counts_toward_roadmap_and_progress(client, auth_user):
    _user, _tokens, headers = auth_user
    client.post(
        "/api/practice/problems/lr-blood-relation-1/submit-mcq",
        json={"selected_option_id": "a"},
        headers=headers,
    )
    roadmap = client.get("/api/practice/roadmap", headers=headers).json()["items"]
    row = next(i for i in roadmap if i["id"] == "lr-blood-relation-1")
    assert row["solved"] is True

    progress = client.get("/api/practice/progress", headers=headers).json()
    lr_path = next(p for p in progress["paths"] if p["path"] == "Logical Reasoning")
    assert lr_path["solved"] == 1
