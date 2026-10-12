"""Unit tests for services/mcp/orchestrator_service.py — the structured
plan/step event stream, per-step failure handling and the retry path, with the
MCP session pool and the LLM both replaced by fakes (no network, no subprocess).
"""
from types import SimpleNamespace

import pytest

from db import mcp_connections_col
from services.mcp import orchestrator_service as orch

pytestmark = pytest.mark.anyio


def _text(t):
    return SimpleNamespace(type="text", text=t)


def _tool(id_, name, **inp):
    return SimpleNamespace(type="tool_use", id=id_, name=name, input=inp)


class FakePool:
    """Stands in for ConnectorSessionPool. `results` maps 'conn.tool' -> dict."""
    results: dict = {}

    def __init__(self, user_id):
        self.user_id = user_id

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def connect(self, cid):
        pass

    async def list_tools_anthropic(self, cid):
        return [{"name": f"{cid}__t", "description": "", "input_schema": {"type": "object"}}]

    async def call_tool(self, cid, tool, args):
        return self.results[f"{cid}.{tool}"]


class FakeChat:
    script: list = []

    def __init__(self, system_message=""):
        pass

    def with_model(self, *a, **k):
        return self

    async def create_with_tools(self, messages, tools, system=None):
        return self.script.pop(0)


@pytest.fixture
def patched(monkeypatch):
    monkeypatch.setattr(orch, "ConnectorSessionPool", FakePool)
    monkeypatch.setattr(orch, "LlmChat", FakeChat)
    return FakePool, FakeChat


async def _connect(user_id, *cids):
    for c in cids:
        await mcp_connections_col.insert_one({"user_id": user_id, "connector_id": c, "enabled": True})


async def test_plan_steps_failure_and_final_answer(patched):
    pool, chat = patched
    await _connect("u1", "slack", "github")
    pool.results = {
        "github.list_issues": {"result": "- #1 [open] Bug\n- #2 [open] Crash"},
        "slack.post_message": {"error": "Slack returned HTTP 403: missing_scope"},
    }
    chat.script = [
        SimpleNamespace(stop_reason="tool_use", content=[
            _text("1. Find open issues\n2. Post them to Slack"),
            _tool("a", "github__list_issues", repo="o/r"),
        ]),
        SimpleNamespace(stop_reason="tool_use", content=[_tool("b", "slack__post_message", channel="#g", text="hi")]),
        SimpleNamespace(stop_reason="end_turn", content=[_text("Found 2 issues; Slack post failed.")]),
    ]
    events = [e async for e in orch.stream_prompt_with_tools("u1", "c1", "go", [])]
    types = [e["type"] for e in events]
    assert types[0] == "meta" and types[-1] == "done"

    plan = next(e for e in events if e["type"] == "plan")
    assert plan["items"] == ["Find open issues", "Post them to Slack"]

    gh = [e["status"] for e in events if e["type"] == "step" and e["id"] == "s1"]
    assert gh == ["pending", "running", "done"]
    done = [e for e in events if e["type"] == "step" and e["id"] == "s1"][-1]
    assert done["summary"].startswith("2 items")
    assert done["args_readable"] == [{"label": "Repo", "value": "o/r"}]

    slack = [e for e in events if e["type"] == "step" and e["id"] == "s2"][-1]
    assert slack["status"] == "failed" and slack["retryable"]
    assert "permission" in slack["friendly_error"]
    assert events[-1]["content"].startswith("Found 2 issues")


async def test_run_prompt_collects_steps(patched):
    pool, chat = patched
    await _connect("u2", "linear")
    pool.results = {"linear.t": {"result": "ok"}}
    chat.script = [
        SimpleNamespace(stop_reason="tool_use", content=[_tool("a", "linear__t")]),
        SimpleNamespace(stop_reason="end_turn", content=[_text("done")]),
    ]
    out = await orch.run_prompt("u2", "x")
    assert out["reply"] == "done"
    assert [s["status"] for s in out["steps"]] == ["done"]
    assert out["tool_calls"][0]["success"] is True


async def test_retry_step_reports_failure_friendly(patched):
    pool, _ = patched
    await _connect("u3", "slack")
    pool.results = {"slack.list_channels": {"error": "Tool call timed out after 45s"}}
    step = await orch.retry_step("u3", "slack", "list_channels", {})
    assert step["status"] == "failed"
    assert "respond in time" in step["friendly_error"]


async def test_retry_requires_connection(patched):
    with pytest.raises(ValueError):
        await orch.retry_step("nobody", "slack", "list_channels", {})


async def test_no_connectors_gives_friendly_message():
    events = [e async for e in orch.stream_prompt_with_tools("empty", "c", "hi", [])]
    assert "/connectors" in events[-1]["content"]


async def test_mention_restricts_tools_and_destructive_waits_for_confirm(patched):
    pool, chat = patched
    await _connect("u5", "slack", "gmail")
    pool.results = {"gmail.send_message": {"result": "sent"}}
    chat.script = [
        SimpleNamespace(stop_reason="tool_use", content=[_tool("a", "gmail__send_message", to="x@y.z")]),
        SimpleNamespace(stop_reason="end_turn", content=[_text("Waiting for your confirmation.")]),
    ]
    events = [e async for e in orch.stream_prompt_with_tools("u5", "c", "@Gmail send", [], mentions=["gmail", "github"])]
    steps = [e for e in events if e["type"] == "step"]
    assert steps[0]["status"] == "needs_connect" and steps[0]["connector_id"] == "github"
    last = [e for e in steps if e["connector_id"] == "gmail"][-1]
    assert last["status"] == "awaiting_confirm"
    assert orch.needs_confirmation("delete_event") and not orch.needs_confirmation("list_events")
