"""Practice Engine — code execution (via Piston) and grading against test cases.

Cold-start seeds any problem in ALL_PROBLEMS that isn't already in
`practice_problems` yet (per-problem, not "only if the whole collection is
empty" — see `seed_problems()`), so admin edits to already-seeded problems are
never clobbered, and new problems added to this file over time get inserted
without touching what's already there.

Execution strategy: the user submits a bare function body (e.g. `def two_sum(nums,
target): ...`). We append a small per-language "harness" that reads the test
case's input as JSON on stdin, calls the user's function, and prints the result
as JSON on stdout. The backend then compares that JSON (order/whitespace
normalized) against the test case's expected JSON — never a brittle byte-exact
stdout comparison.

Harnesses are generated GENERICALLY from each problem's `params` (an ordered
list of `{"name": ..., "type": "int_array" | "int" | "string"}`, matching the
keys of each test case's `input` dict) and `output_type` (one of "int",
"bool", "int_array_sorted", "int_array_ordered") — see "Generic harness
generation" below. This replaces the original hardcoded-to-Two-Sum's-exact-
shape (`nums`/`target` -> sorted list of ints) harness with something that
covers any of this file's problems, present or future, without a bespoke
per-problem harness.

Piston (https://github.com/engineer-man/piston) does the actual sandboxed run.
The public instance (https://emkc.org/api/v2/piston) went whitelist-only in
2026, so PISTON_URL is configurable — point it at a self-hosted instance
(`docker run --privileged -p 2000:2000 ghcr.io/engineer-man/piston`, then
`POST /api/v2/packages` to install the languages you need) via the
PISTON_URL env var. Defaults to the public URL for whenever whitelisting comes
through / someone points it elsewhere.
"""
import os
import json
import logging
import re
import sqlite3
from datetime import timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx

from db import db, now_iso, now_utc

logger = logging.getLogger(__name__)

practice_problems_col = db["practice_problems"]
practice_submissions_col = db["practice_submissions"]

PISTON_URL = os.environ.get("PISTON_URL", "https://emkc.org/api/v2/piston").rstrip("/")
PISTON_TIMEOUT_S = float(os.environ.get("PISTON_TIMEOUT_S", "15"))
# Guards against user code that infinite-loops — Piston kills the process past this.
RUN_TIMEOUT_MS = int(os.environ.get("PISTON_RUN_TIMEOUT_MS", "5000"))

# language key (as used by the frontend / stored problem docs) -> Piston's
# (language, version) pair. Confirmed against a live `GET /api/v2/runtimes`
# rather than hardcoded blind — versions drift over time.
LANGUAGE_RUNTIMES = {
    "python": {"piston_language": "python", "piston_version": "3.10.0"},
    "javascript": {"piston_language": "javascript", "piston_version": "20.11.1"},
    "cpp": {"piston_language": "c++", "piston_version": "10.2.0"},
    # Java's compiler enforces "public class name == filename" — Piston needs
    # an explicit filename, since the harness's public class is `Main`, not
    # whatever the problem's entry point is called.
    "java": {"piston_language": "java", "piston_version": "15.0.2", "filename": "Main"},
}

# Roadmap top-level grouping, added above `step` when the SQL / Logical
# Reasoning / Computer Networks / System Design paths were introduced
# alongside the original DSA (code) problems. Anything not listed sorts last,
# by insertion order among the unlisted, rather than erroring.
PATH_ORDER = {
    "DSA": 0,
    "SQL": 1,
    "Logical Reasoning": 2,
    "Computer Networks": 3,
    "System Design": 4,
}

# Roadmap "step" (topic) display order WITHIN a path — keyed by path first
# since step names are only unique within their own path (e.g. "Joins" only
# means something under the SQL path). Anything not listed sorts last, by
# insertion order among the unlisted, rather than erroring.
STEP_ORDER = {
    "DSA": {
        "Arrays & Hashing": 0,
        "Two Pointers": 1,
        "Binary Search": 2,
        # --- added for bulk-generated content (see scripts/seed_generated_practice.py) ---
        "Sliding Window": 3,
        "Stacks & Queues": 4,
        "Linked Lists": 5,
        "Trees": 6,
        "Heaps": 7,
        "Backtracking": 8,
        "Graphs": 9,
        "Dynamic Programming": 10,
        "Greedy": 11,
        "Bit Manipulation": 12,
        "Math & Number Theory": 13,
        "Recursion": 14,
        "Sorting": 15,
    },
    "SQL": {
        "Joins": 0,
        "Aggregation": 1,
        "Subqueries": 2,
        "Sorting & Limiting": 3,
        # --- added for bulk-generated content ---
        "Window Functions": 4,
        "Set Operations": 5,
        "String & Date Functions": 6,
        "Advanced Joins & Self-Joins": 7,
        "Case Expressions & Conditional Logic": 8,
        "Indexing & Performance": 9,
    },
    "Logical Reasoning": {
        "Verbal Reasoning": 0,
        "Analytical Reasoning": 1,
        # --- added for bulk-generated content ---
        "Non-Verbal Reasoning": 2,
        "Blood Relations & Family Tree": 3,
        "Puzzles & Arrangements": 4,
        "Data Sufficiency": 5,
        "Coding-Decoding & Series": 6,
        "Critical Reasoning": 7,
    },
    "Computer Networks": {
        "OSI & TCP/IP Fundamentals": 0,
        "Addressing & Routing": 1,
        "Application Layer Protocols": 2,
        # --- added for bulk-generated content ---
        "Network Security": 3,
        "Network Performance & Troubleshooting": 4,
        "Wireless & LAN Technologies": 5,
        "Network Devices & Topologies": 6,
    },
    "System Design": {
        "High-Level Design (HLD)": 0,
        "Low-Level Design (LLD)": 1,
        # --- added for bulk-generated content ---
        "HLD: Scalability & Reliability Patterns": 2,
        "HLD: Data Storage & Caching": 3,
        "LLD: Design Patterns Practice": 4,
        "LLD: API & Concurrency Design": 5,
    },
}


# ---------------------------------------------------------------------------
# Generic harness generation.
#
# Python/JS have JSON built in, so their harnesses are fully generic: parse
# stdin as JSON, pull each named param out of the dict (any names, any order,
# any count), call the entry point positionally, and print the JSON-encoded
# result — sorting first only when `output_type == "int_array_sorted"` (an
# answer like Two Sum's, where any valid index order is acceptable).
#
# C++ and Java don't have a JSON library available in the Piston images this
# project targets (the original Two Sum harness deliberately avoided pulling
# one in for exactly this reason), so those two hand-parse each named field
# out of the raw JSON text by type — the same trick the original nums/target
# parser used, generalized to any ordered set of (name, type) params instead
# of being hardcoded to exactly "nums" + "target".
# ---------------------------------------------------------------------------
def _py_harness(entry_point: str, params: List[dict], output_type: str) -> str:
    args = ", ".join(f"_data[{p['name']!r}]" for p in params)
    wrap = "sorted(_result)" if output_type == "int_array_sorted" else "_result"
    return (
        "\n\n"
        "import sys as _sys, json as _json\n"
        "_data = _json.loads(_sys.stdin.read())\n"
        f"_result = {entry_point}({args})\n"
        f"print(_json.dumps({wrap}))\n"
    )


def _js_harness(entry_point: str, params: List[dict], output_type: str) -> str:
    args = ", ".join(f"_data[{p['name']!r}]" for p in params)
    wrap = "[..._result].sort((a, b) => a - b)" if output_type == "int_array_sorted" else "_result"
    return (
        "\n\n"
        "const _data = JSON.parse(require('fs').readFileSync(0, 'utf-8'));\n"
        f"const _result = {entry_point}({args});\n"
        f"const _out = {wrap};\n"
        "console.log(JSON.stringify(_out));\n"
    )


def _cpp_parse_param(p: dict, idx: int) -> Tuple[str, str]:
    name, ptype = p["name"], p["type"]
    var = f"_p{idx}"
    if ptype == "int_array":
        code = (
            f"    std::vector<int> {var};\n"
            "    {\n"
            f"        size_t _k = all.find(\"\\\"{name}\\\"\"); size_t _lb = all.find('[', _k); size_t _rb = all.find(']', _lb);\n"
            "        std::string _arr = all.substr(_lb + 1, _rb - _lb - 1);\n"
            "        std::stringstream _ss(_arr); std::string _tok;\n"
            f"        while (std::getline(_ss, _tok, ',')) {{ if (!_tok.empty()) {var}.push_back(std::stoi(_tok)); }}\n"
            "    }\n"
        )
    elif ptype == "int":
        code = (
            f"    int {var};\n"
            "    {\n"
            f"        size_t _k = all.find(\"\\\"{name}\\\"\"); size_t _c = all.find(':', _k);\n"
            f"        {var} = std::stoi(all.substr(_c + 1));\n"
            "    }\n"
        )
    elif ptype == "string":
        code = (
            f"    std::string {var};\n"
            "    {\n"
            f"        size_t _k = all.find(\"\\\"{name}\\\"\"); size_t _c = all.find(':', _k);\n"
            "        size_t _q1 = all.find('\"', _c); size_t _q2 = all.find('\"', _q1 + 1);\n"
            f"        {var} = all.substr(_q1 + 1, _q2 - _q1 - 1);\n"
            "    }\n"
        )
    else:
        raise ValueError(f"unsupported param type for cpp harness: {ptype}")
    return code, var


def _cpp_harness(entry_point: str, params: List[dict], output_type: str) -> str:
    decls, varnames = [], []
    for i, p in enumerate(params):
        code, var = _cpp_parse_param(p, i)
        decls.append(code)
        varnames.append(var)
    call_args = ", ".join(varnames)

    if output_type == "int":
        result_decl = f"int result = sol.{entry_point}({call_args});"
        print_code = "std::cout << result << std::endl;"
    elif output_type == "bool":
        result_decl = f"bool result = sol.{entry_point}({call_args});"
        print_code = 'std::cout << (result ? "true" : "false") << std::endl;'
    elif output_type in ("int_array_sorted", "int_array_ordered"):
        result_decl = f"std::vector<int> result = sol.{entry_point}({call_args});"
        sort_code = "std::sort(result.begin(), result.end());\n    " if output_type == "int_array_sorted" else ""
        print_code = (
            f"{sort_code}std::cout << \"[\";\n"
            "    for (size_t i = 0; i < result.size(); ++i) { if (i) std::cout << \",\"; std::cout << result[i]; }\n"
            "    std::cout << \"]\" << std::endl;"
        )
    else:
        raise ValueError(f"unsupported output_type for cpp harness: {output_type}")

    return (
        "\n\n"
        "#include <iostream>\n"
        "#include <sstream>\n"
        "#include <string>\n"
        "#include <vector>\n"
        "#include <algorithm>\n"
        "int main() {\n"
        "    std::string all((std::istreambuf_iterator<char>(std::cin)), std::istreambuf_iterator<char>());\n"
        + "".join(decls)
        + "    Solution sol;\n"
        f"    {result_decl}\n"
        f"    {print_code}\n"
        "    return 0;\n"
        "}\n"
    )


def _java_parse_param(p: dict, idx: int) -> Tuple[str, str]:
    name, ptype = p["name"], p["type"]
    var = f"_p{idx}"
    if ptype == "int_array":
        code = (
            f"        int[] {var};\n"
            "        {\n"
            f"            int _k = all.indexOf(\"\\\"{name}\\\"\"); int _lb = all.indexOf('[', _k); int _rb = all.indexOf(']', _lb);\n"
            "            java.util.List<Integer> _list = new java.util.ArrayList<>();\n"
            "            for (String _tok : all.substring(_lb + 1, _rb).split(\",\")) {\n"
            "                _tok = _tok.trim();\n"
            "                if (!_tok.isEmpty()) _list.add(Integer.parseInt(_tok));\n"
            "            }\n"
            f"            {var} = new int[_list.size()];\n"
            f"            for (int _i = 0; _i < {var}.length; _i++) {var}[_i] = _list.get(_i);\n"
            "        }\n"
        )
    elif ptype == "int":
        code = (
            f"        int {var};\n"
            "        {\n"
            f"            int _k = all.indexOf(\"\\\"{name}\\\"\"); int _c = all.indexOf(':', _k);\n"
            "            String _rest = all.substring(_c + 1).trim();\n"
            "            StringBuilder _num = new StringBuilder();\n"
            "            for (char _ch : _rest.toCharArray()) {\n"
            "                if (Character.isDigit(_ch) || _ch == '-') _num.append(_ch); else break;\n"
            "            }\n"
            f"            {var} = Integer.parseInt(_num.toString());\n"
            "        }\n"
        )
    elif ptype == "string":
        code = (
            f"        String {var};\n"
            "        {\n"
            f"            int _k = all.indexOf(\"\\\"{name}\\\"\"); int _c = all.indexOf(':', _k);\n"
            "            int _q1 = all.indexOf('\"', _c); int _q2 = all.indexOf('\"', _q1 + 1);\n"
            f"            {var} = all.substring(_q1 + 1, _q2);\n"
            "        }\n"
        )
    else:
        raise ValueError(f"unsupported param type for java harness: {ptype}")
    return code, var


def _java_harness(entry_point: str, params: List[dict], output_type: str) -> str:
    decls, varnames = [], []
    for i, p in enumerate(params):
        code, var = _java_parse_param(p, i)
        decls.append(code)
        varnames.append(var)
    call_args = ", ".join(varnames)

    if output_type == "int":
        result_decl = f"int result = sol.{entry_point}({call_args});"
        print_code = "System.out.println(result);"
    elif output_type == "bool":
        result_decl = f"boolean result = sol.{entry_point}({call_args});"
        print_code = "System.out.println(result ? \"true\" : \"false\");"
    elif output_type in ("int_array_sorted", "int_array_ordered"):
        result_decl = f"int[] result = sol.{entry_point}({call_args});"
        sort_code = "java.util.Arrays.sort(result);\n        " if output_type == "int_array_sorted" else ""
        print_code = (
            f"{sort_code}StringBuilder _out = new StringBuilder(\"[\");\n"
            "        for (int _i = 0; _i < result.length; _i++) { if (_i > 0) _out.append(\",\"); _out.append(result[_i]); }\n"
            "        _out.append(\"]\");\n"
            "        System.out.println(_out.toString());"
        )
    else:
        raise ValueError(f"unsupported output_type for java harness: {output_type}")

    return (
        "\n\n"
        # Pre-imported here (like LeetCode/most judges do) so a solution can
        # use Map/HashMap/List/etc. unqualified with no import of its own.
        # This harness has to be the FIRST thing in the file (see the
        # java-specific compose-order note in run_submission below), so these
        # imports must live here — any import statement the user writes
        # themselves gets stripped before compiling, since one appearing
        # after this class would be a Java compile error, not because it's
        # forbidden to write, just redundant now.
        "import java.util.*;\n"
        "import java.util.stream.*;\n"
        "import java.util.function.*;\n"
        "import java.math.*;\n\n"
        "public class Main {\n"
        "    public static void main(String[] args) throws Exception {\n"
        "        StringBuilder sb = new StringBuilder();\n"
        "        java.io.BufferedReader br = new java.io.BufferedReader(new java.io.InputStreamReader(System.in));\n"
        "        String line;\n"
        "        while ((line = br.readLine()) != null) sb.append(line);\n"
        "        String all = sb.toString();\n"
        + "".join(decls)
        + "        Solution sol = new Solution();\n"
        f"        {result_decl}\n"
        f"        {print_code}\n"
        "    }\n"
        "}\n"
    )


def build_harness(language: str, entry_point: str, params: List[dict], output_type: str) -> str:
    if language == "python":
        return _py_harness(entry_point, params, output_type)
    if language == "javascript":
        return _js_harness(entry_point, params, output_type)
    if language == "cpp":
        return _cpp_harness(entry_point, params, output_type)
    if language == "java":
        return _java_harness(entry_point, params, output_type)
    raise ValueError(f"Unsupported language: {language}")


# ---------------------------------------------------------------------------
# Seed data.
#
# Every problem below is hand-authored (description, examples, constraints,
# hints, solution_writeup, starter code) — none of it is LLM-generated. Each
# follows the exact schema TWO_SUM_PROBLEM established, plus three roadmap
# fields: `step` (topic group), `order` (position within that step), and
# `companies` (illustrative topic associations, NOT real interview-frequency
# data — the frontend carries a disclaimer next to the company filter).
# ---------------------------------------------------------------------------
TWO_SUM_PROBLEM = {
    "_id": "two-sum",
    "question_type": "code",
    "path": "DSA",
    "title": "Two Sum",
    "difficulty": "Easy",
    "tags": ["array", "hash-map"],
    "step": "Arrays & Hashing",
    "order": 1,
    "companies": ["Amazon", "Google", "Microsoft", "Adobe"],
    "description": (
        "Given an array of integers `nums` and an integer `target`, return the "
        "indices of the two numbers such that they add up to `target`.\n\n"
        "You may assume that each input has **exactly one** solution, and you may "
        "not use the same element twice. You can return the answer in any order."
    ),
    "examples": [
        {
            "input": "nums = [2,7,11,15], target = 9",
            "output": "[0,1]",
            "explanation": "nums[0] + nums[1] == 9, so return [0, 1].",
        },
        {
            "input": "nums = [3,2,4], target = 6",
            "output": "[1,2]",
            "explanation": "",
        },
        {
            "input": "nums = [3,3], target = 6",
            "output": "[0,1]",
            "explanation": "",
        },
    ],
    "constraints": [
        "2 <= nums.length <= 10^4",
        "-10^9 <= nums[i] <= 10^9",
        "-10^9 <= target <= 10^9",
        "Only one valid answer exists.",
    ],
    "hints": [
        "A brute-force check of every pair works, but is there a way to avoid the nested loop?",
        "As you scan the array, what if you remembered every value you'd already seen, and where?",
        "A hash map from value → index lets you check 'have I seen target - nums[i] before?' in O(1) per element.",
    ],
    # Hand-written, not LLM-generated — a static editorial like this only ever
    # needs writing once per problem, so there's no ongoing cost either way.
    "solution_writeup": (
        "## Approach: One-pass hash map\n\n"
        "The brute-force approach checks every pair — O(n^2) time. We can do "
        "better by trading space for time.\n\n"
        "As we scan the array left to right, for each element we ask: *has "
        "the number I'd need to pair with this one already appeared?* If "
        "`nums[i]` is the current value, we need `target - nums[i]`. Keep a "
        "hash map from value seen so far → its index. Before inserting the "
        "current value, check whether `target - nums[i]` is already a key. "
        "If it is, we've found our pair immediately — no second loop needed.\n\n"
        "```python\n"
        "def two_sum(nums, target):\n"
        "    seen = {}\n"
        "    for i, n in enumerate(nums):\n"
        "        need = target - n\n"
        "        if need in seen:\n"
        "            return [seen[need], i]\n"
        "        seen[n] = i\n"
        "    return []\n"
        "```\n\n"
        "**Complexity:** O(n) time — one pass, O(1) hash map operations. "
        "O(n) space for the hash map."
    ),
    "entry_point": {"python": "two_sum", "javascript": "twoSum", "cpp": "twoSum", "java": "twoSum"},
    "params": [{"name": "nums", "type": "int_array"}, {"name": "target", "type": "int"}],
    "output_type": "int_array_sorted",
    "starter_code": {
        "python": (
            "def two_sum(nums, target):\n"
            "    # Return a list of the two indices whose values add up to target.\n"
            "    pass\n"
        ),
        "javascript": (
            "function twoSum(nums, target) {\n"
            "  // Return an array of the two indices whose values add up to target.\n"
            "}\n"
        ),
        "cpp": (
            "#include <vector>\n"
            "using namespace std;\n\n"
            "class Solution {\n"
            "public:\n"
            "    vector<int> twoSum(vector<int>& nums, int target) {\n"
            "        // Return a vector of the two indices whose values add up to target.\n"
            "        return {};\n"
            "    }\n"
            "};\n"
        ),
        "java": (
            "class Solution {\n"
            "    public int[] twoSum(int[] nums, int target) {\n"
            "        // Return an array of the two indices whose values add up to target.\n"
            "        return new int[]{};\n"
            "    }\n"
            "}\n"
        ),
    },
    # `is_sample` test cases are what "Run" uses (free, full detail shown,
    # matches the problem's own Examples) — "Submit" runs ALL of them, charges
    # credits, and records a real submission, but only shows full input/
    # expected/actual for the sample ones; hidden ones report pass/fail only,
    # so a submission can't be used to reverse-engineer the hidden suite.
    "test_cases": [
        {"input": {"nums": [2, 7, 11, 15], "target": 9}, "expected": [0, 1], "is_sample": True},
        {"input": {"nums": [3, 2, 4], "target": 6}, "expected": [1, 2], "is_sample": True},
        {"input": {"nums": [3, 3], "target": 6}, "expected": [0, 1], "is_sample": False},
        {"input": {"nums": [-1, -2, -3, -4, -5], "target": -8}, "expected": [2, 4], "is_sample": False},
        {"input": {"nums": [0, 4, 3, 0], "target": 0}, "expected": [0, 3], "is_sample": False},
    ],
}

CONTAINS_DUPLICATE_PROBLEM = {
    "_id": "contains-duplicate",
    "question_type": "code",
    "path": "DSA",
    "title": "Contains Duplicate",
    "difficulty": "Easy",
    "tags": ["array", "hash-set"],
    "step": "Arrays & Hashing",
    "order": 2,
    "companies": ["Amazon", "Google", "Apple"],
    "description": (
        "Given an integer array `nums`, return `true` if any value appears "
        "**at least twice** in the array, and `false` if every element is distinct."
    ),
    "examples": [
        {"input": "nums = [1,2,3,1]", "output": "true", "explanation": "1 appears at indices 0 and 3."},
        {"input": "nums = [1,2,3,4]", "output": "false", "explanation": "Every element is distinct."},
        {"input": "nums = [1,1,1,3,3,4,3,2,4,2]", "output": "true", "explanation": ""},
    ],
    "constraints": ["1 <= nums.length <= 10^5", "-10^9 <= nums[i] <= 10^9"],
    "hints": [
        "What data structure answers 'have I seen this value before?' in O(1)?",
        "You could also sort first, then only ever need to compare each element to its neighbor.",
    ],
    "solution_writeup": (
        "## Approach: Hash set of seen values\n\n"
        "Scan left to right, keeping a hash set of every value seen so far. "
        "If the current value is already in the set, we've found a "
        "duplicate — return `true` immediately. If the scan finishes with no "
        "repeat, return `false`.\n\n"
        "An alternative is sorting first (O(n log n)) and then checking only "
        "adjacent elements for equality — no extra space beyond the sort "
        "itself, at the cost of a slower average case. Worth mentioning if "
        "an interviewer asks for a follow-up on space.\n\n"
        "```python\n"
        "def contains_duplicate(nums):\n"
        "    seen = set()\n"
        "    for n in nums:\n"
        "        if n in seen:\n"
        "            return True\n"
        "        seen.add(n)\n"
        "    return False\n"
        "```\n\n"
        "**Complexity:** O(n) time, O(n) space with the hash-set approach "
        "(O(n log n) time, O(1) extra space with the sort-based alternative)."
    ),
    "entry_point": {
        "python": "contains_duplicate", "javascript": "containsDuplicate",
        "cpp": "containsDuplicate", "java": "containsDuplicate",
    },
    "params": [{"name": "nums", "type": "int_array"}],
    "output_type": "bool",
    "starter_code": {
        "python": (
            "def contains_duplicate(nums):\n"
            "    # Return True if any value appears at least twice in nums.\n"
            "    pass\n"
        ),
        "javascript": (
            "function containsDuplicate(nums) {\n"
            "  // Return true if any value appears at least twice in nums.\n"
            "}\n"
        ),
        "cpp": (
            "#include <vector>\n"
            "using namespace std;\n\n"
            "class Solution {\n"
            "public:\n"
            "    bool containsDuplicate(vector<int>& nums) {\n"
            "        // Return true if any value appears at least twice in nums.\n"
            "        return false;\n"
            "    }\n"
            "};\n"
        ),
        "java": (
            "class Solution {\n"
            "    public boolean containsDuplicate(int[] nums) {\n"
            "        // Return true if any value appears at least twice in nums.\n"
            "        return false;\n"
            "    }\n"
            "}\n"
        ),
    },
    "test_cases": [
        {"input": {"nums": [1, 2, 3, 1]}, "expected": True, "is_sample": True},
        {"input": {"nums": [1, 2, 3, 4]}, "expected": False, "is_sample": True},
        {"input": {"nums": [1, 1, 1, 3, 3, 4, 3, 2, 4, 2]}, "expected": True, "is_sample": False},
        {"input": {"nums": [7]}, "expected": False, "is_sample": False},
        {"input": {"nums": [5, 5]}, "expected": True, "is_sample": False},
    ],
}

VALID_ANAGRAM_PROBLEM = {
    "_id": "valid-anagram",
    "question_type": "code",
    "path": "DSA",
    "title": "Valid Anagram",
    "difficulty": "Easy",
    "tags": ["string", "hash-map"],
    "step": "Arrays & Hashing",
    "order": 3,
    "companies": ["Amazon", "Bloomberg", "Meta"],
    "description": (
        "Given two strings `s` and `t`, return `true` if `t` is an anagram of "
        "`s`, and `false` otherwise.\n\n"
        "An anagram is a word formed by rearranging the letters of another, "
        "using every original letter exactly once."
    ),
    "examples": [
        {"input": 's = "anagram", t = "nagaram"', "output": "true", "explanation": ""},
        {"input": 's = "rat", t = "car"', "output": "false", "explanation": ""},
    ],
    "constraints": [
        "1 <= s.length, t.length <= 5 * 10^4",
        "s and t consist of lowercase English letters.",
    ],
    "hints": [
        "Two strings are anagrams exactly when they have the same letter counts.",
        "A length mismatch is an instant `false` — check that first.",
        "A 26-slot count array (or a hash map, for non-lowercase alphabets) can compare counts in one pass.",
    ],
    "solution_writeup": (
        "## Approach: Character frequency count\n\n"
        "`t` is an anagram of `s` exactly when both strings have identical "
        "letter counts. First check the lengths — if they differ, it's an "
        "instant `false`. Otherwise, count each letter in `s` (+1) and each "
        "letter in `t` (-1) using a single hash map (or a fixed 26-slot "
        "array since the constraints guarantee lowercase English letters). "
        "If every count nets to zero, the strings are anagrams.\n\n"
        "```python\n"
        "def is_anagram(s, t):\n"
        "    if len(s) != len(t):\n"
        "        return False\n"
        "    counts = {}\n"
        "    for ch in s:\n"
        "        counts[ch] = counts.get(ch, 0) + 1\n"
        "    for ch in t:\n"
        "        counts[ch] = counts.get(ch, 0) - 1\n"
        "        if counts[ch] < 0:\n"
        "            return False\n"
        "    return all(v == 0 for v in counts.values())\n"
        "```\n\n"
        "**Complexity:** O(n) time, O(1) space (the count map holds at most "
        "26 entries for lowercase English letters, regardless of string length)."
    ),
    "entry_point": {"python": "is_anagram", "javascript": "isAnagram", "cpp": "isAnagram", "java": "isAnagram"},
    "params": [{"name": "s", "type": "string"}, {"name": "t", "type": "string"}],
    "output_type": "bool",
    "starter_code": {
        "python": (
            "def is_anagram(s, t):\n"
            "    # Return True if t is an anagram of s.\n"
            "    pass\n"
        ),
        "javascript": (
            "function isAnagram(s, t) {\n"
            "  // Return true if t is an anagram of s.\n"
            "}\n"
        ),
        "cpp": (
            "#include <string>\n"
            "using namespace std;\n\n"
            "class Solution {\n"
            "public:\n"
            "    bool isAnagram(string s, string t) {\n"
            "        // Return true if t is an anagram of s.\n"
            "        return false;\n"
            "    }\n"
            "};\n"
        ),
        "java": (
            "class Solution {\n"
            "    public boolean isAnagram(String s, String t) {\n"
            "        // Return true if t is an anagram of s.\n"
            "        return false;\n"
            "    }\n"
            "}\n"
        ),
    },
    "test_cases": [
        {"input": {"s": "anagram", "t": "nagaram"}, "expected": True, "is_sample": True},
        {"input": {"s": "rat", "t": "car"}, "expected": False, "is_sample": True},
        {"input": {"s": "a", "t": "ab"}, "expected": False, "is_sample": False},
        {"input": {"s": "listen", "t": "silent"}, "expected": True, "is_sample": False},
        {"input": {"s": "aacc", "t": "ccac"}, "expected": False, "is_sample": False},
    ],
}

BEST_TIME_TO_BUY_SELL_STOCK_PROBLEM = {
    "_id": "best-time-to-buy-sell-stock",
    "question_type": "code",
    "path": "DSA",
    "title": "Best Time to Buy and Sell Stock",
    "difficulty": "Easy",
    "tags": ["array", "dynamic-programming"],
    "step": "Arrays & Hashing",
    "order": 4,
    "companies": ["Amazon", "Meta", "Adobe", "Goldman Sachs"],
    "description": (
        "You are given an array `prices` where `prices[i]` is the price of a "
        "stock on day `i`.\n\n"
        "You want to maximize profit by choosing a single day to buy and a "
        "different, **later** day to sell. Return the maximum profit "
        "achievable. If no profit is possible, return `0`."
    ),
    "examples": [
        {
            "input": "prices = [7,1,5,3,6,4]",
            "output": "5",
            "explanation": "Buy on day 1 (price 1), sell on day 4 (price 6). Profit = 6 - 1 = 5.",
        },
        {
            "input": "prices = [7,6,4,3,1]",
            "output": "0",
            "explanation": "Prices only fall, so no profitable transaction is possible.",
        },
    ],
    "constraints": ["1 <= prices.length <= 10^5", "0 <= prices[i] <= 10^4"],
    "hints": [
        "The brute force checks every buy/sell pair — O(n^2). Can you track just what you need as you go?",
        "As you scan left to right, keep the lowest price seen so far — every day is a candidate sell day against it.",
        "At each day, the best possible profit if selling today is `price[i] - min_so_far`.",
    ],
    "solution_writeup": (
        "## Approach: Track the running minimum\n\n"
        "A brute-force pair check is O(n^2). Instead, scan once left to "
        "right while tracking the lowest price seen so far (`min_price`). "
        "At each day, the best profit obtainable by selling *today* is "
        "`prices[i] - min_price` — keep a running maximum of that value as "
        "you go, and update `min_price` whenever a new low appears.\n\n"
        "```python\n"
        "def max_profit(prices):\n"
        "    min_price = float('inf')\n"
        "    best = 0\n"
        "    for p in prices:\n"
        "        if p < min_price:\n"
        "            min_price = p\n"
        "        elif p - min_price > best:\n"
        "            best = p - min_price\n"
        "    return best\n"
        "```\n\n"
        "**Complexity:** O(n) time, O(1) space — a single pass, two running values."
    ),
    "entry_point": {"python": "max_profit", "javascript": "maxProfit", "cpp": "maxProfit", "java": "maxProfit"},
    "params": [{"name": "prices", "type": "int_array"}],
    "output_type": "int",
    "starter_code": {
        "python": (
            "def max_profit(prices):\n"
            "    # Return the maximum profit from one buy and one later sell.\n"
            "    pass\n"
        ),
        "javascript": (
            "function maxProfit(prices) {\n"
            "  // Return the maximum profit from one buy and one later sell.\n"
            "}\n"
        ),
        "cpp": (
            "#include <vector>\n"
            "using namespace std;\n\n"
            "class Solution {\n"
            "public:\n"
            "    int maxProfit(vector<int>& prices) {\n"
            "        // Return the maximum profit from one buy and one later sell.\n"
            "        return 0;\n"
            "    }\n"
            "};\n"
        ),
        "java": (
            "class Solution {\n"
            "    public int maxProfit(int[] prices) {\n"
            "        // Return the maximum profit from one buy and one later sell.\n"
            "        return 0;\n"
            "    }\n"
            "}\n"
        ),
    },
    "test_cases": [
        {"input": {"prices": [7, 1, 5, 3, 6, 4]}, "expected": 5, "is_sample": True},
        {"input": {"prices": [7, 6, 4, 3, 1]}, "expected": 0, "is_sample": True},
        {"input": {"prices": [1, 2, 3, 4, 5]}, "expected": 4, "is_sample": False},
        {"input": {"prices": [2, 4, 1]}, "expected": 2, "is_sample": False},
        {"input": {"prices": [3, 3, 3, 3]}, "expected": 0, "is_sample": False},
    ],
}

PRODUCT_OF_ARRAY_EXCEPT_SELF_PROBLEM = {
    "_id": "product-of-array-except-self",
    "question_type": "code",
    "path": "DSA",
    "title": "Product of Array Except Self",
    "difficulty": "Medium",
    "tags": ["array", "prefix-sum"],
    "step": "Arrays & Hashing",
    "order": 5,
    "companies": ["Amazon", "Microsoft", "Google", "Meta"],
    "description": (
        "Given an integer array `nums`, return an array `answer` such that "
        "`answer[i]` is equal to the product of every element of `nums` "
        "except `nums[i]`.\n\n"
        "You must write an algorithm that runs in O(n) time **without** "
        "using the division operator."
    ),
    "examples": [
        {"input": "nums = [1,2,3,4]", "output": "[24,12,8,6]", "explanation": ""},
        {"input": "nums = [-1,1,0,-3,3]", "output": "[0,0,9,0,0]", "explanation": ""},
    ],
    "constraints": [
        "2 <= nums.length <= 10^5",
        "-30 <= nums[i] <= 30",
        "The product of any prefix or suffix of nums fits in a 32-bit integer.",
    ],
    "hints": [
        "Division would make this trivial, but it's disallowed (and breaks if any element is 0) — what else gives you 'everything except position i'?",
        "answer[i] is the product of everything to i's LEFT times everything to i's RIGHT — compute those two passes separately.",
        "You can build the left-products in one left-to-right pass, then fold in the right-products in a second right-to-left pass, reusing the output array as scratch space to keep this O(1) extra space.",
    ],
    "solution_writeup": (
        "## Approach: Prefix and suffix products\n\n"
        "`answer[i]` is the product of everything to the left of `i` times "
        "everything to its right. Compute those two halves in two linear "
        "passes instead of dividing:\n\n"
        "1. **Left pass:** `answer[i]` = the product of all elements before "
        "`i` (with `answer[0] = 1`, since nothing is to its left).\n"
        "2. **Right pass:** walk from the end, keeping a running product of "
        "everything seen so far (to the right of the current index), and "
        "multiply it into `answer[i]`.\n\n"
        "This never divides, handles zeros correctly (a division-based "
        "approach breaks the moment any element is 0), and needs no extra "
        "array beyond the output.\n\n"
        "```python\n"
        "def product_except_self(nums):\n"
        "    n = len(nums)\n"
        "    answer = [1] * n\n"
        "    left = 1\n"
        "    for i in range(n):\n"
        "        answer[i] = left\n"
        "        left *= nums[i]\n"
        "    right = 1\n"
        "    for i in range(n - 1, -1, -1):\n"
        "        answer[i] *= right\n"
        "        right *= nums[i]\n"
        "    return answer\n"
        "```\n\n"
        "**Complexity:** O(n) time (two passes), O(1) extra space beyond the "
        "required output array."
    ),
    "entry_point": {
        "python": "product_except_self", "javascript": "productExceptSelf",
        "cpp": "productExceptSelf", "java": "productExceptSelf",
    },
    "params": [{"name": "nums", "type": "int_array"}],
    "output_type": "int_array_ordered",
    "starter_code": {
        "python": (
            "def product_except_self(nums):\n"
            "    # Return a list where result[i] is the product of every element except nums[i].\n"
            "    pass\n"
        ),
        "javascript": (
            "function productExceptSelf(nums) {\n"
            "  // Return an array where result[i] is the product of every element except nums[i].\n"
            "}\n"
        ),
        "cpp": (
            "#include <vector>\n"
            "using namespace std;\n\n"
            "class Solution {\n"
            "public:\n"
            "    vector<int> productExceptSelf(vector<int>& nums) {\n"
            "        // Return a vector where result[i] is the product of every element except nums[i].\n"
            "        return {};\n"
            "    }\n"
            "};\n"
        ),
        "java": (
            "class Solution {\n"
            "    public int[] productExceptSelf(int[] nums) {\n"
            "        // Return an array where result[i] is the product of every element except nums[i].\n"
            "        return new int[]{};\n"
            "    }\n"
            "}\n"
        ),
    },
    "test_cases": [
        {"input": {"nums": [1, 2, 3, 4]}, "expected": [24, 12, 8, 6], "is_sample": True},
        {"input": {"nums": [-1, 1, 0, -3, 3]}, "expected": [0, 0, 9, 0, 0], "is_sample": True},
        {"input": {"nums": [2, 3]}, "expected": [3, 2], "is_sample": False},
        {"input": {"nums": [1, 1, 1, 1]}, "expected": [1, 1, 1, 1], "is_sample": False},
        {"input": {"nums": [4, 0, 0]}, "expected": [0, 0, 0], "is_sample": False},
    ],
}

VALID_PALINDROME_PROBLEM = {
    "_id": "valid-palindrome",
    "question_type": "code",
    "path": "DSA",
    "title": "Valid Palindrome",
    "difficulty": "Easy",
    "tags": ["string", "two-pointers"],
    "step": "Two Pointers",
    "order": 1,
    "companies": ["Meta", "Microsoft", "Amazon"],
    "description": (
        "A phrase is a palindrome if, after converting all uppercase letters "
        "to lowercase and removing every character that isn't a letter or "
        "digit, it reads the same forwards and backwards.\n\n"
        "Given a string `s`, return `true` if it is a palindrome under these rules."
    ),
    "examples": [
        {
            "input": 's = "A man, a plan, a canal: Panama"',
            "output": "true",
            "explanation": '"amanaplanacanalpanama" is a palindrome after filtering.',
        },
        {
            "input": 's = "race a car"',
            "output": "false",
            "explanation": '"raceacar" is not a palindrome.',
        },
    ],
    "constraints": [
        "1 <= s.length <= 2 * 10^5",
        "s consists of printable ASCII characters.",
    ],
    "hints": [
        "Two pointers, one from each end, moving inward — what should each pointer do when it's sitting on a non-alphanumeric character?",
        "Compare case-insensitively; skip past punctuation and spaces on both sides before comparing.",
        "Stop as soon as the pointers cross, or as soon as a mismatch is found.",
    ],
    "solution_writeup": (
        "## Approach: Two pointers from both ends\n\n"
        "Keep a `left` pointer starting at index 0 and a `right` pointer "
        "starting at the last index. Advance `left` forward past any "
        "character that isn't alphanumeric, and move `right` backward past "
        "any character that isn't alphanumeric. Once both pointers sit on "
        "alphanumeric characters, compare them case-insensitively — if they "
        "differ, it's not a palindrome. Otherwise move both pointers inward "
        "and repeat until they meet or cross.\n\n"
        "This avoids building a whole new filtered string up front, though "
        "doing so (`''.join(c.lower() for c in s if c.isalnum())` then "
        "comparing it to its reverse) is a perfectly good O(n) alternative "
        "if clarity matters more than the extra allocation.\n\n"
        "```python\n"
        "def is_palindrome(s):\n"
        "    left, right = 0, len(s) - 1\n"
        "    while left < right:\n"
        "        while left < right and not s[left].isalnum():\n"
        "            left += 1\n"
        "        while left < right and not s[right].isalnum():\n"
        "            right -= 1\n"
        "        if s[left].lower() != s[right].lower():\n"
        "            return False\n"
        "        left += 1\n"
        "        right -= 1\n"
        "    return True\n"
        "```\n\n"
        "**Complexity:** O(n) time — each pointer visits every character at "
        "most once. O(1) extra space."
    ),
    "entry_point": {
        "python": "is_palindrome", "javascript": "isPalindrome",
        "cpp": "isPalindrome", "java": "isPalindrome",
    },
    "params": [{"name": "s", "type": "string"}],
    "output_type": "bool",
    "starter_code": {
        "python": (
            "def is_palindrome(s):\n"
            "    # Return True if s is a palindrome, ignoring case and non-alphanumeric characters.\n"
            "    pass\n"
        ),
        "javascript": (
            "function isPalindrome(s) {\n"
            "  // Return true if s is a palindrome, ignoring case and non-alphanumeric characters.\n"
            "}\n"
        ),
        "cpp": (
            "#include <string>\n"
            "#include <cctype>\n"
            "using namespace std;\n\n"
            "class Solution {\n"
            "public:\n"
            "    bool isPalindrome(string s) {\n"
            "        // Return true if s is a palindrome, ignoring case and non-alphanumeric characters.\n"
            "        return false;\n"
            "    }\n"
            "};\n"
        ),
        "java": (
            "class Solution {\n"
            "    public boolean isPalindrome(String s) {\n"
            "        // Return true if s is a palindrome, ignoring case and non-alphanumeric characters.\n"
            "        return false;\n"
            "    }\n"
            "}\n"
        ),
    },
    "test_cases": [
        {"input": {"s": "A man, a plan, a canal: Panama"}, "expected": True, "is_sample": True},
        {"input": {"s": "race a car"}, "expected": False, "is_sample": True},
        {"input": {"s": " "}, "expected": True, "is_sample": False},
        {"input": {"s": "0P"}, "expected": False, "is_sample": False},
        {"input": {"s": "ab_a"}, "expected": True, "is_sample": False},
    ],
}

TWO_SUM_II_PROBLEM = {
    "_id": "two-sum-ii-sorted",
    "question_type": "code",
    "path": "DSA",
    "title": "Two Sum II - Input Array Is Sorted",
    "difficulty": "Medium",
    "tags": ["array", "two-pointers", "binary-search"],
    "step": "Two Pointers",
    "order": 2,
    "companies": ["Amazon", "Google"],
    "description": (
        "Given a **1-indexed** array of integers `numbers` that is already "
        "sorted in non-decreasing order, find two numbers such that they add "
        "up to `target`.\n\n"
        "Return the indices, `[index1, index2]`, added by one, as an array "
        "of length two, where `1 <= index1 < index2 <= numbers.length`. You "
        "may assume each input has exactly one solution, and you may not use "
        "the same element twice."
    ),
    "examples": [
        {
            "input": "numbers = [2,7,11,15], target = 9",
            "output": "[1,2]",
            "explanation": "numbers[1] + numbers[2] == 9 (1-indexed), so return [1, 2].",
        },
        {"input": "numbers = [2,3,4], target = 6", "output": "[1,3]", "explanation": ""},
    ],
    "constraints": [
        "2 <= numbers.length <= 3 * 10^4",
        "-1000 <= numbers[i] <= 1000",
        "numbers is sorted in non-decreasing order.",
        "Only one valid answer exists.",
    ],
    "hints": [
        "The array is already sorted — that's a strong hint against the O(n) hash-map approach from Two Sum I being the intended one here.",
        "Two pointers, one at each end: if the sum is too big, which pointer should move? Too small?",
        "Move the low pointer up when the sum is too small, and the high pointer down when it's too big — this converges in a single pass with O(1) extra space.",
    ],
    "solution_writeup": (
        "## Approach: Two pointers on a sorted array\n\n"
        "Because `numbers` is already sorted, a two-pointer sweep beats the "
        "hash-map approach from Two Sum I on space (O(1) instead of O(n)). "
        "Start `left` at the beginning and `right` at the end. At each step, "
        "compare `numbers[left] + numbers[right]` to `target`:\n\n"
        "- **Too small** → the only way to increase the sum is to move "
        "`left` forward (every element from there on is >= the current one).\n"
        "- **Too big** → move `right` backward.\n"
        "- **Equal** → found it — return the 1-indexed positions.\n\n"
        "```python\n"
        "def two_sum_ii(numbers, target):\n"
        "    left, right = 0, len(numbers) - 1\n"
        "    while left < right:\n"
        "        total = numbers[left] + numbers[right]\n"
        "        if total == target:\n"
        "            return [left + 1, right + 1]\n"
        "        elif total < target:\n"
        "            left += 1\n"
        "        else:\n"
        "            right -= 1\n"
        "    return []\n"
        "```\n\n"
        "**Complexity:** O(n) time — each pointer moves at most n steps "
        "total. O(1) extra space."
    ),
    "entry_point": {
        "python": "two_sum_ii", "javascript": "twoSumII",
        "cpp": "twoSumII", "java": "twoSumII",
    },
    "params": [{"name": "numbers", "type": "int_array"}, {"name": "target", "type": "int"}],
    "output_type": "int_array_ordered",
    "starter_code": {
        "python": (
            "def two_sum_ii(numbers, target):\n"
            "    # Return the 1-indexed [index1, index2] of the two numbers that sum to target.\n"
            "    pass\n"
        ),
        "javascript": (
            "function twoSumII(numbers, target) {\n"
            "  // Return the 1-indexed [index1, index2] of the two numbers that sum to target.\n"
            "}\n"
        ),
        "cpp": (
            "#include <vector>\n"
            "using namespace std;\n\n"
            "class Solution {\n"
            "public:\n"
            "    vector<int> twoSumII(vector<int>& numbers, int target) {\n"
            "        // Return the 1-indexed [index1, index2] of the two numbers that sum to target.\n"
            "        return {};\n"
            "    }\n"
            "};\n"
        ),
        "java": (
            "class Solution {\n"
            "    public int[] twoSumII(int[] numbers, int target) {\n"
            "        // Return the 1-indexed [index1, index2] of the two numbers that sum to target.\n"
            "        return new int[]{};\n"
            "    }\n"
            "}\n"
        ),
    },
    "test_cases": [
        {"input": {"numbers": [2, 7, 11, 15], "target": 9}, "expected": [1, 2], "is_sample": True},
        {"input": {"numbers": [2, 3, 4], "target": 6}, "expected": [1, 3], "is_sample": True},
        {"input": {"numbers": [-1, 0], "target": -1}, "expected": [1, 2], "is_sample": False},
        {"input": {"numbers": [1, 2, 3, 4, 4, 9, 56, 90], "target": 8}, "expected": [4, 5], "is_sample": False},
        {"input": {"numbers": [5, 25, 75], "target": 100}, "expected": [2, 3], "is_sample": False},
    ],
}

SORTED_SQUARES_PROBLEM = {
    "_id": "squares-of-sorted-array",
    "question_type": "code",
    "path": "DSA",
    "title": "Squares of a Sorted Array",
    "difficulty": "Easy",
    "tags": ["array", "two-pointers", "sorting"],
    "step": "Two Pointers",
    "order": 3,
    "companies": ["Microsoft", "Apple"],
    "description": (
        "Given an integer array `nums` sorted in non-decreasing order, "
        "return an array of the **squares** of each number, also sorted in "
        "non-decreasing order."
    ),
    "examples": [
        {"input": "nums = [-4,-1,0,3,10]", "output": "[0,1,9,16,100]", "explanation": ""},
        {"input": "nums = [-7,-3,2,3,11]", "output": "[4,9,9,49,121]", "explanation": ""},
    ],
    "constraints": [
        "1 <= nums.length <= 10^4",
        "-10^4 <= nums[i] <= 10^4",
        "nums is sorted in non-decreasing order.",
    ],
    "hints": [
        "Squaring directly and re-sorting works, but that's O(n log n) — the input being pre-sorted should let you do better.",
        "The largest squares come from whichever end is furthest from zero — negative or positive.",
        "Fill the answer array from the back: compare the absolute values at two pointers (one at each end) and place the bigger square last each time.",
    ],
    "solution_writeup": (
        "## Approach: Two pointers, fill from the back\n\n"
        "Squaring every element and sorting is O(n log n) — but since `nums` "
        "arrives sorted, the largest square must come from whichever end "
        "(most negative or most positive) is furthest from zero. Keep a "
        "`left` pointer at the start and a `right` pointer at the end. "
        "Compare `abs(nums[left])` to `abs(nums[right])`: whichever is "
        "bigger produces the next-largest square, so place its square at "
        "the **back** of the answer array (filling it right to left) and "
        "advance that pointer inward.\n\n"
        "```python\n"
        "def sorted_squares(nums):\n"
        "    n = len(nums)\n"
        "    result = [0] * n\n"
        "    left, right = 0, n - 1\n"
        "    for i in range(n - 1, -1, -1):\n"
        "        if abs(nums[left]) > abs(nums[right]):\n"
        "            result[i] = nums[left] * nums[left]\n"
        "            left += 1\n"
        "        else:\n"
        "            result[i] = nums[right] * nums[right]\n"
        "            right -= 1\n"
        "    return result\n"
        "```\n\n"
        "**Complexity:** O(n) time, O(n) space for the output array (O(1) "
        "extra space beyond it)."
    ),
    "entry_point": {
        "python": "sorted_squares", "javascript": "sortedSquares",
        "cpp": "sortedSquares", "java": "sortedSquares",
    },
    "params": [{"name": "nums", "type": "int_array"}],
    "output_type": "int_array_ordered",
    "starter_code": {
        "python": (
            "def sorted_squares(nums):\n"
            "    # Return the squares of nums, sorted in non-decreasing order.\n"
            "    pass\n"
        ),
        "javascript": (
            "function sortedSquares(nums) {\n"
            "  // Return the squares of nums, sorted in non-decreasing order.\n"
            "}\n"
        ),
        "cpp": (
            "#include <vector>\n"
            "#include <cmath>\n"
            "using namespace std;\n\n"
            "class Solution {\n"
            "public:\n"
            "    vector<int> sortedSquares(vector<int>& nums) {\n"
            "        // Return the squares of nums, sorted in non-decreasing order.\n"
            "        return {};\n"
            "    }\n"
            "};\n"
        ),
        "java": (
            "class Solution {\n"
            "    public int[] sortedSquares(int[] nums) {\n"
            "        // Return the squares of nums, sorted in non-decreasing order.\n"
            "        return new int[]{};\n"
            "    }\n"
            "}\n"
        ),
    },
    "test_cases": [
        {"input": {"nums": [-4, -1, 0, 3, 10]}, "expected": [0, 1, 9, 16, 100], "is_sample": True},
        {"input": {"nums": [-7, -3, 2, 3, 11]}, "expected": [4, 9, 9, 49, 121], "is_sample": True},
        {"input": {"nums": [-5, -3, -2, -1]}, "expected": [1, 4, 9, 25], "is_sample": False},
        {"input": {"nums": [0]}, "expected": [0], "is_sample": False},
        {"input": {"nums": [-2, -1, 0, 1, 2]}, "expected": [0, 1, 1, 4, 4], "is_sample": False},
    ],
}

BINARY_SEARCH_PROBLEM = {
    "_id": "binary-search",
    "question_type": "code",
    "path": "DSA",
    "title": "Binary Search",
    "difficulty": "Easy",
    "tags": ["array", "binary-search"],
    "step": "Binary Search",
    "order": 1,
    "companies": ["Google", "Amazon", "Bloomberg"],
    "description": (
        "Given a sorted (ascending) array of distinct integers `nums` and a "
        "`target` value, return the index of `target` in `nums`, or `-1` if "
        "it isn't present.\n\n"
        "Your algorithm must run in O(log n) time."
    ),
    "examples": [
        {"input": "nums = [-1,0,3,5,9,12], target = 9", "output": "4", "explanation": "9 is at index 4."},
        {"input": "nums = [-1,0,3,5,9,12], target = 2", "output": "-1", "explanation": "2 does not exist, so return -1."},
    ],
    "constraints": [
        "1 <= nums.length <= 10^4",
        "-10^4 < nums[i], target < 10^4",
        "All the integers in nums are unique, sorted in ascending order.",
    ],
    "hints": [
        "O(log n) on a sorted array is the classic signal for binary search.",
        "Keep a low and high pointer; check the midpoint and discard the half that can't contain the target.",
        "Watch the loop condition (`low <= high`) and the midpoint update — off-by-one errors here are the most common bug in this problem.",
    ],
    "solution_writeup": (
        "## Approach: Classic binary search\n\n"
        "Maintain `low` and `high` bounds spanning the whole array. At each "
        "step, look at the midpoint `mid = (low + high) // 2`:\n\n"
        "- If `nums[mid] == target`, we're done — return `mid`.\n"
        "- If `nums[mid] < target`, the target (if present) must be to the "
        "right, so move `low = mid + 1`.\n"
        "- Otherwise, move `high = mid - 1`.\n\n"
        "Repeat while `low <= high`. If the loop ends without finding a "
        "match, the target isn't in the array — return `-1`.\n\n"
        "```python\n"
        "def search(nums, target):\n"
        "    low, high = 0, len(nums) - 1\n"
        "    while low <= high:\n"
        "        mid = (low + high) // 2\n"
        "        if nums[mid] == target:\n"
        "            return mid\n"
        "        elif nums[mid] < target:\n"
        "            low = mid + 1\n"
        "        else:\n"
        "            high = mid - 1\n"
        "    return -1\n"
        "```\n\n"
        "**Complexity:** O(log n) time — the search space halves each "
        "iteration. O(1) space."
    ),
    "entry_point": {"python": "search", "javascript": "search", "cpp": "search", "java": "search"},
    "params": [{"name": "nums", "type": "int_array"}, {"name": "target", "type": "int"}],
    "output_type": "int",
    "starter_code": {
        "python": (
            "def search(nums, target):\n"
            "    # Return the index of target in the sorted nums, or -1 if not present.\n"
            "    pass\n"
        ),
        "javascript": (
            "function search(nums, target) {\n"
            "  // Return the index of target in the sorted nums, or -1 if not present.\n"
            "}\n"
        ),
        "cpp": (
            "#include <vector>\n"
            "using namespace std;\n\n"
            "class Solution {\n"
            "public:\n"
            "    int search(vector<int>& nums, int target) {\n"
            "        // Return the index of target in the sorted nums, or -1 if not present.\n"
            "        return -1;\n"
            "    }\n"
            "};\n"
        ),
        "java": (
            "class Solution {\n"
            "    public int search(int[] nums, int target) {\n"
            "        // Return the index of target in the sorted nums, or -1 if not present.\n"
            "        return -1;\n"
            "    }\n"
            "}\n"
        ),
    },
    "test_cases": [
        {"input": {"nums": [-1, 0, 3, 5, 9, 12], "target": 9}, "expected": 4, "is_sample": True},
        {"input": {"nums": [-1, 0, 3, 5, 9, 12], "target": 2}, "expected": -1, "is_sample": True},
        {"input": {"nums": [5], "target": 5}, "expected": 0, "is_sample": False},
        {"input": {"nums": [2, 5], "target": 5}, "expected": 1, "is_sample": False},
        {"input": {"nums": [1, 3, 5, 7, 9, 11], "target": 1}, "expected": 0, "is_sample": False},
    ],
}

SEARCH_INSERT_POSITION_PROBLEM = {
    "_id": "search-insert-position",
    "question_type": "code",
    "path": "DSA",
    "title": "Search Insert Position",
    "difficulty": "Easy",
    "tags": ["array", "binary-search"],
    "step": "Binary Search",
    "order": 2,
    "companies": ["Amazon", "Microsoft"],
    "description": (
        "Given a sorted array of distinct integers `nums` and a `target` "
        "value, return the index if `target` is found. If not, return the "
        "index where it would be inserted, keeping the array sorted.\n\n"
        "Your algorithm must run in O(log n) time."
    ),
    "examples": [
        {"input": "nums = [1,3,5,6], target = 5", "output": "2", "explanation": "5 is present at index 2."},
        {"input": "nums = [1,3,5,6], target = 2", "output": "1", "explanation": "2 would be inserted at index 1, between 1 and 3."},
    ],
    "constraints": [
        "1 <= nums.length <= 10^4",
        "-10^4 <= nums[i], target <= 10^4",
        "nums contains distinct values sorted in ascending order.",
    ],
    "hints": [
        "This is Binary Search's close cousin — same O(log n) shape, different question when the target isn't found.",
        "Binary search as usual; when the loop ends without a match, one of your two bounds is exactly the insert position.",
        "When `low > high` at the end, `low` is always the first index whose value is >= target — that IS the insert position.",
    ],
    "solution_writeup": (
        "## Approach: Binary search for the lower bound\n\n"
        "Run the same binary search as in the plain Binary Search problem. "
        "The twist is what to do when the loop ends without an exact match: "
        "at that point, `low` has converged to exactly the first index whose "
        "value is `>= target` — which is precisely where `target` belongs "
        "to keep the array sorted, whether or not it was already present.\n\n"
        "```python\n"
        "def search_insert(nums, target):\n"
        "    low, high = 0, len(nums) - 1\n"
        "    while low <= high:\n"
        "        mid = (low + high) // 2\n"
        "        if nums[mid] == target:\n"
        "            return mid\n"
        "        elif nums[mid] < target:\n"
        "            low = mid + 1\n"
        "        else:\n"
        "            high = mid - 1\n"
        "    return low\n"
        "```\n\n"
        "**Complexity:** O(log n) time, O(1) space — identical shape to Binary Search."
    ),
    "entry_point": {
        "python": "search_insert", "javascript": "searchInsert",
        "cpp": "searchInsert", "java": "searchInsert",
    },
    "params": [{"name": "nums", "type": "int_array"}, {"name": "target", "type": "int"}],
    "output_type": "int",
    "starter_code": {
        "python": (
            "def search_insert(nums, target):\n"
            "    # Return the index of target, or where it would be inserted to stay sorted.\n"
            "    pass\n"
        ),
        "javascript": (
            "function searchInsert(nums, target) {\n"
            "  // Return the index of target, or where it would be inserted to stay sorted.\n"
            "}\n"
        ),
        "cpp": (
            "#include <vector>\n"
            "using namespace std;\n\n"
            "class Solution {\n"
            "public:\n"
            "    int searchInsert(vector<int>& nums, int target) {\n"
            "        // Return the index of target, or where it would be inserted to stay sorted.\n"
            "        return 0;\n"
            "    }\n"
            "};\n"
        ),
        "java": (
            "class Solution {\n"
            "    public int searchInsert(int[] nums, int target) {\n"
            "        // Return the index of target, or where it would be inserted to stay sorted.\n"
            "        return 0;\n"
            "    }\n"
            "}\n"
        ),
    },
    "test_cases": [
        {"input": {"nums": [1, 3, 5, 6], "target": 5}, "expected": 2, "is_sample": True},
        {"input": {"nums": [1, 3, 5, 6], "target": 2}, "expected": 1, "is_sample": True},
        {"input": {"nums": [1, 3, 5, 6], "target": 7}, "expected": 4, "is_sample": False},
        {"input": {"nums": [1, 3, 5, 6], "target": 0}, "expected": 0, "is_sample": False},
        {"input": {"nums": [1], "target": 1}, "expected": 0, "is_sample": False},
    ],
}

SQRT_X_PROBLEM = {
    "_id": "sqrt-x",
    "question_type": "code",
    "path": "DSA",
    "title": "Sqrt(x)",
    "difficulty": "Easy",
    "tags": ["math", "binary-search"],
    "step": "Binary Search",
    "order": 3,
    "companies": ["Facebook", "Google"],
    "description": (
        "Given a non-negative integer `x`, return the square root of `x` "
        "**rounded down** to the nearest integer.\n\n"
        "You may not use any built-in exponent or square-root function."
    ),
    "examples": [
        {"input": "x = 4", "output": "2", "explanation": ""},
        {"input": "x = 8", "output": "2", "explanation": "sqrt(8) is ~2.83, rounded down to 2."},
    ],
    "constraints": ["0 <= x <= 2^31 - 1"],
    "hints": [
        "The answer is monotonic — as the candidate answer increases, its square only ever increases too. That monotonicity is what makes binary search applicable.",
        "Binary search on the ANSWER itself, from 0 to x: for a candidate mid, is mid*mid too big, too small, or a match?",
        "Since no exact integer square root may exist, track the largest mid whose square is <= x as you narrow the range.",
    ],
    "solution_writeup": (
        "## Approach: Binary search on the answer\n\n"
        "Rather than searching an array, binary search directly over the "
        "range of possible answers `[0, x]`. For a candidate `mid`, compare "
        "`mid * mid` to `x`:\n\n"
        "- If `mid * mid == x`, `mid` is the exact answer.\n"
        "- If `mid * mid < x`, `mid` is a valid (possibly non-optimal) "
        "answer — record it and search higher.\n"
        "- If `mid * mid > x`, `mid` is too big — search lower.\n\n"
        "Because most `x` don't have an exact integer square root, track "
        "the best (largest) `mid` found with `mid * mid <= x` as the search "
        "narrows, and return that once the range is exhausted.\n\n"
        "```python\n"
        "def my_sqrt(x):\n"
        "    if x < 2:\n"
        "        return x\n"
        "    low, high = 1, x\n"
        "    ans = 1\n"
        "    while low <= high:\n"
        "        mid = (low + high) // 2\n"
        "        if mid * mid == x:\n"
        "            return mid\n"
        "        elif mid * mid < x:\n"
        "            ans = mid\n"
        "            low = mid + 1\n"
        "        else:\n"
        "            high = mid - 1\n"
        "    return ans\n"
        "```\n\n"
        "**Complexity:** O(log x) time, O(1) space."
    ),
    "entry_point": {"python": "my_sqrt", "javascript": "mySqrt", "cpp": "mySqrt", "java": "mySqrt"},
    "params": [{"name": "x", "type": "int"}],
    "output_type": "int",
    "starter_code": {
        "python": (
            "def my_sqrt(x):\n"
            "    # Return floor(sqrt(x)) without using a built-in sqrt/exponent function.\n"
            "    pass\n"
        ),
        "javascript": (
            "function mySqrt(x) {\n"
            "  // Return floor(sqrt(x)) without using a built-in sqrt/exponent function.\n"
            "}\n"
        ),
        "cpp": (
            "class Solution {\n"
            "public:\n"
            "    int mySqrt(int x) {\n"
            "        // Return floor(sqrt(x)) without using a built-in sqrt/exponent function.\n"
            "        return 0;\n"
            "    }\n"
            "};\n"
        ),
        "java": (
            "class Solution {\n"
            "    public int mySqrt(int x) {\n"
            "        // Return floor(sqrt(x)) without using a built-in sqrt/exponent function.\n"
            "        return 0;\n"
            "    }\n"
            "}\n"
        ),
    },
    "test_cases": [
        {"input": {"x": 4}, "expected": 2, "is_sample": True},
        {"input": {"x": 8}, "expected": 2, "is_sample": True},
        {"input": {"x": 0}, "expected": 0, "is_sample": False},
        {"input": {"x": 1}, "expected": 1, "is_sample": False},
        {"input": {"x": 2147395599}, "expected": 46339, "is_sample": False},
    ],
}

# ---------------------------------------------------------------------------
# SQL path — `question_type: "sql"`. A small, hand-seeded SQLite sample
# database per problem (`schema_sql`: CREATE TABLE + INSERT statements run
# fresh, in-memory, on every grading call — see `_sql_execute`/
# `run_sql_submission` below), a hand-written `solution_query` (the reference
# query, executed at grading time to derive ground truth — never a manually
# transcribed "expected rows" list that could drift from the schema), and an
# `order_sensitive` flag: most of these problems are correct regardless of
# row order (a plain SELECT describes a SET), but "top N by X" problems have
# a genuine positional answer (the same 3 rows in the wrong order is wrong),
# so comparison respects that per-problem instead of always sorting.
# ---------------------------------------------------------------------------
COMBINE_TWO_TABLES_PROBLEM = {
    "_id": "sql-combine-two-tables",
    "question_type": "sql",
    "path": "SQL",
    "title": "Combine Two Tables",
    "difficulty": "Easy",
    "tags": ["sql", "join"],
    "step": "Joins",
    "order": 1,
    "companies": ["Amazon", "Meta"],
    "description": (
        "You're given two tables:\n\n"
        "- `Person(person_id, first_name, last_name)`\n"
        "- `Address(address_id, person_id, city, state)`\n\n"
        "Write a query to report the first name, last name, city, and state of "
        "every person in `Person`. If a person has no matching row in "
        "`Address`, report `city`/`state` as `NULL` — every person must appear "
        "exactly once, regardless of whether they have an address on file."
    ),
    "examples": [
        {
            "input": "Person(1, 'Wang', 'Allen'), (2, 'Alice', 'Bob') / Address(1, 2, 'New York City', 'New York')",
            "output": "('Allen', 'Wang', NULL, NULL), ('Alice', 'Bob', 'New York City', 'New York')",
            "explanation": "Person 1 (Allen Wang) has no row in Address, so city/state come back NULL.",
        },
    ],
    "constraints": ["Every person_id in Person is unique.", "Not every person has a row in Address."],
    "hints": [
        "An INNER JOIN would silently drop people with no address — that's exactly the bug this problem is designed to catch.",
        "A LEFT JOIN from Person to Address keeps every person, filling unmatched columns with NULL.",
    ],
    "solution_writeup": (
        "## Approach: LEFT JOIN from the table that must never lose rows\n\n"
        "The requirement 'every person must appear exactly once' is the "
        "signal for a `LEFT JOIN`, not an `INNER JOIN` — an inner join would "
        "silently drop anyone without a matching address row, which is "
        "wrong here. Join FROM `Person` (the table whose rows are "
        "mandatory) TO `Address` (the optional side); any person with no "
        "match gets `NULL` for `city`/`state` automatically.\n\n"
        "```sql\n"
        "SELECT p.first_name, p.last_name, a.city, a.state\n"
        "FROM Person p\n"
        "LEFT JOIN Address a ON p.person_id = a.person_id;\n"
        "```"
    ),
    "schema_sql": (
        "CREATE TABLE Person (person_id INTEGER PRIMARY KEY, first_name TEXT, last_name TEXT);\n"
        "CREATE TABLE Address (address_id INTEGER PRIMARY KEY, person_id INTEGER, city TEXT, state TEXT);\n"
        "INSERT INTO Person VALUES (1, 'Wang', 'Allen'), (2, 'Alice', 'Bob'), (3, 'Ford', 'Kim');\n"
        "INSERT INTO Address VALUES (1, 2, 'New York City', 'New York'), (2, 3, 'Seattle', 'Washington');\n"
    ),
    "solution_query": (
        "SELECT p.first_name, p.last_name, a.city, a.state "
        "FROM Person p LEFT JOIN Address a ON p.person_id = a.person_id;"
    ),
    "order_sensitive": False,
    "starter_code": {"sql": "-- Return first_name, last_name, city, state for every person.\nSELECT\n"},
}

SECOND_HIGHEST_SALARY_PROBLEM = {
    "_id": "sql-second-highest-salary",
    "question_type": "sql",
    "path": "SQL",
    "title": "Second Highest Salary",
    "difficulty": "Medium",
    "tags": ["sql", "aggregation", "subquery"],
    "step": "Aggregation",
    "order": 1,
    "companies": ["Amazon", "Bloomberg"],
    "description": (
        "Table `Employee(id, salary)`. Write a query to return the **second "
        "highest** distinct salary. If there is no second highest salary "
        "(fewer than 2 distinct salaries exist), return `NULL`."
    ),
    "examples": [
        {"input": "Employee: (1,100), (2,200), (3,300)", "output": "200", "explanation": ""},
        {"input": "Employee: (1,100)", "output": "NULL", "explanation": "Only one distinct salary exists."},
    ],
    "constraints": ["salary can repeat across employees."],
    "hints": [
        "MAX(salary) gets you the highest — how do you exclude just that one value and ask MAX again?",
        "A subquery that finds the max salary strictly LESS THAN the overall max IS the second highest.",
        "This naturally returns NULL (not an error) when no such row exists — no special-casing needed.",
    ],
    "solution_writeup": (
        "## Approach: Max of everything below the max\n\n"
        "The second highest distinct salary is exactly `MAX(salary) WHERE "
        "salary < (the overall MAX(salary))`. If there's only one distinct "
        "salary, that subquery matches zero rows, and `MAX()` over zero rows "
        "returns `NULL` in standard SQL — which is exactly the required "
        "behavior, with no `CASE`/`COALESCE` needed.\n\n"
        "```sql\n"
        "SELECT MAX(salary) AS SecondHighestSalary\n"
        "FROM Employee\n"
        "WHERE salary < (SELECT MAX(salary) FROM Employee);\n"
        "```"
    ),
    "schema_sql": (
        "CREATE TABLE Employee (id INTEGER PRIMARY KEY, salary INTEGER);\n"
        "INSERT INTO Employee VALUES (1, 100), (2, 200), (3, 300);\n"
    ),
    "solution_query": (
        "SELECT MAX(salary) AS SecondHighestSalary FROM Employee "
        "WHERE salary < (SELECT MAX(salary) FROM Employee);"
    ),
    "order_sensitive": False,
    "starter_code": {"sql": "-- Return the second highest DISTINCT salary, or NULL.\nSELECT\n"},
}

DUPLICATE_EMAILS_PROBLEM = {
    "_id": "sql-duplicate-emails",
    "question_type": "sql",
    "path": "SQL",
    "title": "Duplicate Emails",
    "difficulty": "Easy",
    "tags": ["sql", "aggregation", "group-by"],
    "step": "Aggregation",
    "order": 2,
    "companies": ["Amazon", "Google"],
    "description": (
        "Table `Person(id, email)`. Write a query to report every email "
        "address that appears **more than once**. Each duplicate email "
        "should appear only once in the result, regardless of how many "
        "times it repeats in the table."
    ),
    "examples": [
        {
            "input": "Person: (1,'a@b.com'), (2,'c@d.com'), (3,'a@b.com')",
            "output": "('a@b.com')",
            "explanation": "a@b.com appears twice; c@d.com appears once and is excluded.",
        },
    ],
    "constraints": [],
    "hints": [
        "Group by the value you're checking for repeats, and count.",
        "HAVING filters on a GROUP BY's aggregate — that's exactly count > 1.",
    ],
    "solution_writeup": (
        "## Approach: GROUP BY + HAVING\n\n"
        "Group rows by `email`, then keep only the groups whose count "
        "exceeds 1 — `HAVING` filters on the aggregate itself, which `WHERE` "
        "can't do (WHERE runs before grouping).\n\n"
        "```sql\n"
        "SELECT email\n"
        "FROM Person\n"
        "GROUP BY email\n"
        "HAVING COUNT(*) > 1;\n"
        "```"
    ),
    "schema_sql": (
        "CREATE TABLE Person (id INTEGER PRIMARY KEY, email TEXT);\n"
        "INSERT INTO Person VALUES (1, 'a@b.com'), (2, 'c@d.com'), (3, 'a@b.com'), (4, 'e@f.com');\n"
    ),
    "solution_query": "SELECT email FROM Person GROUP BY email HAVING COUNT(*) > 1;",
    "order_sensitive": False,
    "starter_code": {"sql": "-- Return every email that appears more than once (each shown only once).\nSELECT\n"},
}

EMPLOYEES_EARNING_MORE_THAN_MANAGERS_PROBLEM = {
    "_id": "sql-employees-earning-more-than-managers",
    "question_type": "sql",
    "path": "SQL",
    "title": "Employees Earning More Than Their Managers",
    "difficulty": "Medium",
    "tags": ["sql", "join", "self-join"],
    "step": "Joins",
    "order": 2,
    "companies": ["Amazon", "Microsoft"],
    "description": (
        "Table `Employee(id, name, salary, managerId)` — `managerId` is "
        "`NULL` for employees with no manager, otherwise it refers to "
        "another row's `id` in the same table. Write a query to report the "
        "`name` of every employee who earns **more** than their manager."
    ),
    "examples": [
        {
            "input": "Employee: (1,'Joe',70000,3), (2,'Henry',80000,4), (3,'Sam',60000,NULL), (4,'Max',90000,NULL)",
            "output": "('Joe')",
            "explanation": "Joe (70000) earns more than manager Sam (60000). Henry (80000) does not out-earn Max (90000).",
        },
    ],
    "constraints": ["managerId may be NULL."],
    "hints": [
        "This table refers to itself — you need TWO aliased copies of it in the same query.",
        "Join the employee copy's managerId to the manager copy's id, then compare the two salary columns.",
    ],
    "solution_writeup": (
        "## Approach: Self-join on managerId = id\n\n"
        "Since manager info lives in the SAME table as the employee it "
        "refers to, join the table to itself with two aliases: one row "
        "representing the employee (`e`), one representing their manager "
        "(`m`), matched via `e.managerId = m.id`. An inner join here is "
        "correct (and intentional) — someone with `managerId IS NULL` has "
        "no matching manager row and is correctly excluded, since they "
        "can't 'earn more than a manager' that doesn't exist.\n\n"
        "```sql\n"
        "SELECT e.name\n"
        "FROM Employee e\n"
        "JOIN Employee m ON e.managerId = m.id\n"
        "WHERE e.salary > m.salary;\n"
        "```"
    ),
    "schema_sql": (
        "CREATE TABLE Employee (id INTEGER PRIMARY KEY, name TEXT, salary INTEGER, managerId INTEGER);\n"
        "INSERT INTO Employee VALUES (1, 'Joe', 70000, 3), (2, 'Henry', 80000, 4), "
        "(3, 'Sam', 60000, NULL), (4, 'Max', 90000, NULL);\n"
    ),
    "solution_query": (
        "SELECT e.name FROM Employee e JOIN Employee m ON e.managerId = m.id WHERE e.salary > m.salary;"
    ),
    "order_sensitive": False,
    "starter_code": {"sql": "-- Return the name of every employee who earns more than their manager.\nSELECT\n"},
}

CUSTOMERS_WHO_NEVER_ORDER_PROBLEM = {
    "_id": "sql-customers-who-never-order",
    "question_type": "sql",
    "path": "SQL",
    "title": "Customers Who Never Order",
    "difficulty": "Easy",
    "tags": ["sql", "join", "anti-join"],
    "step": "Joins",
    "order": 3,
    "companies": ["Amazon", "Adobe"],
    "description": (
        "Tables `Customers(id, name)` and `Orders(id, customerId)`. Write a "
        "query to report the names of customers who never placed **any** order."
    ),
    "examples": [
        {
            "input": "Customers: (1,'Joe'), (2,'Henry'), (3,'Sam') / Orders: (1,3)",
            "output": "('Joe'), ('Henry')",
            "explanation": "Only Sam (id 3) has a row in Orders.",
        },
    ],
    "constraints": [],
    "hints": [
        "This is the classic 'find rows on the left with no match on the right' shape — an anti-join.",
        "A LEFT JOIN from Customers to Orders, then filtering for WHERE the Orders side is NULL, finds exactly the unmatched customers.",
    ],
    "solution_writeup": (
        "## Approach: LEFT JOIN + IS NULL (anti-join)\n\n"
        "Left join `Customers` to `Orders` on the customer id. Any customer "
        "with at least one order gets one or more matched rows; a customer "
        "with NO orders gets exactly one row with every `Orders` column "
        "`NULL`. Filtering for `Orders.id IS NULL` isolates exactly those "
        "customers — the standard SQL 'anti-join' pattern.\n\n"
        "```sql\n"
        "SELECT c.name AS Customers\n"
        "FROM Customers c\n"
        "LEFT JOIN Orders o ON c.id = o.customerId\n"
        "WHERE o.id IS NULL;\n"
        "```"
    ),
    "schema_sql": (
        "CREATE TABLE Customers (id INTEGER PRIMARY KEY, name TEXT);\n"
        "CREATE TABLE Orders (id INTEGER PRIMARY KEY, customerId INTEGER);\n"
        "INSERT INTO Customers VALUES (1, 'Joe'), (2, 'Henry'), (3, 'Sam');\n"
        "INSERT INTO Orders VALUES (1, 3);\n"
    ),
    "solution_query": (
        "SELECT c.name AS Customers FROM Customers c LEFT JOIN Orders o ON c.id = o.customerId WHERE o.id IS NULL;"
    ),
    "order_sensitive": False,
    "starter_code": {"sql": "-- Return the names of customers who never placed an order.\nSELECT\n"},
}

STUDENTS_ABOVE_AVERAGE_PROBLEM = {
    "_id": "sql-students-above-average",
    "question_type": "sql",
    "path": "SQL",
    "title": "Students Scoring Above the Class Average",
    "difficulty": "Medium",
    "tags": ["sql", "subquery", "aggregation"],
    "step": "Subqueries",
    "order": 1,
    "companies": ["Google"],
    "description": (
        "Table `Scores(student_id, name, score)`. Write a query to report "
        "the `name` of every student whose `score` is **strictly greater** "
        "than the average `score` across all students."
    ),
    "examples": [
        {
            "input": "Scores: (1,'Ann',90), (2,'Bo',60), (3,'Cy',75)",
            "output": "('Ann')",
            "explanation": "Average is 75. Only Ann (90) is strictly above it — Cy (75) ties the average, not above it.",
        },
    ],
    "constraints": [],
    "hints": [
        "You need the class average as a single number before you can compare anything to it.",
        "A scalar subquery in the WHERE clause computes that average once, then every row's score is compared against it.",
    ],
    "solution_writeup": (
        "## Approach: Scalar subquery for the class average\n\n"
        "Compute `AVG(score)` across the whole table as a scalar subquery, "
        "then filter rows whose own `score` exceeds it. Note **strictly** "
        "greater — a student exactly at the average doesn't qualify.\n\n"
        "```sql\n"
        "SELECT name\n"
        "FROM Scores\n"
        "WHERE score > (SELECT AVG(score) FROM Scores);\n"
        "```"
    ),
    "schema_sql": (
        "CREATE TABLE Scores (student_id INTEGER PRIMARY KEY, name TEXT, score REAL);\n"
        "INSERT INTO Scores VALUES (1, 'Ann', 90), (2, 'Bo', 60), (3, 'Cy', 75), (4, 'Dee', 81);\n"
    ),
    "solution_query": "SELECT name FROM Scores WHERE score > (SELECT AVG(score) FROM Scores);",
    "order_sensitive": False,
    "starter_code": {"sql": "-- Return the name of every student scoring strictly above the class average.\nSELECT\n"},
}

TOP_THREE_PAID_EMPLOYEES_PROBLEM = {
    "_id": "sql-top-three-paid-employees",
    "question_type": "sql",
    "path": "SQL",
    "title": "Top 3 Highest-Paid Employees",
    "difficulty": "Medium",
    "tags": ["sql", "order-by", "limit"],
    "step": "Sorting & Limiting",
    "order": 1,
    "companies": ["Amazon", "Meta", "Microsoft"],
    "description": (
        "Table `Employee(id, name, salary)`. Write a query returning the "
        "`name` of the **3 highest-paid** employees, **ordered from highest "
        "salary to lowest**. Assume all salaries are distinct.\n\n"
        "Order matters here: returning the correct 3 names in the wrong "
        "order is an incorrect answer, not just an incorrect style choice."
    ),
    "examples": [
        {
            "input": "Employee: (1,'A',500),(2,'B',900),(3,'C',700),(4,'D',300)",
            "output": "('B'), ('C'), ('A')",
            "explanation": "900, 700, 500 — highest to lowest.",
        },
    ],
    "constraints": ["All salaries are distinct."],
    "hints": [
        "Sort first, then take only as many rows as you need.",
        "ORDER BY ... DESC followed by LIMIT 3 is the whole solution.",
    ],
    "solution_writeup": (
        "## Approach: ORDER BY DESC + LIMIT\n\n"
        "Sort by `salary` descending, then keep only the first 3 rows. "
        "Unlike most of the other SQL problems here (which describe an "
        "unordered SET of correct rows), this result is inherently "
        "positional — the SAME three names in ascending order would be a "
        "different, wrong answer.\n\n"
        "```sql\n"
        "SELECT name\n"
        "FROM Employee\n"
        "ORDER BY salary DESC\n"
        "LIMIT 3;\n"
        "```"
    ),
    "schema_sql": (
        "CREATE TABLE Employee (id INTEGER PRIMARY KEY, name TEXT, salary INTEGER);\n"
        "INSERT INTO Employee VALUES (1, 'Ann', 500), (2, 'Bo', 900), (3, 'Cy', 700), (4, 'Dee', 300), (5, 'Eli', 450);\n"
    ),
    "solution_query": "SELECT name FROM Employee ORDER BY salary DESC LIMIT 3;",
    "order_sensitive": True,
    "starter_code": {"sql": "-- Return the top 3 highest-paid employees' names, highest salary first.\nSELECT\n"},
}

SQL_PROBLEMS = [
    COMBINE_TWO_TABLES_PROBLEM,
    SECOND_HIGHEST_SALARY_PROBLEM,
    DUPLICATE_EMAILS_PROBLEM,
    EMPLOYEES_EARNING_MORE_THAN_MANAGERS_PROBLEM,
    CUSTOMERS_WHO_NEVER_ORDER_PROBLEM,
    STUDENTS_ABOVE_AVERAGE_PROBLEM,
    TOP_THREE_PAID_EMPLOYEES_PROBLEM,
]


# ---------------------------------------------------------------------------
# Logical Reasoning path — `question_type: "mcq"`. Classic verbal/analytical
# reasoning aptitude questions (single-select), graded by trivial equality —
# see `grade_mcq` below. `options` is an ordered list of {"id", "text"};
# `correct_option_id` is server-side only (never sent to the client before a
# submission — see `_to_public_problem_detail`).
# ---------------------------------------------------------------------------
BLOOD_RELATION_PROBLEM = {
    "_id": "lr-blood-relation-1",
    "question_type": "mcq",
    "path": "Logical Reasoning",
    "title": "Blood Relations: Pointing at the Photograph",
    "difficulty": "Easy",
    "tags": ["logical-reasoning", "blood-relations"],
    "step": "Verbal Reasoning",
    "order": 1,
    "companies": [],
    "description": (
        "Pointing to a photograph, a man says, \"She is the daughter of my "
        "grandfather's only son.\" How is the woman in the photograph "
        "related to the man?"
    ),
    "options": [
        {"id": "a", "text": "Sister"},
        {"id": "b", "text": "Daughter"},
        {"id": "c", "text": "Cousin"},
        {"id": "d", "text": "Mother"},
    ],
    "correct_option_id": "a",
    "solution_writeup": (
        "The man's grandfather's only son is the man's own father (since "
        "the grandfather has only one son). So \"daughter of my "
        "grandfather's only son\" = \"daughter of my father\" = the man's "
        "**sister**. (If the man had said 'my grandfather's son' without "
        "'only', it could ambiguously include the man himself as a possible "
        "son, but 'only son' pins it down uniquely to the father.)"
    ),
}

SYLLOGISM_PROBLEM = {
    "_id": "lr-syllogism-1",
    "question_type": "mcq",
    "path": "Logical Reasoning",
    "title": "Syllogism: Valid Conclusion",
    "difficulty": "Medium",
    "tags": ["logical-reasoning", "syllogism"],
    "step": "Verbal Reasoning",
    "order": 2,
    "companies": [],
    "description": (
        "Statements:\n"
        "1. All pens are pencils.\n"
        "2. All pencils are erasers.\n\n"
        "Which conclusion follows definitely from the two statements?"
    ),
    "options": [
        {"id": "a", "text": "All erasers are pens"},
        {"id": "b", "text": "All pens are erasers"},
        {"id": "c", "text": "No pen is an eraser"},
        {"id": "d", "text": "Some erasers are not pencils"},
    ],
    "correct_option_id": "b",
    "solution_writeup": (
        "This is a straightforward chain: pens ⊆ pencils, and pencils ⊆ "
        "erasers, therefore pens ⊆ erasers — **\"All pens are erasers\"** "
        "follows with certainty. Option (a) reverses the direction of the "
        "chain (not guaranteed); (c) directly contradicts the valid "
        "conclusion; (d) isn't supported — the statements say nothing about "
        "erasers that AREN'T pencils."
    ),
}

CODING_DECODING_PROBLEM = {
    "_id": "lr-coding-decoding-1",
    "question_type": "mcq",
    "path": "Logical Reasoning",
    "title": "Coding-Decoding: Letter Shift Cipher",
    "difficulty": "Easy",
    "tags": ["logical-reasoning", "coding-decoding"],
    "step": "Verbal Reasoning",
    "order": 3,
    "companies": [],
    "description": (
        "In a certain code, \"TRAIN\" is written as \"UQBHO\". How is "
        "\"CHAIR\" written in that same code?"
    ),
    "options": [
        {"id": "a", "text": "DGBHS"},
        {"id": "b", "text": "DIBJS"},
        {"id": "c", "text": "BGZHQ"},
        {"id": "d", "text": "DGZHS"},
    ],
    "correct_option_id": "a",
    "solution_writeup": (
        "Compare TRAIN → UQBHO letter by letter (using each letter's "
        "position in the alphabet, A=1): T(+1)→U, R(-1)→Q, A(+1)→B, "
        "I(-1)→H, N(+1)→O. So the cipher shifts each letter by an "
        "alternating +1, -1, +1, -1, +1 pattern by position. Apply the "
        "same alternating shift to CHAIR: C(+1)→D, H(-1)→G, A(+1)→B, "
        "I(-1)→H, R(+1)→S, giving **DGBHS** — option (a)."
    ),
}

DIRECTION_SENSE_PROBLEM = {
    "_id": "lr-direction-sense-1",
    "question_type": "mcq",
    "path": "Logical Reasoning",
    "title": "Direction Sense: Final Bearing",
    "difficulty": "Medium",
    "tags": ["logical-reasoning", "direction-sense"],
    "step": "Verbal Reasoning",
    "order": 4,
    "companies": [],
    "description": (
        "A man walks 5 km to the East, then turns left and walks 3 km, then "
        "turns left again and walks 5 km. How far is he from his starting "
        "point, and in which direction?"
    ),
    "options": [
        {"id": "a", "text": "3 km, North of the starting point"},
        {"id": "b", "text": "3 km, South of the starting point"},
        {"id": "c", "text": "8 km, East of the starting point"},
        {"id": "d", "text": "13 km, North-East of the starting point"},
    ],
    "correct_option_id": "a",
    "solution_writeup": (
        "Start facing East, at the origin. Walk 5 km East: (5, 0). Turn "
        "left (from facing East, a left turn means now facing North), "
        "walk 3 km North: (5, 3). Turn left again (from facing North, now "
        "facing West), walk 5 km West: (0, 3). The East leg and West leg "
        "are equal and opposite (both 5 km), so they cancel exactly — only "
        "the 3 km North leg survives. He ends up at (0, 3): **3 km due "
        "North of the starting point** — option (a)."
    ),
}

NUMBER_SERIES_PROBLEM = {
    "_id": "lr-number-series-1",
    "question_type": "mcq",
    "path": "Logical Reasoning",
    "title": "Number Series: Find the Next Term",
    "difficulty": "Easy",
    "tags": ["logical-reasoning", "number-series"],
    "step": "Analytical Reasoning",
    "order": 1,
    "companies": [],
    "description": "Find the next number in the series: 3, 7, 15, 31, 63, ?",
    "options": [
        {"id": "a", "text": "95"},
        {"id": "b", "text": "127"},
        {"id": "c", "text": "119"},
        {"id": "d", "text": "111"},
    ],
    "correct_option_id": "b",
    "solution_writeup": (
        "Each term is `previous * 2 + 1`: 3×2+1=7, 7×2+1=15, 15×2+1=31, "
        "31×2+1=63, so the next is 63×2+1 = **127**. (Equivalently, each "
        "term is `2^(n+1) - 1`: 3=2²-1, 7=2³-1, 15=2⁴-1, 31=2⁵-1, 63=2⁶-1, "
        "next = 2⁷-1 = 127.)"
    ),
}

SEATING_ARRANGEMENT_PROBLEM = {
    "_id": "lr-seating-arrangement-1",
    "question_type": "mcq",
    "path": "Logical Reasoning",
    "title": "Seating Arrangement: Who Sits Where",
    "difficulty": "Medium",
    "tags": ["logical-reasoning", "seating-arrangement"],
    "step": "Analytical Reasoning",
    "order": 2,
    "companies": [],
    "description": (
        "Five friends — P, Q, R, S, T — sit in a row facing the same "
        "direction. Q sits immediately to the right of P. R sits at one of "
        "the ends. S sits exactly in the middle. T sits immediately to the "
        "left of S.\n\n"
        "Which of the following MUST be true?"
    ),
    "options": [
        {"id": "a", "text": "P sits at an end"},
        {"id": "b", "text": "Q sits in the middle"},
        {"id": "c", "text": "R sits immediately next to T"},
        {"id": "d", "text": "T sits at an end"},
    ],
    "correct_option_id": "c",
    "solution_writeup": (
        "5 seats, positions 1-5 left to right. S is in the middle: "
        "position 3. T is immediately left of S: position 2. That leaves "
        "positions 1, 4, 5 for P, Q, R, with Q immediately right of P "
        "(`Q = P + 1`) and R at an end (position 1 or 5). Testing the "
        "remaining positions {1, 4, 5} for a consecutive P/Q pair: only "
        "4 and 5 are consecutive, so P=4, Q=5 — which leaves position 1 "
        "for R, and 1 IS an end, so this is consistent. (P=1, Q=2 is "
        "impossible since position 2 is already T's.)\n\n"
        "Final arrangement: R=1, T=2, S=3, P=4, Q=5. Checking each option "
        "against it: P (4) is not at an end, ruling out (a); Q (5) is not "
        "in the middle, ruling out (b); T (2) is not at an end, ruling out "
        "(d); R (1) and T (2) ARE adjacent — **option (c) is the one that "
        "must be true**."
    ),
}

LOGICAL_REASONING_PROBLEMS = [
    BLOOD_RELATION_PROBLEM,
    SYLLOGISM_PROBLEM,
    CODING_DECODING_PROBLEM,
    DIRECTION_SENSE_PROBLEM,
    NUMBER_SERIES_PROBLEM,
    SEATING_ARRANGEMENT_PROBLEM,
]


# ---------------------------------------------------------------------------
# Computer Networks path — also `question_type: "mcq"` (same grading
# mechanism as Logical Reasoning, different topic/tagging — see the task
# design note on reusing MCQ for both paths).
# ---------------------------------------------------------------------------
OSI_LAYER_PROBLEM = {
    "_id": "cn-osi-layer-1",
    "question_type": "mcq",
    "path": "Computer Networks",
    "title": "OSI Model: Where Does Routing Happen?",
    "difficulty": "Easy",
    "tags": ["networks", "osi-model"],
    "step": "OSI & TCP/IP Fundamentals",
    "order": 1,
    "companies": [],
    "description": "In the OSI reference model, at which layer does routing (choosing a path across multiple networks) primarily happen?",
    "options": [
        {"id": "a", "text": "Data Link Layer (Layer 2)"},
        {"id": "b", "text": "Network Layer (Layer 3)"},
        {"id": "c", "text": "Transport Layer (Layer 4)"},
        {"id": "d", "text": "Session Layer (Layer 5)"},
    ],
    "correct_option_id": "b",
    "solution_writeup": (
        "The **Network Layer (Layer 3)** is responsible for logical "
        "addressing (IP addresses) and routing packets across "
        "interconnected networks — this is where routers make forwarding "
        "decisions. The Data Link Layer (2) handles addressing/framing "
        "within a single local network segment (MAC addresses, switches); "
        "the Transport Layer (4) handles end-to-end delivery and "
        "reliability (TCP/UDP), not path selection."
    ),
}

TCP_VS_UDP_PROBLEM = {
    "_id": "cn-tcp-vs-udp-1",
    "question_type": "mcq",
    "path": "Computer Networks",
    "title": "TCP vs UDP: Reliable Delivery",
    "difficulty": "Easy",
    "tags": ["networks", "tcp", "udp"],
    "step": "OSI & TCP/IP Fundamentals",
    "order": 2,
    "companies": [],
    "description": "Which transport-layer protocol guarantees reliable, ordered, and error-checked delivery of a stream of bytes between two hosts?",
    "options": [
        {"id": "a", "text": "UDP"},
        {"id": "b", "text": "IP"},
        {"id": "c", "text": "TCP"},
        {"id": "d", "text": "ICMP"},
    ],
    "correct_option_id": "c",
    "solution_writeup": (
        "**TCP** (Transmission Control Protocol) is connection-oriented and "
        "guarantees reliable, in-order, error-checked delivery via "
        "acknowledgments, retransmission, and sequence numbers. **UDP** is "
        "the opposite — connectionless, best-effort, no delivery guarantee "
        "— traded for lower latency and overhead (used for DNS, video "
        "streaming, gaming). IP handles addressing/routing, not "
        "reliability; ICMP is used for diagnostics/error reporting (e.g. ping)."
    ),
}

HTTPS_PORT_PROBLEM = {
    "_id": "cn-https-port-1",
    "question_type": "mcq",
    "path": "Computer Networks",
    "title": "Well-Known Ports: HTTPS",
    "difficulty": "Easy",
    "tags": ["networks", "ports", "http"],
    "step": "Application Layer Protocols",
    "order": 1,
    "companies": [],
    "description": "What is the default, well-known TCP port number for HTTPS (HTTP over TLS/SSL)?",
    "options": [
        {"id": "a", "text": "80"},
        {"id": "b", "text": "8080"},
        {"id": "c", "text": "21"},
        {"id": "d", "text": "443"},
    ],
    "correct_option_id": "d",
    "solution_writeup": (
        "**443** is the IANA-assigned well-known port for HTTPS. Port 80 "
        "is plain (unencrypted) HTTP; 8080 is a common alternate HTTP port "
        "used by dev servers/proxies, not a default; 21 is FTP's control port."
    ),
}

SUBNET_HOSTS_PROBLEM = {
    "_id": "cn-subnet-hosts-1",
    "question_type": "mcq",
    "path": "Computer Networks",
    "title": "Subnetting: Usable Host Count",
    "difficulty": "Medium",
    "tags": ["networks", "subnetting", "ipv4"],
    "step": "Addressing & Routing",
    "order": 1,
    "companies": [],
    "description": (
        "A subnet uses a /26 mask (255.255.255.192). How many **usable** "
        "host addresses does this subnet provide?"
    ),
    "options": [
        {"id": "a", "text": "64"},
        {"id": "b", "text": "62"},
        {"id": "c", "text": "30"},
        {"id": "d", "text": "126"},
    ],
    "correct_option_id": "b",
    "solution_writeup": (
        "/26 leaves `32 - 26 = 6` host bits, giving `2^6 = 64` total "
        "addresses in the block. Two of those are reserved — the lowest "
        "(network address) and the highest (broadcast address) — leaving "
        "`64 - 2 = **62**` usable host addresses."
    ),
}

ARP_PROBLEM = {
    "_id": "cn-arp-1",
    "question_type": "mcq",
    "path": "Computer Networks",
    "title": "Address Resolution: IP to MAC",
    "difficulty": "Easy",
    "tags": ["networks", "arp"],
    "step": "Addressing & Routing",
    "order": 2,
    "companies": [],
    "description": "Which protocol is used to resolve a known IPv4 address to its corresponding MAC (hardware) address on a local network?",
    "options": [
        {"id": "a", "text": "DNS"},
        {"id": "b", "text": "ARP"},
        {"id": "c", "text": "DHCP"},
        {"id": "d", "text": "RARP"},
    ],
    "correct_option_id": "b",
    "solution_writeup": (
        "**ARP** (Address Resolution Protocol) broadcasts \"who has this "
        "IP?\" on the local segment and the owning host replies with its "
        "MAC address. DNS resolves domain NAMES to IP addresses (a "
        "completely different layer of the problem); DHCP assigns IP "
        "addresses to hosts; RARP (largely obsolete) does the reverse of "
        "ARP — MAC to IP."
    ),
}

DNS_RECORD_PROBLEM = {
    "_id": "cn-dns-record-1",
    "question_type": "mcq",
    "path": "Computer Networks",
    "title": "DNS Record Types",
    "difficulty": "Easy",
    "tags": ["networks", "dns"],
    "step": "Application Layer Protocols",
    "order": 2,
    "companies": [],
    "description": "Which DNS record type maps a domain name directly to an IPv4 address?",
    "options": [
        {"id": "a", "text": "A"},
        {"id": "b", "text": "CNAME"},
        {"id": "c", "text": "MX"},
        {"id": "d", "text": "TXT"},
    ],
    "correct_option_id": "a",
    "solution_writeup": (
        "An **A record** maps a hostname to an IPv4 address (an AAAA record "
        "does the same for IPv6). A CNAME is an alias pointing to another "
        "hostname (resolved further from there), MX records specify mail "
        "servers for a domain, and TXT records hold arbitrary text "
        "(commonly used for domain verification/SPF)."
    ),
}

THREE_WAY_HANDSHAKE_PROBLEM = {
    "_id": "cn-three-way-handshake-1",
    "question_type": "mcq",
    "path": "Computer Networks",
    "title": "TCP Connection Setup",
    "difficulty": "Medium",
    "tags": ["networks", "tcp", "handshake"],
    "step": "OSI & TCP/IP Fundamentals",
    "order": 3,
    "companies": [],
    "description": "What is the correct sequence of segments exchanged in a standard TCP three-way handshake to establish a connection?",
    "options": [
        {"id": "a", "text": "SYN → ACK → FIN"},
        {"id": "b", "text": "SYN → SYN-ACK → ACK"},
        {"id": "c", "text": "ACK → SYN → SYN-ACK"},
        {"id": "d", "text": "SYN → FIN → ACK"},
    ],
    "correct_option_id": "b",
    "solution_writeup": (
        "The client sends **SYN** (requesting a connection with an initial "
        "sequence number), the server replies **SYN-ACK** (acknowledging "
        "the client's SYN and sending its own), and the client finishes "
        "with **ACK** (acknowledging the server's SYN) — after which the "
        "connection is established. FIN is used later, to gracefully "
        "*close* a connection, not open one."
    ),
}

COMPUTER_NETWORKS_PROBLEMS = [
    OSI_LAYER_PROBLEM,
    TCP_VS_UDP_PROBLEM,
    HTTPS_PORT_PROBLEM,
    SUBNET_HOSTS_PROBLEM,
    ARP_PROBLEM,
    DNS_RECORD_PROBLEM,
    THREE_WAY_HANDSHAKE_PROBLEM,
]


# ---------------------------------------------------------------------------
# System Design path (HLD + LLD) — `question_type: "design"`. A large
# free-text written answer, graded by an LLM against an explicit per-problem
# `rubric` (see `practice_ai_service.grade_design_submission`). There is no
# single correct answer to hide, so — same as every other problem type here —
# `solution_writeup` is a hand-written editorial covering the KEY points a
# strong answer would hit, visible up front (consistent with how the
# existing code problems already show their full solution unconditionally).
# ---------------------------------------------------------------------------
URL_SHORTENER_PROBLEM = {
    "_id": "sd-url-shortener",
    "question_type": "design",
    "path": "System Design",
    "title": "Design a URL Shortener (e.g. bit.ly)",
    "difficulty": "Medium",
    "tags": ["system-design", "hld"],
    "step": "High-Level Design (HLD)",
    "order": 1,
    "companies": ["Amazon", "Google", "Adobe"],
    "supports_diagram": True,
    "supports_calculation": True,
    "description": (
        "Design a URL-shortening service like bit.ly or TinyURL.\n\n"
        "Requirements to address in your answer:\n"
        "- Given a long URL, the service returns a short URL; visiting the "
        "short URL redirects to the original long URL.\n"
        "- Expected scale: ~100M new URLs/day, ~10:1 read:write ratio.\n"
        "- Short codes should be hard to guess (not sequential) but as "
        "short as practical.\n"
        "- Discuss: the short-code generation strategy, the data model and "
        "what store you'd use and why, how reads/redirects are kept fast at "
        "scale, and what happens if a custom alias collides with an existing one.\n\n"
        "**Draw your architecture** using the diagram canvas below — boxes "
        "for each component (client, load balancer, app servers, cache, "
        "datastore, etc.) and arrows for how a request flows through them. "
        "**Estimate the scale** in the calculations scratchpad: work out "
        "write QPS, read QPS, and storage growth per year from the ~100M/day "
        "figure above, stating whatever assumptions you make (e.g. average "
        "row size)."
    ),
    "examples": [],
    "constraints": [],
    "hints": [
        "A hash of the long URL isn't sufficient by itself — collisions need an explicit resolution strategy.",
        "Base62-encoding an auto-incrementing (or otherwise unique) counter is a common way to get short, non-sequential-looking codes without a collision-detection loop.",
        "Redirects are overwhelmingly reads — where would you put a cache, and what does that do to your write path?",
    ],
    "solution_writeup": (
        "## Key points a strong answer should hit\n\n"
        "**Core algorithm:** base62-encode a unique integer (an "
        "auto-incrementing counter, or a range of IDs pre-allocated per "
        "app-server to avoid a single point of contention) into a 6-8 "
        "character code — this avoids the collision-retry loop a pure hash "
        "approach needs, while still producing short, effectively "
        "non-sequential-looking codes if the counter itself is lightly "
        "obfuscated/shuffled.\n\n"
        "**Data model:** a simple key-value mapping `short_code -> "
        "long_url` (+ metadata: created_at, expires_at, click_count) is "
        "sufficient — a wide-column or KV store (DynamoDB, Cassandra) "
        "suits the access pattern (point lookups by short_code) far better "
        "than a relational join-heavy schema, since there ARE no joins here.\n\n"
        "**Read scaling:** redirects are the overwhelming majority of "
        "traffic (10:1 read:write) and are simple point-lookups — a cache "
        "(Redis/Memcached) in front of the KV store absorbs the vast "
        "majority of reads; a cache miss falls through to the store and "
        "populates the cache.\n\n"
        "**Custom alias collisions:** unlike auto-generated codes (which "
        "are unique by construction), a user-requested custom alias needs "
        "an explicit uniqueness check against the store before insert, "
        "with a clear conflict response (409-style) rather than silently "
        "overwriting.\n\n"
        "**Other considerations worth mentioning:** expiration/TTL policy, "
        "analytics (click counts) written asynchronously so they don't sit "
        "on the redirect's critical path, and rate-limiting URL creation "
        "to prevent abuse."
    ),
    "rubric": [
        {"criterion": "Scalability", "max_score": 10, "description": "Addresses the stated read-heavy scale (caching, read/write split, horizontal scaling) rather than a design that only works for one server."},
        {"criterion": "Data model correctness", "max_score": 10, "description": "Proposes a sensible schema/store for the short_code -> long_url mapping and justifies the store choice against the access pattern."},
        {"criterion": "Core algorithm (short-code generation)", "max_score": 10, "description": "Explains HOW short codes are generated and how collisions (especially for custom aliases) are avoided or detected."},
        {"criterion": "Edge cases", "max_score": 10, "description": "Considers at least one of: alias collisions, expiration, abuse/rate-limiting, or malformed input URLs."},
        {"criterion": "Clarity of API surface", "max_score": 10, "description": "Describes the shape of the create/redirect endpoints clearly enough that another engineer could implement against the description."},
        {"criterion": "Diagram shows load-balancing / horizontal scaling", "max_score": 10, "applies_to": "diagram", "description": "The diagram includes a load balancer (or otherwise shows multiple app-server instances) rather than a single server handling all traffic."},
        {"criterion": "Diagram shows a caching layer", "max_score": 10, "applies_to": "diagram", "description": "The diagram places a cache between the app servers and the datastore on the read path, consistent with the stated read-heavy traffic."},
        {"criterion": "Realistic scale estimate", "max_score": 10, "applies_to": "calculation", "description": "The calculations include a concrete write/read QPS and storage estimate derived from the ~100M URLs/day figure, with assumptions stated (not just a bare number with no derivation)."},
    ],
}

RATE_LIMITER_PROBLEM = {
    "_id": "sd-rate-limiter",
    "question_type": "design",
    "path": "System Design",
    "title": "Design a Distributed Rate Limiter",
    "difficulty": "Hard",
    "tags": ["system-design", "hld"],
    "step": "High-Level Design (HLD)",
    "order": 2,
    "companies": ["Amazon", "Microsoft", "Google"],
    "supports_diagram": True,
    "supports_calculation": True,
    "description": (
        "Design a rate limiter that enforces a per-user limit (e.g. 100 "
        "requests/minute) across a fleet of many API server instances "
        "behind a load balancer.\n\n"
        "Address: which rate-limiting algorithm you'd use and why (fixed "
        "window / sliding window / token bucket / leaky bucket), where the "
        "limiter's state lives so it's consistent across instances, how "
        "the limiter behaves if that shared state store becomes "
        "unavailable, and what the client sees when they're rate-limited.\n\n"
        "**Draw your architecture** using the diagram canvas below — show "
        "the load balancer, the fleet of API servers, and the shared state "
        "store the limiter reads/writes, with arrows showing how a request "
        "is checked against the limit. **Estimate the scale** in the "
        "calculations scratchpad: for a fleet handling a stated request "
        "volume (pick a realistic number and say so), estimate the "
        "increment/check throughput the shared store must sustain."
    ),
    "examples": [],
    "constraints": [],
    "hints": [
        "If each server instance tracks its own counters in local memory, a user could get N× the intended limit just by hitting N different instances.",
        "Fixed windows have a boundary problem (a burst right at the window edge can double-count) — what does a sliding window buy you over that?",
        "What SHOULD happen to normal traffic if the shared counter store goes down — should the limiter fail open or fail closed?",
    ],
    "solution_writeup": (
        "## Key points a strong answer should hit\n\n"
        "**Why local, per-instance counters fail:** with N server "
        "instances each tracking counts independently, a user can receive "
        "up to N times the intended limit by having requests routed across "
        "instances — the limiter's state MUST be shared/centralized.\n\n"
        "**Shared state store:** Redis is the standard choice — in-memory, "
        "fast, and its `INCR` + `EXPIRE` (or a Lua script combining both "
        "atomically) gives an atomic increment-and-check with no race "
        "condition between servers.\n\n"
        "**Algorithm trade-offs:** fixed window is simplest but allows a "
        "burst of 2x the limit right at a window boundary (e.g. 100 "
        "requests in the last second of one window + 100 in the first "
        "second of the next). A sliding window (log or counter-based) or a "
        "token bucket smooths this out — token bucket additionally allows "
        "controlled bursting up to the bucket size, which fixed/sliding "
        "windows don't naturally express.\n\n"
        "**Failure mode:** whether the limiter fails OPEN (allow all "
        "traffic through if Redis is unreachable — availability over "
        "strict enforcement) or CLOSED (reject everything — protection "
        "over availability) is a real design decision with no universally "
        "'correct' answer, but a strong answer states its choice explicitly "
        "and justifies it against the system's actual risk profile.\n\n"
        "**Client experience:** a `429 Too Many Requests` response with a "
        "`Retry-After` header (or `X-RateLimit-Remaining`/`X-RateLimit-Reset`) "
        "lets well-behaved clients back off correctly instead of "
        "hammering the API immediately again."
    ),
    "rubric": [
        {"criterion": "Correct identification of the distributed-state problem", "max_score": 10, "description": "Explicitly identifies why per-instance local counters are insufficient across a fleet."},
        {"criterion": "Algorithm choice & trade-offs", "max_score": 10, "description": "Names a specific algorithm (token bucket / sliding window / etc.) and discusses its trade-off against at least one alternative."},
        {"criterion": "Shared store & concurrency correctness", "max_score": 10, "description": "Proposes a specific shared store and addresses the race condition between concurrent increments from different servers."},
        {"criterion": "Failure-mode handling", "max_score": 10, "description": "Explicitly discusses what happens to traffic if the shared store is unavailable (fail open vs. fail closed)."},
        {"criterion": "Client-facing behavior", "max_score": 10, "description": "Describes what a rate-limited client actually receives (status code / headers)."},
        {"criterion": "Diagram shows horizontal scaling behind a load balancer", "max_score": 10, "applies_to": "diagram", "description": "The diagram shows a load balancer fanning out to multiple API server instances, not a single server — the whole point being a fleet, not one box."},
        {"criterion": "Diagram shows the shared state store", "max_score": 10, "applies_to": "diagram", "description": "The diagram includes a distinct shared store (e.g. Redis) that every API server instance connects to, making the shared-state design visible rather than only described in prose."},
        {"criterion": "Realistic throughput estimate", "max_score": 10, "applies_to": "calculation", "description": "The calculations derive a concrete increment/check throughput (requests/sec the shared store must handle) from a stated request-volume assumption."},
    ],
}

NOTIFICATION_SYSTEM_PROBLEM = {
    "_id": "sd-notification-system",
    "question_type": "design",
    "path": "System Design",
    "title": "Design a Notification System",
    "difficulty": "Medium",
    "tags": ["system-design", "hld"],
    "step": "High-Level Design (HLD)",
    "order": 3,
    "companies": ["Meta", "Amazon"],
    "supports_diagram": True,
    "supports_calculation": True,
    "description": (
        "Design a notification system that can send notifications to users "
        "via multiple channels: push (mobile), email, and SMS. Other "
        "internal services (e.g. an order service, a chat service) should "
        "be able to trigger a notification without needing to know how "
        "each channel actually works.\n\n"
        "Address: how the system decouples 'something happened' from "
        "'actually deliver it', how a burst of notifications (e.g. a viral "
        "post) is handled without overwhelming third-party providers "
        "(APNs/FCM/an email provider/an SMS gateway), how failed "
        "deliveries are retried, and how you'd avoid spamming a user with "
        "duplicate notifications for the same event.\n\n"
        "**Draw your architecture** using the diagram canvas below — the "
        "triggering services, the queue, the worker/consumer layer, and the "
        "per-channel provider adapters, with arrows showing the flow from "
        "'event happened' to 'notification delivered'. **Estimate the "
        "scale** in the calculations scratchpad: for a stated "
        "notifications-per-day figure (pick one and say so), estimate the "
        "peak send rate a viral burst could produce and the queue "
        "throughput needed to absorb it."
    ),
    "examples": [],
    "constraints": [],
    "hints": [
        "Should the order service that triggers a notification call the push/email/SMS providers directly, or through something in between?",
        "A message queue between 'event happened' and 'notification sent' is what makes a traffic burst survivable instead of an outage.",
        "What key would you use to detect and drop a duplicate send for the same logical event?",
    ],
    "solution_writeup": (
        "## Key points a strong answer should hit\n\n"
        "**Decoupling via a queue:** internal services publish a "
        "notification EVENT (user id, template, channel preference, "
        "payload) onto a message queue (Kafka/SQS/RabbitMQ) rather than "
        "calling providers directly — this decouples the triggering "
        "service's request path from actual delivery, and lets a burst of "
        "events queue up and drain at a sustainable rate instead of "
        "immediately overwhelming APNs/FCM/an email or SMS provider.\n\n"
        "**Worker/consumer layer:** a pool of notification workers consumes "
        "the queue, resolves the user's channel preferences and contact "
        "info, and calls the appropriate provider adapter (push/email/SMS) "
        "— each channel behind its own adapter/interface so adding a new "
        "channel doesn't touch the triggering services at all.\n\n"
        "**Retries & backoff:** a failed provider call goes back onto a "
        "retry queue with exponential backoff, with a dead-letter queue "
        "after N attempts so a permanently-failing send doesn't loop forever.\n\n"
        "**De-duplication:** an idempotency key (e.g. hash of "
        "event_id + user_id + channel) checked against a short-lived cache "
        "before sending prevents the same logical event from notifying a "
        "user twice, e.g. if the triggering service retries its own publish.\n\n"
        "**User preferences:** a per-user preference store (opted-in "
        "channels, quiet hours, unsubscribes) is checked before dispatch, "
        "not baked into the triggering service."
    ),
    "rubric": [
        {"criterion": "Decoupling / asynchrony", "max_score": 10, "description": "Explicitly uses a queue or equivalent async mechanism between 'event triggered' and 'notification delivered'."},
        {"criterion": "Burst / scalability handling", "max_score": 10, "description": "Addresses what happens under a large burst of notifications without overwhelming downstream providers."},
        {"criterion": "Multi-channel abstraction", "max_score": 10, "description": "Describes an abstraction (adapter/interface) that lets push/email/SMS be added without changing triggering services."},
        {"criterion": "Failure handling & retries", "max_score": 10, "description": "Addresses retry/backoff behavior for a failed delivery."},
        {"criterion": "Deduplication", "max_score": 10, "description": "Addresses how a duplicate notification for the same event is avoided."},
        {"criterion": "Diagram shows the queue decoupling triggers from delivery", "max_score": 10, "applies_to": "diagram", "description": "The diagram shows triggering services publishing to a queue, and a separate worker/consumer layer reading from it — not triggering services calling providers directly."},
        {"criterion": "Diagram shows per-channel provider adapters", "max_score": 10, "applies_to": "diagram", "description": "The diagram shows the worker layer fanning out to distinct push/email/SMS provider nodes, making the multi-channel abstraction visible, not just described in prose."},
        {"criterion": "Realistic burst-throughput estimate", "max_score": 10, "applies_to": "calculation", "description": "The calculations derive a concrete peak notifications/sec figure for a burst scenario from a stated daily-volume assumption."},
    ],
}

PARKING_LOT_PROBLEM = {
    "_id": "sd-parking-lot",
    "question_type": "design",
    "path": "System Design",
    "title": "Design a Parking Lot System (LLD)",
    "difficulty": "Medium",
    "tags": ["system-design", "lld", "oop"],
    "step": "Low-Level Design (LLD)",
    "order": 1,
    "companies": ["Amazon", "Google", "Microsoft"],
    "description": (
        "Design the CLASSES (not a distributed architecture — this is a "
        "single-process, object-oriented design) for a multi-level parking "
        "lot system.\n\n"
        "Requirements:\n"
        "- Multiple levels, each with parking spots of different sizes "
        "(motorcycle, compact, large).\n"
        "- A vehicle can only park in a spot its size fits.\n"
        "- The system tracks which spots are free/occupied and can find an "
        "available spot for an incoming vehicle.\n"
        "- Support issuing a ticket on entry and computing a fee on exit "
        "based on duration.\n\n"
        "Describe your key classes/interfaces, their responsibilities and "
        "relationships (composition/inheritance), and how the 'find a spot "
        "for this vehicle' operation would be implemented."
    ),
    "examples": [],
    "constraints": [],
    "hints": [
        "Vehicle and Spot both come in different 'sizes' — is that better modeled as an inheritance hierarchy, an enum, or both?",
        "Who owns the responsibility of finding a free spot: the ParkingLot, the Level, or the Spot itself?",
        "A Ticket needs to capture enough state at entry time to compute a correct fee at exit time, independent of any other ticket.",
    ],
    "solution_writeup": (
        "## Key points a strong answer should hit\n\n"
        "**Core classes:** `ParkingLot` (owns a list of `Level`s, "
        "top-level entry point for `parkVehicle`/`unparkVehicle`), `Level` "
        "(owns a list of `ParkingSpot`s, knows how to find its own next "
        "free spot for a given size), `ParkingSpot` (has a `size` enum "
        "and an occupied/free state, references the parked `Vehicle` if "
        "any), `Vehicle` (base class with a `size` enum "
        "Motorcycle/Compact/Large — either as a plain `size` field or, if "
        "vehicle-specific behavior is needed, an inheritance hierarchy "
        "`Motorcycle`/`Car`/`Bus` extending `Vehicle`), and `Ticket` "
        "(vehicle reference, spot reference, entry timestamp, and later, "
        "exit timestamp + computed fee).\n\n"
        "**Spot-finding:** a reasonable design has `ParkingLot.parkVehicle` "
        "delegate to each `Level` in turn (e.g. lowest level first) asking "
        "'do you have a free spot that fits this vehicle's size'; `Level` "
        "iterates (or, better, keeps a free-spot index/map keyed by size) "
        "to answer in better than a linear scan of every spot on every "
        "call as the lot fills. A key design point: a Motorcycle CAN use a "
        "Compact or Large spot if none of its own size are free (spot-size "
        "compatibility isn't strict equality, it's 'is this spot big "
        "enough'), which a strong answer states explicitly.\n\n"
        "**Ticketing/fee:** `Ticket` is created on entry with a start "
        "timestamp; on exit, `(exit_time - entry_time)` combined with a "
        "rate table (possibly varying by vehicle size) computes the fee — "
        "keeping this logic in a separate `FeeCalculator`/`FeeStrategy` "
        "class (rather than hardcoded inside `Ticket`) keeps pricing "
        "changes from requiring a change to the ticket's own class.\n\n"
        "**Extensibility:** using a strategy pattern for fee calculation "
        "and a size ENUM (or small size hierarchy) for spot/vehicle "
        "compatibility makes adding a new vehicle size or a new pricing "
        "scheme a localized change, not a rewrite."
    ),
    "rubric": [
        {"criterion": "Class design & OOP principles", "max_score": 10, "description": "Identifies sensible core classes (ParkingLot, Level, Spot, Vehicle, Ticket or equivalent) with clear single responsibilities."},
        {"criterion": "Handling different vehicle/spot sizes", "max_score": 10, "description": "Explicitly addresses size compatibility (a smaller vehicle fitting a larger spot) rather than assuming exact-size matching only."},
        {"criterion": "Spot allocation algorithm", "max_score": 10, "description": "Describes how an available spot is actually found/assigned to an incoming vehicle."},
        {"criterion": "Ticketing & fee calculation", "max_score": 10, "description": "Describes how entry/exit are tracked and how a fee is computed from duration."},
        {"criterion": "Extensibility", "max_score": 10, "description": "Discusses how the design accommodates a new vehicle type, spot type, or pricing rule without a large rewrite."},
    ],
}

ELEVATOR_SYSTEM_PROBLEM = {
    "_id": "sd-elevator-system",
    "question_type": "design",
    "path": "System Design",
    "title": "Design an Elevator System (LLD)",
    "difficulty": "Hard",
    "tags": ["system-design", "lld", "oop"],
    "step": "Low-Level Design (LLD)",
    "order": 2,
    "companies": ["Amazon", "Microsoft"],
    "description": (
        "Design the CLASSES for a control system managing multiple "
        "elevators in a building.\n\n"
        "Requirements:\n"
        "- Multiple elevator cars, each serving all floors of the building.\n"
        "- A user on any floor can press an up/down call button; a user "
        "inside a car can select a destination floor.\n"
        "- The system must decide WHICH car responds to a given call.\n"
        "- Each car processes its pending requests in a sensible order "
        "(not necessarily FIFO — think about how a real elevator behaves).\n\n"
        "Describe your key classes, how a call gets assigned to a specific "
        "car, and how a single car decides its next stop among several "
        "pending requests."
    ),
    "examples": [],
    "constraints": [],
    "hints": [
        "An elevator mid-journey shouldn't reverse direction just because a closer request appears — how does a real elevator avoid that?",
        "Assigning EVERY call to the nearest idle car is simple but not always optimal — what else might you weigh (car already moving toward that floor, current load)?",
        "Model the set of pending stops for one car as something ordered by proximity IN THE CURRENT DIRECTION OF TRAVEL, not by arrival time.",
    ],
    "solution_writeup": (
        "## Key points a strong answer should hit\n\n"
        "**Core classes:** `ElevatorController` (or `Dispatcher` — the "
        "top-level entry point that receives external hall calls and "
        "assigns them to a car), `ElevatorCar` (current floor, direction, "
        "state — idle/moving-up/moving-down, and its own set of pending "
        "stops), `Request`/`Call` (floor + desired direction for a hall "
        "call, or just a destination floor for an in-car request).\n\n"
        "**Dispatch/assignment strategy:** a real design should go beyond "
        "'nearest idle car' — a strong answer considers a car that's "
        "ALREADY moving toward the requested floor in the matching "
        "direction as a candidate too (it can pick up the request en route "
        "with no detour), scoring candidate cars by something like "
        "distance-adjusted-for-direction-and-current-load, not just raw "
        "distance.\n\n"
        "**Per-car request ordering (the classic SCAN/elevator algorithm):** "
        "a single car should NOT serve requests in the order they arrived "
        "— it should continue in its current direction, servicing every "
        "pending stop along the way in that direction (like a disk-scheduling "
        "SCAN algorithm), before reversing direction once it has no more "
        "stops ahead of it. This avoids the car bouncing back and forth "
        "between floors as new requests arrive during a run.\n\n"
        "**Data structure for pending stops:** commonly two ordered "
        "sets/sorted structures per car — 'stops above current floor, "
        "ascending' and 'stops below current floor, descending' — so the "
        "next stop is always whichever is closest in the current direction, "
        "with O(log n) insertion for a new request.\n\n"
        "**Extensibility:** keeping the assignment strategy as a "
        "swappable component (interface) lets the building operator later "
        "tune it (e.g. reserve a car for a VIP floor) without touching the "
        "core car/request model."
    ),
    "rubric": [
        {"criterion": "Class design & OOP principles", "max_score": 10, "description": "Identifies sensible core classes (Controller/Dispatcher, Car, Request) with clear responsibilities."},
        {"criterion": "Call-to-car assignment strategy", "max_score": 10, "description": "Describes a specific strategy for choosing which car answers a hall call, beyond a naive 'always nearest idle car'."},
        {"criterion": "Per-car request scheduling (SCAN-like behavior)", "max_score": 10, "description": "Addresses how a single car orders its own pending stops to avoid unnecessary direction reversals."},
        {"criterion": "State modeling", "max_score": 10, "description": "Models a car's current floor/direction/state and pending requests clearly enough to reason about correctness."},
        {"criterion": "Extensibility", "max_score": 10, "description": "Discusses how the design could accommodate a new requirement (e.g. a reserved car, capacity limits) without a large rewrite."},
    ],
}

LIBRARY_MANAGEMENT_PROBLEM = {
    "_id": "sd-library-management",
    "question_type": "design",
    "path": "System Design",
    "title": "Design a Library Management System (LLD)",
    "difficulty": "Medium",
    "tags": ["system-design", "lld", "oop"],
    "step": "Low-Level Design (LLD)",
    "order": 3,
    "companies": ["Adobe", "Microsoft"],
    "description": (
        "Design the CLASSES for a library management system.\n\n"
        "Requirements:\n"
        "- The library holds multiple copies of the same book (a `Book` "
        "title vs. a physical `BookCopy` are different concepts).\n"
        "- A member can check out an available copy and must return it by "
        "a due date; a late return incurs a fine.\n"
        "- A member can place a hold on a book that's fully checked out, "
        "and gets notified when a copy becomes available.\n"
        "- A librarian can add new titles/copies and remove damaged copies.\n\n"
        "Describe your key classes and their relationships, and how "
        "check-out/return/hold would be implemented."
    ),
    "examples": [],
    "constraints": [],
    "hints": [
        "A 'Book' (the title, author, ISBN) and a physical copy on a shelf are two different things with two different lifecycles — model them separately.",
        "What state does a BookCopy need beyond 'checked out or not' to support holds correctly?",
        "When a checked-out copy is returned and there's a queue of holds on that title, who gets it next?",
    ],
    "solution_writeup": (
        "## Key points a strong answer should hit\n\n"
        "**Title vs. copy:** `Book` represents the title-level metadata "
        "(ISBN, title, author) — there's exactly one `Book` record per "
        "distinct title regardless of how many physical copies the library "
        "owns. `BookCopy` represents one physical, shelvable item "
        "(a copy id, condition, and a status: available / checked-out / "
        "on-hold / damaged), with a reference back to its `Book`. "
        "Conflating these two would make 'how many copies of this title "
        "are available' awkward to answer.\n\n"
        "**Checkout/return:** a `Loan` (or `Checkout`) record ties a "
        "specific `BookCopy` to a `Member` with a checkout date and a due "
        "date; `Member.checkoutBook(copy)` marks the copy unavailable and "
        "creates the Loan, `returnBook(copy)` closes the Loan, marks the "
        "copy available again, and computes a fine if `now > due_date`.\n\n"
        "**Holds:** a `Hold` is a request tied to a `Book` (the title, not "
        "a specific copy — a member holding a title doesn't care WHICH "
        "physical copy they get) and a `Member`, queued in "
        "request order. When a copy of that title is returned, the "
        "system checks for a pending hold queue on that `Book`; if one "
        "exists, the returned copy is assigned/reserved for the "
        "front-of-queue member (and they're notified) instead of "
        "going back to general availability.\n\n"
        "**Librarian operations:** adding a new title creates a `Book`; "
        "adding copies creates `BookCopy` instances linked to it; removing "
        "a damaged copy marks it permanently unavailable (or deletes it) "
        "without affecting the `Book` record or other copies.\n\n"
        "**Fine calculation:** kept as a separate concern (e.g. a "
        "`FineCalculator` given the loan's overdue duration) rather than "
        "hardcoded inline, similar to the fee-strategy point in the "
        "parking lot design — keeps a future policy change localized."
    ),
    "rubric": [
        {"criterion": "Class design & OOP principles", "max_score": 10, "description": "Separates title-level (Book) from copy-level (BookCopy) concepts and models Member/Loan sensibly."},
        {"criterion": "Checkout/return flow", "max_score": 10, "description": "Describes how a checkout and return actually update state and compute a fine when late."},
        {"criterion": "Hold/reservation handling", "max_score": 10, "description": "Describes how a hold is queued and how a returned copy is routed to a waiting member."},
        {"criterion": "Librarian operations", "max_score": 10, "description": "Addresses adding new titles/copies and removing damaged copies without breaking existing loans/holds."},
        {"criterion": "Clarity of relationships", "max_score": 10, "description": "The relationships between Book, BookCopy, Member, Loan, and Hold are clear and consistent."},
    ],
}

SYSTEM_DESIGN_PROBLEMS = [
    URL_SHORTENER_PROBLEM,
    RATE_LIMITER_PROBLEM,
    NOTIFICATION_SYSTEM_PROBLEM,
    PARKING_LOT_PROBLEM,
    ELEVATOR_SYSTEM_PROBLEM,
    LIBRARY_MANAGEMENT_PROBLEM,
]

ALL_PROBLEMS = [
    TWO_SUM_PROBLEM,
    CONTAINS_DUPLICATE_PROBLEM,
    VALID_ANAGRAM_PROBLEM,
    BEST_TIME_TO_BUY_SELL_STOCK_PROBLEM,
    PRODUCT_OF_ARRAY_EXCEPT_SELF_PROBLEM,
    VALID_PALINDROME_PROBLEM,
    TWO_SUM_II_PROBLEM,
    SORTED_SQUARES_PROBLEM,
    BINARY_SEARCH_PROBLEM,
    SEARCH_INSERT_POSITION_PROBLEM,
    SQRT_X_PROBLEM,
    *SQL_PROBLEMS,
    *LOGICAL_REASONING_PROBLEMS,
    *COMPUTER_NETWORKS_PROBLEMS,
    *SYSTEM_DESIGN_PROBLEMS,
]


async def seed_problems():
    """Idempotent PER-PROBLEM: inserts any problem in ALL_PROBLEMS whose
    `_id` isn't in the collection yet, but never touches one that's already
    there. This keeps the original guarantee (Two Sum, seeded before this
    file grew, is never clobbered or reset) while letting new problems added
    here over time get seeded in too, and letting an admin's edits to any
    already-seeded problem survive a restart."""
    existing_ids = {d["_id"] async for d in practice_problems_col.find({}, {"_id": 1})}
    for problem in ALL_PROBLEMS:
        if problem["_id"] not in existing_ids:
            doc = {**problem, "created_at": now_iso(), "updated_at": now_iso()}
            await practice_problems_col.insert_one(doc)
            logger.info(f"Seeded practice problem: {problem['_id']}")
            continue
        # One-time backfill: a problem seeded before this file grew a
        # roadmap (i.e. the original Two Sum) has no `step`/`order`/
        # `companies` fields yet — AND predates the generic harness's
        # `params`/`output_type` fields too (it was hardcoded to Two Sum's
        # exact nums/target shape before that existed as a concept). Missing
        # `params` makes the harness call the entry point with zero
        # arguments — a real, silent bug, not just a cosmetic gap. Only
        # touch these five, only when `step` is missing — never overwrite
        # title/description/starter_code/etc. (an admin may have edited
        # them), and never touch submissions.
        await practice_problems_col.update_one(
            {"_id": problem["_id"], "step": {"$exists": False}},
            {"$set": {
                "step": problem.get("step", "Uncategorized"),
                "order": problem.get("order", 0),
                "companies": problem.get("companies", []),
                "params": problem.get("params", []),
                "output_type": problem.get("output_type"),
                "updated_at": now_iso(),
            }},
        )
        # Second, independent one-time backfill: `path` (the top-level
        # roadmap grouping added above `step`, e.g. "DSA"/"SQL"/...) and
        # `question_type` ("code"/"sql"/"mcq"/"design"), added when the SQL /
        # Logical Reasoning / Computer Networks / System Design paths were
        # introduced. Gated on `path` missing specifically — NOT on `step`
        # missing (every existing problem already has `step` set, so the
        # backfill above would never fire for them) — same idempotent,
        # only-if-missing, never-clobber-an-admin-edit pattern as above.
        await practice_problems_col.update_one(
            {"_id": problem["_id"], "path": {"$exists": False}},
            {"$set": {
                "path": problem.get("path", "DSA"),
                "question_type": problem.get("question_type", "code"),
                "updated_at": now_iso(),
            }},
        )


async def enrich_video_links():
    """Fetch-and-cache YouTube video links per problem, once. YouTube's
    search.list costs 100 quota units per call against a 10,000/day free-tier
    cap — with ~11 problems that's ~1,100 units total, fine as a one-time
    pass, but would exhaust the daily quota in under two hours if called live
    per page view instead. Only touches problems missing `video_links`
    entirely, so a restart never re-spends quota on problems already done."""
    from services.youtube_service import find_solution_videos, YOUTUBE_API_KEY
    if not YOUTUBE_API_KEY:
        return  # startup already logs a reminder; nothing to do here yet
    async for doc in practice_problems_col.find({"video_links": {"$exists": False}}, {"_id": 1, "title": 1}):
        try:
            videos = await find_solution_videos(doc["title"])
        except Exception:
            logger.exception("Video lookup failed for %s", doc["_id"])
            continue
        await practice_problems_col.update_one(
            {"_id": doc["_id"]},
            {"$set": {"video_links": videos, "video_links_updated_at": now_iso()}},
        )
        logger.info("Cached %d video link(s) for %s", len(videos), doc["_id"])


async def ensure_indexes():
    await practice_submissions_col.create_index([("user_id", 1), ("created_at", -1)])
    await practice_submissions_col.create_index([("problem_id", 1), ("user_id", 1)])
    await practice_problems_col.create_index([("step", 1), ("order", 1)])


# ---------------------------------------------------------------------------
# Problem access
# ---------------------------------------------------------------------------
def _to_public_problem_summary(doc: dict) -> dict:
    return {
        "id": doc["_id"],
        "title": doc["title"],
        "difficulty": doc.get("difficulty", "Easy"),
        "tags": doc.get("tags", []),
        "path": doc.get("path", "DSA"),
        "question_type": doc.get("question_type", "code"),
    }


def _to_public_problem_detail(doc: dict) -> dict:
    question_type = doc.get("question_type", "code")
    base = {
        "id": doc["_id"],
        "title": doc["title"],
        "difficulty": doc.get("difficulty", "Easy"),
        "tags": doc.get("tags", []),
        "path": doc.get("path", "DSA"),
        "step": doc.get("step", "Uncategorized"),
        "question_type": question_type,
        "description": doc.get("description", ""),
        "hints": doc.get("hints", []),
        # Hand-written editorial, shown unconditionally regardless of question
        # type or whether the user has solved it yet — matches the existing
        # code-problem precedent (TWO_SUM_PROBLEM etc. never gated this).
        "solution_writeup": doc.get("solution_writeup", ""),
        "video_links": doc.get("video_links", []),
    }
    if question_type == "code":
        base.update({
            "examples": doc.get("examples", []),
            "constraints": doc.get("constraints", []),
            "starter_code": doc.get("starter_code", {}),
            "languages": list(doc.get("starter_code", {}).keys()),
            # Expose test-case INPUTS only (never `expected`) so the editor's sample
            # data is visible but a submission can't be reverse-engineered for free.
            "sample_inputs": [tc["input"] for tc in doc.get("test_cases", [])],
            "test_case_count": len(doc.get("test_cases", [])),
        })
    elif question_type == "sql":
        base.update({
            "examples": doc.get("examples", []),
            "constraints": doc.get("constraints", []),
            "starter_code": doc.get("starter_code", {"sql": "-- write your query\n"}),
            "languages": ["sql"],
            # Derived fresh from `schema_sql` (the single source of truth)
            # rather than hand-duplicated — see `get_sql_table_preview`.
            "tables": get_sql_table_preview(doc.get("schema_sql", "")),
            "order_sensitive": bool(doc.get("order_sensitive", False)),
        })
    elif question_type == "mcq":
        base.update({
            # Never include `correct_option_id` here — only after a submission.
            "options": [{"id": o["id"], "text": o["text"]} for o in doc.get("options", [])],
        })
    elif question_type == "design":
        base.update({
            "rubric": [
                {
                    "criterion": c["criterion"],
                    "description": c.get("description", ""),
                    "max_score": c.get("max_score", 10),
                    # Defaults to "answer" — absent on every rubric criterion
                    # authored before diagram/calculation support existed.
                    "applies_to": c.get("applies_to", "answer"),
                }
                for c in doc.get("rubric", [])
            ],
            # Both default False — absent on every design problem seeded
            # before this feature (and on any the concurrent bulk-generator
            # adds without them), so the frontend renders the plain
            # textarea-only layout unless a problem explicitly opts in.
            "supports_diagram": bool(doc.get("supports_diagram", False)),
            "supports_calculation": bool(doc.get("supports_calculation", False)),
        })
    return base


async def list_problems() -> List[dict]:
    items = []
    async for d in practice_problems_col.find({}).sort("title", 1):
        items.append(_to_public_problem_summary(d))
    return items


async def get_problem_public(problem_id: str) -> Optional[dict]:
    doc = await practice_problems_col.find_one({"_id": problem_id})
    if not doc:
        return None
    return _to_public_problem_detail(doc)


async def get_problem_raw(problem_id: str) -> Optional[dict]:
    """Full document (including test cases + expected outputs) — internal use
    only (grading). Never return this directly from an API response."""
    return await practice_problems_col.find_one({"_id": problem_id})


# ---------------------------------------------------------------------------
# Roadmap / progress / streak — lightweight aggregations, never "pull every
# submission down and compute client-side."
# ---------------------------------------------------------------------------
async def list_roadmap() -> List[dict]:
    """Every problem's roadmap-facing fields, grouped by `path` (the
    top-level DSA/SQL/Logical Reasoning/Computer Networks/System Design
    section) and then by `step` within it, ordered within each — solved
    status is NOT included here (that's per-user, merged in by the route
    handler from `get_solved_problem_ids`)."""
    items = []
    async for d in practice_problems_col.find(
        {}, {"title": 1, "difficulty": 1, "tags": 1, "companies": 1, "step": 1, "order": 1, "path": 1, "question_type": 1}
    ):
        items.append({
            "id": d["_id"],
            "title": d["title"],
            "difficulty": d.get("difficulty", "Easy"),
            "tags": d.get("tags", []),
            "companies": d.get("companies", []),
            "path": d.get("path", "DSA"),
            "step": d.get("step", "Uncategorized"),
            "order": d.get("order", 0),
            "question_type": d.get("question_type", "code"),
        })
    items.sort(key=lambda p: (
        PATH_ORDER.get(p["path"], 999),
        STEP_ORDER.get(p["path"], {}).get(p["step"], 999),
        p["order"],
    ))
    return items


async def get_solved_problem_ids(user_id: str) -> List[str]:
    """Distinct problem_ids the user has ever gotten `all_passed: True` on —
    a single Mongo aggregation, not "fetch every submission and filter"."""
    cursor = practice_submissions_col.aggregate([
        {"$match": {"user_id": user_id, "all_passed": True}},
        {"$group": {"_id": "$problem_id"}},
    ])
    return [doc["_id"] async for doc in cursor]


async def _compute_streak(user_id: str) -> int:
    """Consecutive calendar days (UTC) with >=1 submission, counting
    backward from today — or from yesterday, if there's no submission yet
    today, so the streak doesn't read as broken the instant the clock ticks
    past midnight before that day's practice session. `created_at` is an
    ISO-8601 UTC string (see `now_iso()`), so its first 10 characters are
    always that submission's UTC calendar date — grouping on that prefix in
    an aggregation pipeline gets the distinct set of practiced days without
    pulling a single submission document to the app layer.

    `$substr`, not `$substrCP` — plain `$substr` is deprecated in MongoDB in
    favor of the codepoint-aware `$substrCP`, but `created_at` is always
    pure ASCII (digits/dashes/colons/T/Z), so byte offsets and codepoint
    offsets are identical here, and mongomock (used by this test suite)
    implements `$substr` but not `$substrCP`."""
    cursor = practice_submissions_col.aggregate([
        {"$match": {"user_id": user_id}},
        {"$group": {"_id": {"$substr": ["$created_at", 0, 10]}}},
    ])
    days = {doc["_id"] async for doc in cursor}
    if not days:
        return 0

    cursor_day = now_utc().date()
    if cursor_day.isoformat() not in days:
        cursor_day = cursor_day - timedelta(days=1)
        if cursor_day.isoformat() not in days:
            return 0

    streak = 0
    while cursor_day.isoformat() in days:
        streak += 1
        cursor_day -= timedelta(days=1)
    return streak


async def get_progress(user_id: str) -> dict:
    """Dashboard numbers for the roadmap page: total solved/total problems,
    per-path (DSA/SQL/Logical Reasoning/Computer Networks/System Design)
    solved/total/pct with a per-step breakdown nested inside each path, and
    the current daily streak. Two aggregation-scale queries (problem counts
    by path+step, solved ids) plus the streak aggregation above — never a
    per-submission client-side computation."""
    total_by_path_step: Dict[Tuple[str, str], int] = {}
    total_by_path: Dict[str, int] = {}
    total_problems = 0
    async for d in practice_problems_col.find({}, {"path": 1, "step": 1}):
        path = d.get("path", "DSA")
        step = d.get("step", "Uncategorized")
        total_by_path_step[(path, step)] = total_by_path_step.get((path, step), 0) + 1
        total_by_path[path] = total_by_path.get(path, 0) + 1
        total_problems += 1

    solved_ids = set(await get_solved_problem_ids(user_id))
    solved_by_path_step: Dict[Tuple[str, str], int] = {}
    solved_by_path: Dict[str, int] = {}
    if solved_ids:
        async for d in practice_problems_col.find({"_id": {"$in": list(solved_ids)}}, {"path": 1, "step": 1}):
            path = d.get("path", "DSA")
            step = d.get("step", "Uncategorized")
            solved_by_path_step[(path, step)] = solved_by_path_step.get((path, step), 0) + 1
            solved_by_path[path] = solved_by_path.get(path, 0) + 1

    paths = []
    for path, total in total_by_path.items():
        solved = solved_by_path.get(path, 0)
        steps = []
        for (p, step), stotal in total_by_path_step.items():
            if p != path:
                continue
            ssolved = solved_by_path_step.get((p, step), 0)
            steps.append({
                "step": step,
                "solved": ssolved,
                "total": stotal,
                "pct": round(100 * ssolved / stotal) if stotal else 0,
            })
        steps.sort(key=lambda s: STEP_ORDER.get(path, {}).get(s["step"], 999))
        paths.append({
            "path": path,
            "solved": solved,
            "total": total,
            "pct": round(100 * solved / total) if total else 0,
            "steps": steps,
        })
    paths.sort(key=lambda p: PATH_ORDER.get(p["path"], 999))

    return {
        "total_solved": len(solved_ids),
        "total_problems": total_problems,
        "overall_pct": round(100 * len(solved_ids) / total_problems) if total_problems else 0,
        "paths": paths,
        "current_streak_days": await _compute_streak(user_id),
    }


# ---------------------------------------------------------------------------
# Output normalization — tolerant compare, not brittle byte-exact matching.
# ---------------------------------------------------------------------------
def _normalize(raw: Any, sort_lists: bool = True) -> str:
    """Best-effort canonical form: parse as JSON, optionally sort lists, and
    re-serialize. Falls back to a stripped string if it isn't valid JSON at
    all (e.g. a crash printed a traceback instead of a result).

    `sort_lists=False` for problems whose output is a list where POSITION
    matters (e.g. Product of Array Except Self) — sorting would silently
    accept a wrong-order answer as correct."""
    if not isinstance(raw, str):
        raw = json.dumps(raw)
    s = raw.strip()
    try:
        parsed = json.loads(s)
    except Exception:
        return s
    if sort_lists and isinstance(parsed, list):
        try:
            parsed = sorted(parsed)
        except TypeError:
            pass  # not sortable (mixed types) — compare as-is
    return json.dumps(parsed, sort_keys=True)


class PistonUnavailableError(Exception):
    pass


async def _piston_execute(
    piston_language: str, piston_version: str, source: str, stdin: str, filename: Optional[str] = None
) -> Dict[str, Any]:
    file_entry = {"content": source}
    if filename:
        file_entry["name"] = filename
    payload = {
        "language": piston_language,
        "version": piston_version,
        "files": [file_entry],
        "stdin": stdin,
        "run_timeout": RUN_TIMEOUT_MS,
    }
    try:
        async with httpx.AsyncClient(timeout=PISTON_TIMEOUT_S) as client:
            resp = await client.post(f"{PISTON_URL}/execute", json=payload)
    except httpx.HTTPError as e:
        raise PistonUnavailableError(f"Could not reach code execution service: {e}") from e

    if resp.status_code != 200:
        raise PistonUnavailableError(f"Execution service returned {resp.status_code}: {resp.text[:300]}")

    data = resp.json()
    if "run" not in data:
        # Piston returns {"message": "..."} on e.g. unknown language/version.
        raise PistonUnavailableError(data.get("message", "Execution service returned an unexpected response"))
    return data["run"]


async def run_submission(problem: dict, code: str, language: str, sample_only: bool = False) -> Dict[str, Any]:
    """Run `code` against test cases of `problem`. Raises PistonUnavailableError
    if the execution backend itself could not be reached — callers should NOT
    charge credits in that case. Returns per-test results plus an overall
    pass/fail.

    `sample_only=True` (the free "Run" action) only executes the problem's
    `is_sample` test cases, with full input/expected/actual shown — this is
    exactly what "Run" should test against, matching the problem's own
    Examples. `sample_only=False` (the credited "Submit" action) executes
    EVERY test case, but only returns full detail for the sample ones; hidden
    cases report index/passed/crashed only, so a submission can never be used
    to read back the hidden suite's expected outputs."""
    lang_cfg = LANGUAGE_RUNTIMES.get(language)
    if not lang_cfg:
        raise ValueError(f"Unsupported language: {language}")
    entry_point = (problem.get("entry_point") or {}).get(language)
    if not entry_point:
        raise ValueError(f"Problem does not support language: {language}")

    params = problem.get("params", [])
    output_type = problem.get("output_type", "int_array_sorted")
    harness = build_harness(language, entry_point, params, output_type)
    # Java is order-sensitive: Piston runs Java via `java <file>.java` (JEP 330
    # single-file source launch), which executes whichever class is declared
    # FIRST in the file — so the harness's `Main` class must come before the
    # user's `Solution` class, unlike every other language here.
    if language == "java":
        # Strip any `import ...;` the user wrote themselves — the harness
        # above already imports java.util/stream/function/math, and since the
        # harness's Main class has to come FIRST in the file, a user-written
        # import (which would land after it) is a compile error, not just
        # redundant. Silently dropping it matches what most judges do: you
        # never need to write imports for the common stuff at all.
        user_code = re.sub(r"^\s*import\s+[\w.]+(?:\.\*)?\s*;\s*$", "", code, flags=re.MULTILINE)
        full_source = harness + "\n\n" + user_code
    else:
        full_source = code + harness

    all_cases = problem.get("test_cases", [])
    cases_to_run = [tc for tc in all_cases if tc.get("is_sample")] if sample_only else all_cases
    sort_lists = output_type != "int_array_ordered"

    results = []
    passed_count = 0
    for i, tc in enumerate(cases_to_run):
        stdin = json.dumps(tc["input"])
        try:
            run = await _piston_execute(
                lang_cfg["piston_language"], lang_cfg["piston_version"], full_source, stdin,
                filename=lang_cfg.get("filename"),
            )
        except PistonUnavailableError:
            raise  # bubble up — don't charge, don't record a partial submission
        stdout = run.get("stdout") or ""
        stderr = run.get("stderr") or ""
        exit_code = run.get("code")
        signal = run.get("signal")
        expected_norm = _normalize(tc["expected"], sort_lists=sort_lists)
        actual_norm = _normalize(stdout, sort_lists=sort_lists)
        crashed = bool(signal) or (exit_code not in (0, None))
        passed = (not crashed) and actual_norm == expected_norm
        if passed:
            passed_count += 1
        if sample_only or tc.get("is_sample"):
            results.append({
                "index": i,
                "input": tc["input"],
                "expected": tc["expected"],
                "actual_raw": stdout.strip(),
                "stderr": stderr.strip(),
                "passed": passed,
                "crashed": crashed,
                "hidden": False,
            })
        else:
            # Hidden case: report the verdict only, never the actual test data
            # or program output — that's exactly what a submission could be
            # used to fish for otherwise.
            results.append({"index": i, "passed": passed, "crashed": crashed, "hidden": True})

    total = len(results)
    return {
        "results": results,
        "passed_count": passed_count,
        "total": total,
        "all_passed": total > 0 and passed_count == total,
    }


# ---------------------------------------------------------------------------
# SQL grading — `question_type: "sql"`. Uses Python's built-in `sqlite3`
# (no new dependency) to seed a small, throwaway, in-memory database per
# problem/grading call from that problem's hand-written `schema_sql`, then
# runs both the submitted query and the problem's own hand-written
# `solution_query` against it and compares result sets. Expected rows are
# never hand-transcribed and stored — they're derived by EXECUTING the
# reference query fresh every time, so the schema and the expected output
# can never silently drift apart (the same "derive ground truth by actually
# running it" philosophy `practice_ai_service.generate_variant` uses for its
# reference solutions, just with SQL instead of Python).
# ---------------------------------------------------------------------------
def _sql_execute(schema_sql: str, query: str) -> Tuple[List[str], List[list]]:
    """Fresh in-memory SQLite DB: seed via `schema_sql`, then run `query`.
    Returns (column_names, rows). Raises sqlite3.Error on bad SQL (syntax
    error, unknown table/column, etc.) — the caller decides how to surface that."""
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(schema_sql)
        cur = conn.execute(query)
        columns = [d[0] for d in cur.description] if cur.description else []
        rows = [list(r) for r in cur.fetchall()]
        return columns, rows
    finally:
        conn.close()


def get_sql_table_preview(schema_sql: str) -> List[Dict[str, Any]]:
    """Table name/columns/sample rows, derived by actually seeding an
    in-memory DB and reading back `sqlite_master` + each table — so the
    frontend's schema preview can never drift from what grading actually
    runs against, since both read the exact same `schema_sql`."""
    if not schema_sql:
        return []
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(schema_sql)
        table_names = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            ).fetchall()
        ]
        out = []
        for name in table_names:
            cur = conn.execute(f"SELECT * FROM {name}")
            columns = [d[0] for d in cur.description]
            rows = [list(r) for r in cur.fetchall()]
            out.append({"name": name, "columns": columns, "rows": rows})
        return out
    finally:
        conn.close()


async def run_sql_submission(problem: dict, query: str) -> Dict[str, Any]:
    """Grades one submitted SQL query against `problem`'s seeded sample DB.
    Returns the same generic `{results, passed_count, total, all_passed}`
    shape `run_submission()` returns for code problems (`total` is always 1
    — a SQL problem is graded as a single query-correctness check, not
    multiple test cases) so `record_submission()`/the routes can treat both
    uniformly.

    Read-only by construction: rejects anything that isn't a SELECT/WITH
    query before ever executing it (SQLite's own `execute()` — as opposed to
    `executescript()` — also refuses multiple `;`-separated statements in one
    call, so this is defense in depth, not the only guard). The seeded DB is
    a fresh throwaway in-memory connection per call regardless, so even a
    mutation would only ever affect that single grading call's own scratch copy."""
    schema_sql = problem.get("schema_sql", "")
    solution_query = problem.get("solution_query", "")
    order_sensitive = bool(problem.get("order_sensitive", False))

    lowered = query.strip().lower().lstrip("(")
    if not (lowered.startswith("select") or lowered.startswith("with")):
        result_entry = {
            "index": 0, "passed": False, "hidden": False,
            "error": "Only SELECT queries are allowed for these problems.",
            "columns": [], "expected_rows": [], "actual_rows": [],
            "order_sensitive": order_sensitive,
        }
        return {"results": [result_entry], "passed_count": 0, "total": 1, "all_passed": False}

    try:
        expected_columns, expected_rows = _sql_execute(schema_sql, solution_query)
    except sqlite3.Error as e:
        # The problem's OWN reference query failing is an authoring bug, not
        # the user's fault — raise distinctly so the route surfaces a 502,
        # not "your query is wrong".
        raise RuntimeError(f"Reference solution query failed for problem {problem.get('_id')}: {e}") from e

    error = None
    actual_columns: List[str] = []
    actual_rows: List[list] = []
    try:
        actual_columns, actual_rows = _sql_execute(schema_sql, query)
    except sqlite3.Error as e:
        error = str(e)

    if error is None:
        # `key=repr` gives a total order across rows even when a column mixes
        # types (e.g. NULL alongside integers) — the same tolerant-fallback
        # spirit as `_normalize`'s code-grading comparison above.
        exp_cmp = expected_rows if order_sensitive else sorted(expected_rows, key=repr)
        act_cmp = actual_rows if order_sensitive else sorted(actual_rows, key=repr)
        passed = exp_cmp == act_cmp
    else:
        passed = False

    result_entry = {
        "index": 0,
        "passed": passed,
        "hidden": False,
        "error": error,
        "columns": actual_columns or expected_columns,
        "expected_rows": expected_rows,
        "actual_rows": actual_rows,
        "order_sensitive": order_sensitive,
    }
    return {
        "results": [result_entry],
        "passed_count": 1 if passed else 0,
        "total": 1,
        "all_passed": passed,
    }


# ---------------------------------------------------------------------------
# MCQ grading — `question_type: "mcq"` (Logical Reasoning + Computer
# Networks). Trivial equality check: no Piston, no LLM — see
# pricing_engine.DEFAULT_PRICING's `practice_mcq_submit` entry for why this
# is priced at (or near) zero.
# ---------------------------------------------------------------------------
def grade_mcq(problem: dict, selected_option_id: str) -> Dict[str, Any]:
    correct_id = problem.get("correct_option_id")
    passed = selected_option_id == correct_id
    return {"passed": passed, "correct_option_id": correct_id, "selected_option_id": selected_option_id}


async def run_raw_code(language: str, code: str, stdin: str = "") -> Dict[str, Any]:
    """Execute arbitrary source with no test-harness wrapping and no curated-problem
    contract — for consumers (Mock Interview's live-coding `run_code` agent tool)
    that need raw stdout/stderr/exit code for a problem that doesn't exist as a
    `practice_problems` doc, because it was invented on the fly by an LLM.

    Deliberately does NOT go through build_harness()/run_submission()/_normalize():
    those encode a fixed-params/expected-output grading contract that has no
    meaning here — the caller (the interviewer agent) judges the raw output itself.
    Raises PistonUnavailableError if the sandbox itself can't be reached — same
    as run_submission(), callers should not treat that as "the code is wrong".
    """
    lang_cfg = LANGUAGE_RUNTIMES.get(language)
    if not lang_cfg:
        raise ValueError(f"Unsupported language: {language}")
    run = await _piston_execute(
        lang_cfg["piston_language"], lang_cfg["piston_version"], code, stdin,
        filename=lang_cfg.get("filename"),
    )
    return {
        "stdout": (run.get("stdout") or "")[:8000],
        "stderr": (run.get("stderr") or "")[:4000],
        "exit_code": run.get("code"),
        "signal": run.get("signal"),
    }


async def record_submission(user_id: str, problem_id: str, code: Optional[str], language: Optional[str],
                            run_result: Dict[str, Any], extra: Optional[Dict[str, Any]] = None) -> dict:
    """Shared submission ledger for EVERY question type (code/sql/mcq/design)
    — every grading path writes here so `get_solved_problem_ids`/
    `get_progress`/the streak computation (all of which key off `all_passed`
    and `created_at` alone) keep working unmodified regardless of type.

    `code`/`language` are optional (an MCQ submission has neither — it has a
    `selected_option_id`, passed via `extra`; a design submission has
    free-text prose passed as `code` and no `language`). `extra` merges in
    whatever type-specific fields the caller needs to persist."""
    doc = {
        "user_id": user_id,
        "problem_id": problem_id,
        "passed_count": run_result.get("passed_count", 0),
        "total": run_result.get("total", 0),
        "all_passed": run_result.get("all_passed", False),
        "created_at": now_iso(),
    }
    if code is not None:
        doc["code"] = code[:20000]
    if language is not None:
        doc["language"] = language
    if "results" in run_result:
        doc["results"] = run_result["results"]
    if extra:
        doc.update(extra)
    ins = await practice_submissions_col.insert_one(doc)
    doc["_id"] = str(ins.inserted_id)
    return doc


async def get_submission(user_id: str, submission_id: str) -> Optional[dict]:
    """Full submission doc (code/language/results included) — scoped to the
    requesting user only. Used by AI Feedback, which needs the actual failed
    results, not just the redacted client-facing summary."""
    from bson import ObjectId
    doc = await practice_submissions_col.find_one({"_id": ObjectId(submission_id), "user_id": user_id})
    if doc:
        doc["_id"] = str(doc["_id"])
    return doc


async def list_submissions(user_id: str, problem_id: str, limit: int = 20) -> List[dict]:
    """Most-recent-first, scoped to the requesting user only — never another
    user's submissions, even for the same problem."""
    cursor = (
        practice_submissions_col.find({"user_id": user_id, "problem_id": problem_id})
        .sort("created_at", -1)
        .limit(limit)
    )
    out = []
    async for doc in cursor:
        out.append({
            "id": str(doc["_id"]),
            # .get(), not [] — mcq/design submissions have neither field
            # (see record_submission's docstring).
            "language": doc.get("language"),
            "code": doc.get("code"),
            "passed_count": doc["passed_count"],
            "total": doc["total"],
            "all_passed": doc["all_passed"],
            "created_at": doc["created_at"],
        })
    return out
