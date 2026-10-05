"""Bulk-seed LLM-generated practice problems into `practice_problems`.

Explicit, one-off exception to the "no LLM-generated problems" rule that
governs `practice_service.ALL_PROBLEMS` (see that file's seed-data docstring)
— authorized for this script only, by direct user instruction, precisely
because hand-authoring thousands of problems isn't feasible. Every document
this script inserts is tagged `"source": "generated"` so it can be told apart
from the 37 hand-authored problems (which are never touched by this script).

Correctness safeguard, mirroring `practice_ai_service.generate_variant`'s
existing philosophy ("never trust an LLM's own stated expected output"):

  * code   — LLM proposes a reference Python solution; we EXECUTE it via the
             real Piston instance for every generated test input and use
             that as ground truth. A crash/non-JSON output discards the
             attempt. Non-Python starter stubs are plain unimplemented
             signatures (not executed) — a real, accepted residual gap,
             documented in the final report.
  * sql    — LLM proposes schema_sql + solution_query; we EXECUTE the query
             against the schema via sqlite3 (exactly what run_sql_submission
             does at grading time) and discard on any execution error. SQL
             problems store no `test_cases` — grading recomputes expected
             rows fresh every time, same as the hand-authored ones.
  * mcq    — no execution-based ground truth exists. Mitigated with a SECOND,
             independent LLM call that re-solves the question from the
             question+options alone (not told the "correct" answer) and is
             discarded on disagreement. Weaker than execution — reported as
             such.
  * design — no single correct answer to check. Mitigated with a rubric
             self-review pass (a second LLM call checking each criterion is
             specific and gradeable), not a correctness check.

Run examples:
    .venv/bin/python scripts/seed_generated_practice.py --path DSA --target 150 --concurrency 6
    .venv/bin/python scripts/seed_generated_practice.py --all --target 200 --concurrency 6 --time-budget-min 90

Idempotent-ish: every inserted `_id` is content-hashed + a short random
suffix, so re-running never collides with a prior run's docs; nothing here
ever touches an existing document.
"""
import argparse
import asyncio
import json
import logging
import os
import random
import re
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from anthropic import AsyncAnthropic  # noqa: E402

from db import db, now_iso  # noqa: E402
from services.practice_service import (  # noqa: E402
    practice_problems_col,
    _py_harness,
    _piston_execute,
    _sql_execute,
    PistonUnavailableError,
    LANGUAGE_RUNTIMES,
)
from services.practice_ai_service import _extract_json  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("seed_generated_practice")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GEN_MODEL = "claude-sonnet-5"       # needs to actually reason about correctness
# Same exact dated ID practice_ai_service.FEEDBACK_MODEL already uses successfully in this
# codebase/account — safer than a bare "claude-haiku-4-5" that hasn't been confirmed to resolve here.
VERIFY_MODEL = "claude-haiku-4-5-20251001"  # independent-check / self-review passes — cheaper is fine here
GEN_MAX_TOKENS = 16000              # confirmed minimum for claude-sonnet-5 — see practice_ai_service.py
VERIFY_MAX_TOKENS = 2000

_client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None

# ---------------------------------------------------------------------------
# Cost / call tracking — printed in the final summary, not just vibes.
# ---------------------------------------------------------------------------
@dataclass
class CostTracker:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    by_model: Dict[str, Dict[str, int]] = field(default_factory=dict)

    def add(self, model: str, usage) -> None:
        self.calls += 1
        it, ot = usage.input_tokens, usage.output_tokens
        self.input_tokens += it
        self.output_tokens += ot
        m = self.by_model.setdefault(model, {"calls": 0, "in": 0, "out": 0})
        m["calls"] += 1
        m["in"] += it
        m["out"] += ot

    PRICES = {  # $ per 1M tokens (in, out) — confirmed current at generation time
        "claude-sonnet-5": (2.00, 10.00),
        "claude-haiku-4-5-20251001": (1.00, 5.00),
    }

    def usd(self) -> float:
        total = 0.0
        for model, m in self.by_model.items():
            pin, pout = self.PRICES.get(model, (0.0, 0.0))
            total += m["in"] / 1e6 * pin + m["out"] / 1e6 * pout
        return total

    def summary(self) -> str:
        lines = [f"Total calls: {self.calls}, ~${self.usd():.4f}"]
        for model, m in self.by_model.items():
            pin, pout = self.PRICES.get(model, (0.0, 0.0))
            cost = m["in"] / 1e6 * pin + m["out"] / 1e6 * pout
            lines.append(f"  {model}: {m['calls']} calls, {m['in']}+{m['out']} tok, ~${cost:.4f}")
        return "\n".join(lines)


COST = CostTracker()


async def call_llm(system: str, user_text: str, model: str, max_tokens: int) -> str:
    assert _client is not None, "ANTHROPIC_API_KEY not set"
    resp = await _client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user_text}],
    )
    COST.add(model, resp.usage)
    return "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
@dataclass
class Stats:
    attempted: int = 0
    inserted: int = 0
    discarded: Dict[str, int] = field(default_factory=dict)

    def discard(self, reason: str) -> None:
        self.discarded[reason] = self.discarded.get(reason, 0) + 1

    def as_dict(self) -> dict:
        return {"attempted": self.attempted, "inserted": self.inserted, "discarded": dict(self.discarded)}


STATS: Dict[str, Stats] = {}


def stats_for(path: str) -> Stats:
    return STATS.setdefault(path, Stats())


# ---------------------------------------------------------------------------
# DSA (code) — step catalog with encoding guidance so generated problems stay
# inside what the EXISTING generic harness (_py_harness / build_harness) can
# grade: params restricted to {int, int_array, string}, output_type restricted
# to {int, bool, int_array_sorted, int_array_ordered}. Trees/graphs/linked
# lists are still valid TOPICS — just expressed via array encodings (documented
# per-step below), the same way LeetCode itself expresses tree/list input.
# ---------------------------------------------------------------------------
DSA_STEPS = {
    "Arrays & Hashing": "prefix sums, frequency counting with hash maps, in-place array rewrites, grouping by a derived key",
    "Two Pointers": "opposite-direction pointers on sorted input, same-direction fast/slow pointers, array partitioning",
    "Binary Search": "search on a sorted array, search on the answer (binary search over a value range), first/last occurrence, rotated sorted array",
    "Sliding Window": "fixed-size window aggregates, variable-size window for longest/shortest substring or subarray meeting a condition",
    "Stacks & Queues": "monotonic stack (next greater/smaller element), valid-bracket-sequence style validation, queue simulation via two stacks",
    "Linked Lists": (
        "Encode the linked list as a flat `int_array` of node values (in list order) — the reference solution "
        "builds an actual singly-linked list from that array internally, operates on it, then converts the "
        "result back to a flat array (output_type int_array_ordered) or a scalar (int/bool). For cycle problems, "
        "pass an extra `int` param `pos` = the 0-indexed position the tail connects back to, or -1 for no cycle."
    ),
    "Trees": (
        "Encode a binary tree as a flat `int_array` in level-order (BFS) where the sentinel value -1 means "
        "'no node here' — assume all real node values are >= 0 so -1 is unambiguous. The reference solution "
        "reconstructs an actual tree from that array internally. Output must reduce to int/bool/int_array_ordered "
        "(e.g. max depth, diameter, sum, whether it's a valid BST, whether two encoded trees are identical) — "
        "never a nested structure."
    ),
    "Heaps": "kth largest/smallest element in an array, top-k frequent elements, whether a stream (given as an array) is always retrievable in sorted order via a heap — output must be a scalar or flat ordered array",
    "Backtracking": (
        "The underlying algorithm should use backtracking/exhaustive search, but the RETURNED answer must reduce "
        "to a scalar (count of valid arrangements, whether a valid arrangement exists) or a single flat array "
        "(e.g. the lexicographically smallest valid permutation) — never a list of all combinations/permutations, "
        "since the harness's output_type can't represent nested lists."
    ),
    "Graphs": (
        "Represent a graph as an `int` `n` (number of nodes) plus an `int_array` `edges` that is a FLATTENED list "
        "of edge pairs ([u1, v1, u2, v2, ...]). The reference solution reconstructs an adjacency list internally. "
        "Good fits: shortest path length (int), connected components count (int), cycle detection (bool), "
        "bipartiteness check (bool), course-schedule-style feasibility (bool), topological order (int_array_ordered)."
    ),
    "Dynamic Programming": "knapsack-style max value, longest increasing subsequence length, edit distance, coin change minimum coins, unique paths counting — output almost always a single int",
    "Greedy": "interval scheduling max count, jump-game reachability (bool), minimum platforms/meeting rooms count, gas station starting index",
    "Bit Manipulation": "single-number-via-XOR, counting set bits, power-of-two check, hamming distance, subset generation via bitmask counting",
    "Math & Number Theory": "GCD/LCM, primality testing, digit manipulation, modular exponentiation, integer sqrt — output almost always int or bool",
    "Recursion": "pure recursive problems distinct from Backtracking's exhaustive-search flavor — recursive tree/array descent, divide-and-conquer, recursion-with-memoization introduced as a concept (before full DP tabulation) — output a scalar or flat ordered array",
    "Sorting": "custom comparator logic, counting sort / bucket sort for a bounded range, merge-step mechanics, finding the kth element via a sort-based or partition-based approach",
}

SQL_STEPS = {
    "Joins": "INNER/LEFT/RIGHT-equivalent joins across 2-3 small tables, anti-joins (rows with no match)",
    "Aggregation": "GROUP BY with COUNT/SUM/AVG/MIN/MAX, HAVING filters on the aggregate",
    "Subqueries": "scalar subqueries, correlated subqueries, subqueries in WHERE/FROM",
    "Sorting & Limiting": "ORDER BY + LIMIT/OFFSET, top-N-per-group patterns",
    "Window Functions": "ROW_NUMBER, RANK, DENSE_RANK, LAG/LEAD, running totals via SUM() OVER (...) — SQLite 3.25+ supports these, use them freely",
    "Set Operations": "UNION, UNION ALL, INTERSECT, EXCEPT across compatible result sets",
    "String & Date Functions": "SUBSTR, LENGTH, UPPER/LOWER, TRIM, date()/strftime() manipulation (SQLite date functions)",
    "Advanced Joins & Self-Joins": "self-joins (e.g. hierarchical/manager-report relationships), 3+ table joins",
    "Case Expressions & Conditional Logic": "CASE WHEN for pivoting/bucketing, conditional aggregation (SUM(CASE WHEN ...))",
    "Indexing & Performance": (
        "questions that test conceptual understanding of query performance — e.g. 'which of these two "
        "equivalent queries would benefit from an index on column X and why', identifying a query that "
        "does a full table scan vs one that could use an index, EXPLAIN-QUERY-PLAN-style reasoning framed as "
        "a normal SQL problem (write a query, AND the solution_writeup explains the indexing/perf angle)"
    ),
}

LOGICAL_REASONING_STEPS = {
    "Verbal Reasoning": "syllogisms, statement-and-conclusion, statement-and-assumption",
    "Analytical Reasoning": "number series, letter series, analogies, classification (odd-one-out)",
    "Non-Verbal Reasoning": "pattern completion described in words, mirror/water image reasoning described textually, figure series described textually (text-only, no actual images)",
    "Blood Relations & Family Tree": "multi-generation family relationship puzzles, pointing-at-a-photograph style questions",
    "Puzzles & Arrangements": "linear seating arrangement, circular seating arrangement, simple puzzles with 4-6 entities and 3-5 clues",
    "Data Sufficiency": "a question plus two numbered statements; the options are the 5 standard data-sufficiency choices (statement 1 alone sufficient / statement 2 alone sufficient / both together sufficient / either alone sufficient / neither sufficient)",
    "Coding-Decoding & Series": "letter-shift ciphers, number-to-letter coding, missing-term series",
    "Critical Reasoning": "strengthen/weaken-the-argument, cause-and-effect, course-of-action questions",
}

COMPUTER_NETWORKS_STEPS = {
    "OSI & TCP/IP Fundamentals": "the 7 OSI layers vs. the 4-layer TCP/IP model, encapsulation, protocol-to-layer mapping",
    "Addressing & Routing": "IPv4/IPv6 addressing, subnetting/CIDR, static vs dynamic routing, routing protocols (RIP/OSPF/BGP) at a conceptual level",
    "Application Layer Protocols": "HTTP/HTTPS, DNS, FTP, SMTP, well-known port numbers",
    "Network Security": "firewalls, VPNs, TLS/SSL handshake basics, common attacks (DDoS, MITM, ARP spoofing) at a conceptual level",
    "Network Performance & Troubleshooting": "latency vs bandwidth vs throughput, common troubleshooting tools (ping/traceroute/nslookup), congestion control basics",
    "Wireless & LAN Technologies": "Wi-Fi standards (802.11), Ethernet basics, CSMA/CD vs CSMA/CA, switches vs hubs",
    "Network Devices & Topologies": "routers vs switches vs hubs vs bridges, star/bus/ring/mesh topologies, collision vs broadcast domains",
}

SYSTEM_DESIGN_STEPS = {
    "High-Level Design (HLD)": "a full distributed-system design prompt (scale, storage choice, caching, API shape)",
    "Low-Level Design (LLD)": "an object-oriented class design prompt for a single-process system",
    "HLD: Scalability & Reliability Patterns": "load balancing strategies, horizontal scaling, replication, failover, circuit breakers, back-pressure",
    "HLD: Data Storage & Caching": "SQL vs NoSQL trade-offs for a given access pattern, sharding strategies, cache invalidation strategies, CDN usage",
    "LLD: Design Patterns Practice": "a class design prompt whose clean solution naturally uses a specific GoF pattern (strategy, observer, factory, decorator, state) without being told which one",
    "LLD: API & Concurrency Design": "designing a small in-process API/data structure that must be thread-safe or handle concurrent access correctly (e.g. an LRU cache, a rate limiter object, a connection pool)",
}

PATH_STEP_CATALOG = {
    "DSA": DSA_STEPS,
    "SQL": SQL_STEPS,
    "Logical Reasoning": LOGICAL_REASONING_STEPS,
    "Computer Networks": COMPUTER_NETWORKS_STEPS,
    "System Design": SYSTEM_DESIGN_STEPS,
}

DIFFICULTIES = ["Easy", "Easy", "Medium", "Medium", "Hard"]  # weighted toward Easy/Medium


def new_id(prefix: str) -> str:
    return f"{prefix}-gen-{uuid.uuid4().hex[:12]}"


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


# ---------------------------------------------------------------------------
# Recently-seen titles per step, so prompts can steer away from repeats.
# ---------------------------------------------------------------------------
RECENT_TITLES: Dict[Tuple[str, str], List[str]] = {}


def remember_title(path: str, step: str, title: str) -> None:
    key = (path, step)
    lst = RECENT_TITLES.setdefault(key, [])
    lst.append(title)
    del lst[:-15]


def recent_titles_note(path: str, step: str) -> str:
    lst = RECENT_TITLES.get((path, step), [])
    if not lst:
        return ""
    return "Avoid repeating (or trivially rephrasing) any of these already-generated titles: " + "; ".join(lst)


# ---------------------------------------------------------------------------
# Generic non-Python starter stub generation (JS/C++/Java) — NOT executed or
# verified, plain unimplemented signatures matching build_harness's own
# per-type parsing rules. Accepted residual gap: a wrong signature here would
# only surface if a real user submits in that language (flagged in report).
# ---------------------------------------------------------------------------
def _snake_to_camel(name: str) -> str:
    parts = name.split("_")
    return parts[0] + "".join(p.title() for p in parts[1:])


def build_multi_lang_stubs(entry_py: str, params: List[dict], output_type: str) -> Tuple[dict, dict]:
    entry_other = _snake_to_camel(entry_py)
    entry_point = {"python": entry_py, "javascript": entry_other, "cpp": entry_other, "java": entry_other}

    py_args = ", ".join(p["name"] for p in params)
    starter = {
        "python": f"def {entry_py}({py_args}):\n    # TODO: implement\n    pass\n",
    }

    js_args = ", ".join(p["name"] for p in params)
    starter["javascript"] = f"function {entry_other}({js_args}) {{\n  // TODO: implement\n}}\n"

    cpp_type = {"int": "int", "int_array": "vector<int>&", "string": "string"}
    cpp_ret = {
        "int": "int", "bool": "bool",
        "int_array_sorted": "vector<int>", "int_array_ordered": "vector<int>",
    }[output_type]
    cpp_default = {"int": "0", "bool": "false", "vector<int>": "{}"}[cpp_ret]
    cpp_params = ", ".join(f"{cpp_type[p['type']]} {p['name']}" for p in params)
    starter["cpp"] = (
        "#include <vector>\n#include <string>\nusing namespace std;\n\n"
        "class Solution {\npublic:\n"
        f"    {cpp_ret} {entry_other}({cpp_params}) {{\n"
        "        // TODO: implement\n"
        f"        return {cpp_default};\n"
        "    }\n};\n"
    )

    java_type = {"int": "int", "int_array": "int[]", "string": "String"}
    java_ret = {
        "int": "int", "bool": "boolean",
        "int_array_sorted": "int[]", "int_array_ordered": "int[]",
    }[output_type]
    java_default = {"int": "0", "boolean": "false", "int[]": "new int[]{}"}[java_ret]
    java_params = ", ".join(f"{java_type[p['type']]} {p['name']}" for p in params)
    starter["java"] = (
        "class Solution {\n"
        f"    public {java_ret} {entry_other}({java_params}) {{\n"
        "        // TODO: implement\n"
        f"        return {java_default};\n"
        "    }\n}\n"
    )
    return entry_point, starter


# ---------------------------------------------------------------------------
# CODE (DSA) generation + verification
# ---------------------------------------------------------------------------
CODE_SYSTEM_PROMPT = """You invent ORIGINAL coding-interview practice problems (LeetCode-style), one at a time.

You MUST respond with ONLY a JSON object, no markdown fences, no prose outside the JSON:
{
  "title": str,
  "difficulty": "Easy"|"Medium"|"Hard",
  "tags": [str, ...],
  "description": str (markdown, fully self-contained problem statement, no reference to companies/interviews),
  "examples": [{"input": str, "output": str, "explanation": str}, ...]  (2-3 entries),
  "constraints": [str, ...],
  "hints": [str, str, str] (progressively more specific, never give the full solution away in a hint),
  "solution_writeup": str (markdown editorial: approach + time/space complexity, matching a LeetCode-editorial tone,
                            and MUST include a ```python fenced code block containing the reference_solution_python
                            you produce below, VERBATIM — this lets the solution be spot-checked later),
  "entry_point": str (snake_case Python function name),
  "params": [{"name": str, "type": "int"|"int_array"|"string"}, ...]  (ONLY these 3 types allowed, nothing else),
  "output_type": "int"|"bool"|"int_array_sorted"|"int_array_ordered"  (ONLY these 4 values allowed — "sorted" if any valid order of the output values is acceptable, "ordered" if the exact order matters),
  "reference_solution_python": str (a full, correct, working Python function definition named exactly `entry_point`, taking exactly `params` as positional args in order — this WILL be executed to derive real test-case ground truth, so it must be genuinely correct, runnable Python with no placeholders),
  "test_inputs": [ {<param name>: value, ...}, ... ]  (8-12 inputs matching `params` exactly, covering normal cases AND edge cases from your own constraints — e.g. empty/minimal input, duplicates, negatives, boundary values)
}

Never use a param type or output_type outside the allowed lists above, even if the natural version of the problem
would use one (e.g. a tree/list/graph must be encoded into int/int_array/string per the step-specific guidance
you're given — follow that guidance exactly)."""


async def generate_code_problem(step: str, difficulty: str) -> Optional[dict]:
    guidance = DSA_STEPS[step]
    prompt = (
        f"Topic/step: \"{step}\" — concept guidance: {guidance}\n"
        f"Target difficulty: {difficulty}\n"
        f"{recent_titles_note('DSA', step)}\n"
        "Invent one new, original problem now."
    )
    try:
        text = await call_llm(CODE_SYSTEM_PROMPT, prompt, GEN_MODEL, GEN_MAX_TOKENS)
        spec = _extract_json(text)
    except Exception as e:
        logger.warning("DSA generation call failed (%s): %s", step, e)
        return None

    try:
        entry = spec["entry_point"]
        params = spec["params"]
        output_type = spec["output_type"]
        assert output_type in ("int", "bool", "int_array_sorted", "int_array_ordered")
        for p in params:
            assert p["type"] in ("int", "int_array", "string")
        reference_code = spec["reference_solution_python"]
        test_inputs = spec["test_inputs"]
        assert isinstance(test_inputs, list) and len(test_inputs) >= 3
    except Exception as e:
        stats_for("DSA").discard(f"malformed_spec:{type(e).__name__}")
        return None

    harness = _py_harness(entry, params, output_type)
    full_source = reference_code + harness
    lang_cfg = LANGUAGE_RUNTIMES["python"]

    test_cases = []
    for i, inp in enumerate(test_inputs):
        try:
            stdin = json.dumps(inp)
        except Exception:
            stats_for("DSA").discard("bad_test_input_json")
            return None
        try:
            run = await _piston_execute(lang_cfg["piston_language"], lang_cfg["piston_version"], full_source, stdin)
        except PistonUnavailableError as e:
            stats_for("DSA").discard("piston_unavailable")
            logger.warning("Piston unavailable: %s", e)
            return None
        stdout = (run.get("stdout") or "").strip()
        exit_code = run.get("code")
        signal = run.get("signal")
        if signal or (exit_code not in (0, None)) or not stdout:
            stats_for("DSA").discard("reference_solution_crashed")
            return None
        try:
            expected = json.loads(stdout)
        except Exception:
            stats_for("DSA").discard("reference_output_not_json")
            return None
        test_cases.append({"input": inp, "expected": expected, "is_sample": i < 2})

    entry_point, starter_code = build_multi_lang_stubs(entry, params, output_type)

    doc = {
        "_id": new_id(f"dsa-{slug(step)}"),
        "question_type": "code",
        "path": "DSA",
        "title": spec["title"],
        "difficulty": spec.get("difficulty", difficulty),
        "tags": spec.get("tags", []),
        "step": step,
        "companies": [],
        "description": spec["description"],
        "examples": spec.get("examples", []),
        "constraints": spec.get("constraints", []),
        "hints": spec.get("hints", []),
        "solution_writeup": spec.get("solution_writeup", ""),
        "entry_point": entry_point,
        "params": params,
        "output_type": output_type,
        "starter_code": starter_code,
        "test_cases": test_cases,
        "source": "generated",
    }
    remember_title("DSA", step, spec["title"])
    return doc


# ---------------------------------------------------------------------------
# SQL generation + verification
# ---------------------------------------------------------------------------
SQL_SYSTEM_PROMPT = """You invent ORIGINAL SQL practice problems (LeetCode-SQL-style), one at a time.

Respond with ONLY a JSON object, no markdown fences, no prose outside it:
{
  "title": str,
  "difficulty": "Easy"|"Medium"|"Hard",
  "tags": [str, ...],
  "description": str (markdown, states the table schema(s) inline and the exact question),
  "examples": [{"input": str, "output": str, "explanation": str}]  (1-2 entries, illustrative only),
  "constraints": [str, ...],
  "hints": [str, str],
  "solution_writeup": str (markdown editorial: approach + a sql code block),
  "schema_sql": str (one or more `CREATE TABLE` statements followed by `INSERT INTO` statements with realistic
                      sample data — SQLite dialect, fewer than 20 total rows across all tables, must be
                      syntactically valid SQLite and self-contained),
  "solution_query": str (a single SELECT/WITH query — SQLite dialect — that correctly answers the question against
                          schema_sql; this WILL be executed to derive real ground truth),
  "order_sensitive": bool (true only if the question inherently asks for a specific row order, e.g. "top N ... highest first" — false for a plain unordered result set)
}

SQLite 3.25+ is the execution engine — window functions, CTEs (WITH), and UNION/INTERSECT/EXCEPT all work."""


async def generate_sql_problem(step: str, difficulty: str) -> Optional[dict]:
    guidance = SQL_STEPS[step]
    prompt = (
        f"Topic/step: \"{step}\" — concept guidance: {guidance}\n"
        f"Target difficulty: {difficulty}\n"
        f"{recent_titles_note('SQL', step)}\n"
        "Invent one new, original problem now."
    )
    try:
        text = await call_llm(SQL_SYSTEM_PROMPT, prompt, GEN_MODEL, GEN_MAX_TOKENS)
        spec = _extract_json(text)
    except Exception as e:
        logger.warning("SQL generation call failed (%s): %s", step, e)
        return None

    schema_sql = spec.get("schema_sql", "")
    solution_query = spec.get("solution_query", "")
    if not schema_sql or not solution_query:
        stats_for("SQL").discard("missing_schema_or_query")
        return None
    lowered = solution_query.strip().lower().lstrip("(")
    if not (lowered.startswith("select") or lowered.startswith("with")):
        stats_for("SQL").discard("solution_query_not_select")
        return None

    try:
        columns, rows = await asyncio.get_event_loop().run_in_executor(
            None, _sql_execute, schema_sql, solution_query
        )
    except Exception as e:
        stats_for("SQL").discard(f"sql_exec_error:{type(e).__name__}")
        return None
    if not columns:
        stats_for("SQL").discard("solution_query_no_columns")
        return None

    doc = {
        "_id": new_id(f"sql-{slug(step)}"),
        "question_type": "sql",
        "path": "SQL",
        "title": spec["title"],
        "difficulty": spec.get("difficulty", difficulty),
        "tags": spec.get("tags", []),
        "step": step,
        "companies": [],
        "description": spec["description"],
        "examples": spec.get("examples", []),
        "constraints": spec.get("constraints", []),
        "hints": spec.get("hints", []),
        "solution_writeup": spec.get("solution_writeup", ""),
        "schema_sql": schema_sql,
        "solution_query": solution_query,
        "order_sensitive": bool(spec.get("order_sensitive", False)),
        "starter_code": {"sql": "-- write your query\nSELECT\n"},
        "source": "generated",
    }
    remember_title("SQL", step, spec["title"])
    return doc


# ---------------------------------------------------------------------------
# MCQ (Logical Reasoning + Computer Networks) generation + independent
# second-opinion verification.
# ---------------------------------------------------------------------------
MCQ_SYSTEM_PROMPT = """You invent ORIGINAL single-select multiple-choice practice questions, one at a time.

Respond with ONLY a JSON object, no markdown fences, no prose outside it:
{
  "title": str,
  "difficulty": "Easy"|"Medium"|"Hard",
  "tags": [str, ...],
  "description": str (the full question text, self-contained),
  "options": [{"id": "a", "text": str}, {"id": "b", "text": str}, {"id": "c", "text": str}, {"id": "d", "text": str}]
              (exactly 4 options, exactly one objectively correct),
  "correct_option_id": "a"|"b"|"c"|"d",
  "solution_writeup": str (explains why the correct option is right AND briefly why each distractor is wrong)
}

The question must have an objectively, unambiguously correct answer — no matters of opinion."""

MCQ_VERIFY_SYSTEM_PROMPT = """You are answering a multiple-choice question independently. You are NOT told which
option anyone else thinks is correct. Think it through and respond with ONLY a JSON object:
{"answer_option_id": "a"|"b"|"c"|"d", "confidence": "high"|"medium"|"low"}
No markdown fences, no prose outside the JSON."""


async def generate_mcq_problem(path: str, step: str, difficulty: str) -> Optional[dict]:
    guidance = PATH_STEP_CATALOG[path][step]
    prompt = (
        f"Path: \"{path}\", topic/step: \"{step}\" — concept guidance: {guidance}\n"
        f"Target difficulty: {difficulty}\n"
        f"{recent_titles_note(path, step)}\n"
        "Invent one new, original question now."
    )
    try:
        text = await call_llm(MCQ_SYSTEM_PROMPT, prompt, GEN_MODEL, GEN_MAX_TOKENS)
        spec = _extract_json(text)
        options = spec["options"]
        correct_id = spec["correct_option_id"]
        assert len(options) == 4
        ids = {o["id"] for o in options}
        assert correct_id in ids
    except Exception as e:
        stats_for(path).discard(f"malformed_spec:{type(e).__name__}")
        return None

    # Independent second opinion — question + options only, no hint of the answer.
    verify_prompt = (
        f"Question: {spec['description']}\n\nOptions:\n"
        + "\n".join(f"({o['id']}) {o['text']}" for o in options)
    )
    try:
        vtext = await call_llm(MCQ_VERIFY_SYSTEM_PROMPT, verify_prompt, VERIFY_MODEL, VERIFY_MAX_TOKENS)
        vdata = _extract_json(vtext)
        independent_answer = vdata.get("answer_option_id")
    except Exception as e:
        stats_for(path).discard(f"verify_call_failed:{type(e).__name__}")
        return None

    if independent_answer != correct_id:
        stats_for(path).discard("mcq_independent_check_mismatch")
        return None

    doc = {
        "_id": new_id(f"{slug(path)}-{slug(step)}"),
        "question_type": "mcq",
        "path": path,
        "title": spec["title"],
        "difficulty": spec.get("difficulty", difficulty),
        "tags": spec.get("tags", []),
        "step": step,
        "companies": [],
        "description": spec["description"],
        "options": options,
        "correct_option_id": correct_id,
        "solution_writeup": spec.get("solution_writeup", ""),
        "source": "generated",
    }
    remember_title(path, step, spec["title"])
    return doc


# ---------------------------------------------------------------------------
# Design (System Design) generation + rubric self-review.
# ---------------------------------------------------------------------------
DESIGN_SYSTEM_PROMPT = """You invent ORIGINAL system-design (HLD) or object-oriented class-design (LLD) practice
prompts, one at a time.

Respond with ONLY a JSON object, no markdown fences, no prose outside it:
{
  "title": str,
  "difficulty": "Medium"|"Hard",
  "tags": [str, ...],
  "description": str (markdown: the scenario, explicit requirements to address, and 3-5 specific things the
                       answer should discuss),
  "hints": [str, str, str],
  "solution_writeup": str (markdown: the key points a strong answer should hit),
  "rubric": [{"criterion": str, "max_score": 10, "description": str (specific, gradeable from a WRITTEN answer)}, ...]
             (exactly 5 criteria, each independently gradeable, each max_score 10)
}"""

RUBRIC_REVIEW_SYSTEM_PROMPT = """You review a grading rubric for a system-design practice question for whether
each criterion is SPECIFIC and GRADEABLE from a candidate's written answer (not vague like "good design" or
"clear thinking" with no concrete signal to check for).

Respond with ONLY a JSON object: {"ok": bool, "issues": [str, ...]}
"ok" is true only if EVERY criterion names a concrete, checkable thing an answer would need to say."""


async def generate_design_problem(step: str, difficulty: str) -> Optional[dict]:
    guidance = SYSTEM_DESIGN_STEPS[step]
    prompt = (
        f"Topic/step: \"{step}\" — concept guidance: {guidance}\n"
        f"Target difficulty: {difficulty}\n"
        f"{recent_titles_note('System Design', step)}\n"
        "Invent one new, original design prompt now."
    )
    try:
        text = await call_llm(DESIGN_SYSTEM_PROMPT, prompt, GEN_MODEL, GEN_MAX_TOKENS)
        spec = _extract_json(text)
        rubric = spec["rubric"]
        assert isinstance(rubric, list) and len(rubric) >= 3
    except Exception as e:
        stats_for("System Design").discard(f"malformed_spec:{type(e).__name__}")
        return None

    rubric_text = "\n".join(f"- \"{c['criterion']}\" (max {c.get('max_score', 10)}): {c.get('description', '')}" for c in rubric)
    try:
        rtext = await call_llm(RUBRIC_REVIEW_SYSTEM_PROMPT, rubric_text, VERIFY_MODEL, VERIFY_MAX_TOKENS)
        rdata = _extract_json(rtext)
    except Exception as e:
        stats_for("System Design").discard(f"rubric_review_call_failed:{type(e).__name__}")
        return None

    if not rdata.get("ok", False):
        stats_for("System Design").discard("rubric_review_flagged_vague")
        return None

    doc = {
        "_id": new_id(f"sd-{slug(step)}"),
        "question_type": "design",
        "path": "System Design",
        "title": spec["title"],
        "difficulty": spec.get("difficulty", difficulty),
        "tags": spec.get("tags", []),
        "step": step,
        "companies": [],
        "description": spec["description"],
        "hints": spec.get("hints", []),
        "solution_writeup": spec.get("solution_writeup", ""),
        "rubric": rubric,
        "source": "generated",
    }
    remember_title("System Design", step, spec["title"])
    return doc


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
GENERATORS = {
    "DSA": lambda step, diff: generate_code_problem(step, diff),
    "SQL": lambda step, diff: generate_sql_problem(step, diff),
    "Logical Reasoning": lambda step, diff: generate_mcq_problem("Logical Reasoning", step, diff),
    "Computer Networks": lambda step, diff: generate_mcq_problem("Computer Networks", step, diff),
    "System Design": lambda step, diff: generate_design_problem(step, diff),
}


async def attempt_one(path: str, step: str) -> None:
    difficulty = random.choice(DIFFICULTIES)
    stats = stats_for(path)
    stats.attempted += 1
    try:
        doc = await GENERATORS[path](step, difficulty)
    except Exception:
        logger.exception("Unhandled error generating %s/%s", path, step)
        stats.discard("unhandled_exception")
        return
    if doc is None:
        return
    doc["created_at"] = now_iso()
    doc["updated_at"] = now_iso()
    try:
        await practice_problems_col.insert_one(doc)
        stats.inserted += 1
        logger.info("[%s/%s] inserted %s (%s)", path, step, doc["_id"], doc["title"])
    except Exception as e:
        stats.discard(f"insert_failed:{type(e).__name__}")


async def worker(queue: "asyncio.Queue[Tuple[str, str]]") -> None:
    while True:
        item = await queue.get()
        if item is None:
            queue.task_done()
            return
        path, step = item
        try:
            await attempt_one(path, step)
        finally:
            queue.task_done()


async def cumulative_counts(paths: List[str]) -> Dict[str, int]:
    """Real CUMULATIVE count of `source: generated` docs per path already in
    Mongo — i.e. everything inserted across every prior run/process in this
    task, not just this process's own in-memory `stats_for(p).inserted`
    counter (which resets to 0 every time the script is (re)launched).
    Per-path stopping thresholds are defined against THIS number, since the
    goal is a real total in the database, not "N more from this invocation"."""
    out = {p: 0 for p in paths}
    cursor = practice_problems_col.aggregate([
        {"$match": {"source": "generated", "path": {"$in": paths}}},
        {"$group": {"_id": "$path", "n": {"$sum": 1}}},
    ])
    async for row in cursor:
        out[row["_id"]] = row["n"]
    return out


async def run(paths: List[str], thresholds: Dict[str, int], concurrency: int, time_budget_s: Optional[float]) -> None:
    """`thresholds[path]` is a CUMULATIVE target (existing DB count + whatever
    this run adds) — a path stops being fed new work once its baseline +
    this-run inserted count crosses its own threshold, independently of the
    other paths (they are not required to reach their thresholds at the same
    time — System Design/DSA need much more runway than the MCQ paths here)."""
    baseline = await cumulative_counts(paths)
    logger.info("Baseline cumulative counts at start: %s | thresholds: %s", baseline, thresholds)

    def cumulative(path: str) -> int:
        return baseline[path] + stats_for(path).inserted

    def path_done(path: str) -> bool:
        return cumulative(path) >= thresholds.get(path, 10**9)

    queue: "asyncio.Queue[Optional[Tuple[str, str]]]" = asyncio.Queue()
    workers = [asyncio.create_task(worker(queue)) for _ in range(concurrency)]

    start = time.monotonic()
    stop = False

    async def feeder():
        nonlocal stop
        # Round-robin over (path, step) pairs so volume spreads across topics
        # instead of exhausting one step before moving to the next — but skip
        # any (path, step) whose PATH has already crossed its own threshold,
        # so a path that finishes early (e.g. the 150-target MCQ paths) stops
        # consuming worker time while paths still short of their target
        # (e.g. System Design's 500) keep getting fed.
        pairs = [(p, s) for p in paths for s in PATH_STEP_CATALOG[p]]
        idx = 0
        while not stop:
            if time_budget_s is not None and (time.monotonic() - start) > time_budget_s:
                break
            if all(path_done(p) for p in paths):
                break
            path, step = pairs[idx % len(pairs)]
            idx += 1
            if path_done(path):
                continue
            await queue.put((path, step))
            # Backpressure: don't let the queue balloon far ahead of workers.
            while queue.qsize() > concurrency * 3:
                await asyncio.sleep(0.5)
                if time_budget_s is not None and (time.monotonic() - start) > time_budget_s:
                    break

    feeder_task = asyncio.create_task(feeder())

    # Periodic progress printer — reports CUMULATIVE (baseline + this-run) per
    # path, since that's what the stopping thresholds are actually judged against.
    async def printer():
        while not feeder_task.done():
            await asyncio.sleep(30)
            snapshot = {p: {"cumulative": cumulative(p), "threshold": thresholds.get(p),
                            "done": path_done(p), **stats_for(p).as_dict()} for p in paths}
            logger.info("PROGRESS %s | %s", snapshot, COST.summary().splitlines()[0])

    printer_task = asyncio.create_task(printer())

    await feeder_task
    await queue.join()
    stop = True
    for _ in workers:
        await queue.put(None)
    await asyncio.gather(*workers)
    printer_task.cancel()
    logger.info("Stopped. Final cumulative: %s", {p: cumulative(p) for p in paths})


# Per-path CUMULATIVE targets (existing DB count + this run), by direct user
# instruction replacing the earlier flat "1000/path" target: the MCQ-graded
# and small-schema-SQL paths top out around 150; DSA and System Design (which
# started furthest behind) get a higher 500 ceiling. Overridable per-run via
# --threshold PATH=N for flexibility, but these are the defaults that matter now.
DEFAULT_THRESHOLDS = {
    "DSA": 500,
    "SQL": 150,
    "Logical Reasoning": 150,
    "Computer Networks": 150,
    "System Design": 500,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", action="append", choices=list(PATH_STEP_CATALOG), help="repeatable; default: all 5")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--target", type=int, default=None,
                     help="flat CUMULATIVE target for any path not covered by --threshold/DEFAULT_THRESHOLDS")
    ap.add_argument("--threshold", action="append", default=[],
                     help="repeatable PATH=N override of a per-path cumulative threshold, e.g. --threshold DSA=800")
    ap.add_argument("--concurrency", type=int, default=6)
    ap.add_argument("--time-budget-min", type=float, default=None)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    paths = args.path if args.path else list(PATH_STEP_CATALOG)
    if not ANTHROPIC_API_KEY:
        logger.error("ANTHROPIC_API_KEY not set — aborting.")
        sys.exit(1)

    thresholds = dict(DEFAULT_THRESHOLDS)
    if args.target is not None:
        thresholds = {p: args.target for p in paths}
    for spec in args.threshold:
        p, _, n = spec.partition("=")
        if p not in PATH_STEP_CATALOG or not n.isdigit():
            logger.error("Bad --threshold %r — expected PATH=N", spec)
            sys.exit(1)
        thresholds[p] = int(n)
    thresholds = {p: thresholds.get(p, DEFAULT_THRESHOLDS.get(p, 200)) for p in paths}

    time_budget_s = args.time_budget_min * 60 if args.time_budget_min else None
    logger.info("Starting generation: paths=%s thresholds=%s concurrency=%d budget=%s", paths, thresholds, args.concurrency, args.time_budget_min)

    asyncio.run(run(paths, thresholds, args.concurrency, time_budget_s))

    logger.info("=== FINAL STATS ===")
    for p in paths:
        logger.info("%s: %s", p, json.dumps(stats_for(p).as_dict()))
    logger.info(COST.summary())

    scratch_dir = os.environ.get("SEED_REPORT_DIR", "/private/tmp")
    out_path = os.path.join(scratch_dir, f"seed_generated_practice_report_{int(time.time())}.json")
    try:
        with open(out_path, "w") as f:
            json.dump({
                "paths": {p: stats_for(p).as_dict() for p in paths},
                "cost": {"calls": COST.calls, "input_tokens": COST.input_tokens,
                         "output_tokens": COST.output_tokens, "usd": COST.usd(),
                         "by_model": COST.by_model},
            }, f, indent=2)
        logger.info("Report written to %s", out_path)
    except Exception:
        logger.exception("Could not write report file")


if __name__ == "__main__":
    main()
