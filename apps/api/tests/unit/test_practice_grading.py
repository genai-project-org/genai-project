"""Unit tests for the SQL and MCQ grading engines added to
services/practice_service.py — pure grading logic, no HTTP layer, no Piston,
no LLM. (Design grading is exercised at the integration level in
tests/integration/test_practice_paths_flows.py since it needs the LLM client
mocked at a call-site the same way Piston is mocked for contest flows.)
"""
import pytest

from services import practice_service as ps

pytestmark = pytest.mark.anyio


# ---------------------------------------------------------------------------
# SQL grading — order-sensitive vs order-insensitive, error handling, the
# SELECT-only guard.
# ---------------------------------------------------------------------------
async def test_sql_correct_query_passes_order_insensitive_problem():
    problem = ps.CUSTOMERS_WHO_NEVER_ORDER_PROBLEM
    result = await ps.run_sql_submission(
        problem,
        "SELECT c.name AS Customers FROM Customers c LEFT JOIN Orders o ON c.id = o.customerId WHERE o.id IS NULL;",
    )
    assert result["all_passed"] is True
    assert result["total"] == 1
    assert result["passed_count"] == 1


async def test_sql_reordered_rows_still_pass_when_problem_is_order_insensitive():
    problem = ps.CUSTOMERS_WHO_NEVER_ORDER_PROBLEM
    assert problem["order_sensitive"] is False
    reordered = (
        "SELECT c.name AS Customers FROM Customers c LEFT JOIN Orders o ON c.id = o.customerId "
        "WHERE o.id IS NULL ORDER BY c.name DESC;"
    )
    result = await ps.run_sql_submission(problem, reordered)
    assert result["all_passed"] is True


async def test_sql_wrong_query_fails():
    problem = ps.CUSTOMERS_WHO_NEVER_ORDER_PROBLEM
    result = await ps.run_sql_submission(problem, "SELECT c.name FROM Customers c;")  # misses the anti-join entirely
    assert result["all_passed"] is False
    assert result["results"][0]["error"] is None  # ran fine, just the wrong rows


async def test_sql_order_sensitive_problem_rejects_right_rows_wrong_order():
    problem = ps.TOP_THREE_PAID_EMPLOYEES_PROBLEM
    assert problem["order_sensitive"] is True
    correct = "SELECT name FROM Employee ORDER BY salary DESC LIMIT 3;"
    same_rows_wrong_order = "SELECT name FROM Employee WHERE salary IN (900, 700, 500) ORDER BY salary ASC;"

    ok = await ps.run_sql_submission(problem, correct)
    bad_order = await ps.run_sql_submission(problem, same_rows_wrong_order)

    assert ok["all_passed"] is True
    assert bad_order["all_passed"] is False  # same 3 rows, wrong order — must fail


async def test_sql_order_sensitive_problem_accepts_correct_order():
    problem = ps.TOP_THREE_PAID_EMPLOYEES_PROBLEM
    result = await ps.run_sql_submission(problem, "SELECT name FROM Employee ORDER BY salary DESC LIMIT 3;")
    assert result["all_passed"] is True
    assert result["results"][0]["actual_rows"] == result["results"][0]["expected_rows"]


async def test_sql_invalid_syntax_reports_an_error_not_an_exception():
    problem = ps.CUSTOMERS_WHO_NEVER_ORDER_PROBLEM
    result = await ps.run_sql_submission(problem, "SELECT nonexistent_column FROM Customers;")
    assert result["all_passed"] is False
    assert "no such column" in result["results"][0]["error"]


async def test_sql_non_select_statement_is_rejected_before_execution():
    problem = ps.CUSTOMERS_WHO_NEVER_ORDER_PROBLEM
    result = await ps.run_sql_submission(problem, "DROP TABLE Customers;")
    assert result["all_passed"] is False
    assert "Only SELECT queries" in result["results"][0]["error"]


def test_get_sql_table_preview_reflects_seeded_schema():
    tables = ps.get_sql_table_preview(ps.COMBINE_TWO_TABLES_PROBLEM["schema_sql"])
    names = {t["name"] for t in tables}
    assert names == {"Person", "Address"}
    person = next(t for t in tables if t["name"] == "Person")
    assert "first_name" in person["columns"]
    assert len(person["rows"]) == 3


async def test_every_seeded_sql_problems_solution_query_actually_runs():
    """Guards against an authoring typo in schema_sql/solution_query for any
    of the hand-written SQL problems — every one of them must actually be
    gradeable, not just the ones exercised individually above."""
    for problem in ps.SQL_PROBLEMS:
        result = await ps.run_sql_submission(problem, problem["solution_query"])
        assert result["all_passed"] is True, f"{problem['_id']}'s own solution_query did not pass its own grading"


# ---------------------------------------------------------------------------
# MCQ grading — trivial equality, but still worth locking down the contract.
# ---------------------------------------------------------------------------
def test_mcq_correct_selection_passes():
    problem = ps.BLOOD_RELATION_PROBLEM
    result = ps.grade_mcq(problem, problem["correct_option_id"])
    assert result["passed"] is True
    assert result["correct_option_id"] == problem["correct_option_id"]


def test_mcq_wrong_selection_fails_and_still_reveals_correct_answer():
    problem = ps.BLOOD_RELATION_PROBLEM
    wrong_id = next(o["id"] for o in problem["options"] if o["id"] != problem["correct_option_id"])
    result = ps.grade_mcq(problem, wrong_id)
    assert result["passed"] is False
    assert result["correct_option_id"] == problem["correct_option_id"]


def test_every_seeded_mcq_problem_has_exactly_one_correct_option_among_its_options():
    """Authoring guard: every Logical Reasoning / Computer Networks problem's
    `correct_option_id` must actually refer to one of its own `options`."""
    for problem in ps.LOGICAL_REASONING_PROBLEMS + ps.COMPUTER_NETWORKS_PROBLEMS:
        option_ids = {o["id"] for o in problem["options"]}
        assert problem["correct_option_id"] in option_ids, problem["_id"]


# ---------------------------------------------------------------------------
# Roadmap `path`/`step` ordering — the new top-level grouping.
# ---------------------------------------------------------------------------
async def test_seed_problems_backfills_path_and_question_type_on_pre_existing_docs():
    """Simulates the exact scenario the backfill exists for: a problem
    already in the DB from before `path`/`question_type` existed (the
    original migration state), with everything else already backfilled."""
    await ps.practice_problems_col.insert_one({
        "_id": "two-sum",
        "title": "Two Sum",
        "difficulty": "Easy",
        "tags": ["array"],
        "step": "Arrays & Hashing",
        "order": 1,
        "companies": [],
        "params": [{"name": "nums", "type": "int_array"}, {"name": "target", "type": "int"}],
        "output_type": "int_array_sorted",
        # `path`/`question_type` deliberately absent — pre-migration shape.
    })
    await ps.seed_problems()
    doc = await ps.practice_problems_col.find_one({"_id": "two-sum"})
    assert doc["path"] == "DSA"
    assert doc["question_type"] == "code"
    # Untouched fields prove this was a backfill, not an overwrite.
    assert doc["title"] == "Two Sum"


async def test_list_roadmap_groups_by_path_then_step():
    await ps.seed_problems()
    items = await ps.list_roadmap()
    paths_seen = [item["path"] for item in items]
    # DSA items must all come before SQL items, which come before Logical
    # Reasoning, etc. — i.e. paths form contiguous blocks in PATH_ORDER.
    seen_order = []
    for p in paths_seen:
        if not seen_order or seen_order[-1] != p:
            seen_order.append(p)
    assert seen_order == sorted(seen_order, key=lambda p: ps.PATH_ORDER.get(p, 999))
    assert set(paths_seen) == {"DSA", "SQL", "Logical Reasoning", "Computer Networks", "System Design"}
