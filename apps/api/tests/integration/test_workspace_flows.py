"""Workspace orchestration over HTTP: /mcp/connectors listing, SSE plan/step
events from /chat/stream (with the orchestrator's pool + model faked), saved
timeline on the stored message, and /mcp/steps/retry."""
import json

import pytest

from db import messages_col, mcp_connections_col, wallets_col
from services.mcp import orchestrator_service as orch
from tests.unit.test_mcp_orchestrator import FakeChat, FakePool, _text, _tool
from types import SimpleNamespace

pytestmark = pytest.mark.integration


def test_connectors_list_is_friendly_when_unconfigured(client, auth_user):
    _, _, headers = auth_user
    r = client.get("/api/mcp/connectors", headers=headers)
    assert r.status_code == 200
    by_id = {c["id"]: c for c in r.json()}
    assert by_id["linear"]["auth_type"] == "api_key" and by_id["linear"]["mcp_status"] == "ready"
    assert by_id["linear"]["notes"]
    assert by_id["slack"]["configured"] is False and by_id["slack"]["connected"] is False


def test_stream_emits_plan_and_steps_and_saves_timeline(client, auth_user, monkeypatch):
    user, _, headers = auth_user
    import asyncio
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        mcp_connections_col.insert_one({"user_id": user["id"], "connector_id": "linear", "enabled": True})
    )
    monkeypatch.setattr(orch, "ConnectorSessionPool", FakePool)
    monkeypatch.setattr(orch, "LlmChat", FakeChat)
    FakePool.results = {"linear.t": {"result": "- ENG-1 Fix\n- ENG-2 Ship"}}
    FakeChat.script = [
        SimpleNamespace(stop_reason="tool_use", content=[_text("1. List issues"), _tool("a", "linear__t")]),
        SimpleNamespace(stop_reason="end_turn", content=[_text("You have 2 issues.")]),
    ]
    r = client.post("/api/chat/stream", json={"content": "what's open?"}, headers=headers)
    assert r.status_code == 200, r.text
    events = []
    for chunk in r.text.split("\n\n"):
        if chunk.startswith("data:") and chunk[5:].strip().startswith("{"):
            events.append(json.loads(chunk[5:].strip()))
    types = [e["type"] for e in events]
    assert "plan" in types and "step" in types and "done" in types
    statuses = [e["status"] for e in events if e["type"] == "step"]
    assert statuses == ["pending", "running", "done"]

    conv_id = next(e["conversation_id"] for e in events if e["type"] == "conversation")
    detail = client.get(f"/api/chat/conversations/{conv_id}", headers=headers).json()
    asst = [m for m in detail["messages"] if m["role"] == "assistant"][0]
    assert asst["plan"]["items"] == ["List issues"]
    assert asst["steps"][0]["status"] == "done"


def test_retry_endpoint(client, auth_user, monkeypatch):
    user, _, headers = auth_user
    r = client.post("/api/mcp/steps/retry", json={"connector_id": "slack", "tool": "list_channels"}, headers=headers)
    assert r.status_code == 400


def test_mention_of_unconnected_connector_shows_connect_step(client, auth_user):
    _, _, headers = auth_user
    r = client.post("/api/chat/stream", json={"content": "@GitHub list my PRs", "mentions": ["github"]}, headers=headers)
    events = [json.loads(c[5:].strip()) for c in r.text.split("\n\n") if c.startswith("data:") and c[5:].strip().startswith("{")]
    step = next(e for e in events if e["type"] == "step")
    assert step["status"] == "needs_connect" and step["connector_id"] == "github"
    assert any(e["type"] == "done" for e in events)
