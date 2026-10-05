"""The prompt-to-action loop: user prompt -> Claude -> real MCP tool calls.

Modeled directly on services/interview_agent.py's run_turn() — the only other
Anthropic tool-use loop in this codebase — generalized from a hardcoded tool
list to whatever tools the user's currently-connected, enabled connectors
expose. Two public entry points share the same setup/tool-loop shape:

- run_prompt(): single-shot, used by the standalone "Try a prompt" tester on
  the Connectors page (routers/mcp_routes.py's POST /mcp/prompt).
- stream_prompt_with_tools(): an AsyncGenerator yielding the same event shape
  services/ai_service.py's stream_ai_response() does, so routers/chat_routes.py
  can swap one for the other with no change to persistence/billing — this is
  what makes every connected, enabled connector usable from the main AI
  Workspace chat, not just a side panel.
"""
import json
import logging
from typing import Any, AsyncGenerator, Dict, List, Tuple

from db import mcp_audit_log_col, mcp_connections_col, now_iso
from services.llm_client import LlmChat
from services.mcp.client_host import ConnectorSessionPool, split_namespaced
from services.mcp.registry import connector_catalog_summary, get_connector

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 10
DEFAULT_TOOL_MODEL = "claude-sonnet-5"

SYSTEM_PROMPT_TEMPLATE = """You are an assistant that performs real actions on the user's behalf across \
third-party services they've explicitly connected. You may ONLY act within the connected services listed \
below, using the tools provided — never claim to have done something you didn't actually call a tool for.

CONNECTED SERVICES: {connector_names}

ALL SERVICES THIS PLATFORM SUPPORTS (connected and not-yet-connected — use this to tell the user exactly \
what to connect when their request needs a service not listed above as connected; never attempt, fake, or \
silently ignore a request for a not-connected service):
{catalog}

Use tools as needed to fulfill the user's request, including calling multiple tools across multiple \
services if the request requires it. If the request needs a service that isn't connected, tell the user \
plainly which one to connect from the Connectors page — don't attempt it, refuse vaguely, or pretend you did \
it. When finished, give a clear, concise plain-language summary of what you did or found — the user cannot \
see your tool calls, only your final reply."""


async def _connected_connector_ids(user_id: str) -> List[str]:
    cursor = mcp_connections_col.find(
        {"user_id": user_id, "enabled": {"$ne": False}}, {"connector_id": 1},
    )
    return [doc["connector_id"] async for doc in cursor]


async def user_has_enabled_connectors(user_id: str) -> bool:
    return bool(await _connected_connector_ids(user_id))


def _summarize(value: Any) -> str:
    try:
        return json.dumps(value)[:500]
    except Exception:
        return str(value)[:500]


async def _open_and_collect_tools(pool: ConnectorSessionPool, connector_ids: List[str]) -> Tuple[List[dict], List[str]]:
    """Open an MCP session per connector and gather their tool schemas.

    Shared by run_prompt() and stream_prompt_with_tools() so the "connect +
    list_tools" setup isn't duplicated between the one-shot and streaming paths.
    """
    tools: List[dict] = []
    connected_names: List[str] = []
    for connector_id in connector_ids:
        cfg = get_connector(connector_id)
        if not cfg:
            continue
        try:
            await pool.connect(connector_id)
            tools.extend(await pool.list_tools_anthropic(connector_id))
            connected_names.append(cfg.display_name)
        except Exception as e:
            logger.warning(f"Could not start MCP session for {connector_id}/{pool.user_id}: {e}")
    return tools, connected_names


def _build_system_prompt(user_id: str, connector_ids: List[str], connected_names: List[str]) -> str:
    catalog = connector_catalog_summary(set(connector_ids))
    return SYSTEM_PROMPT_TEMPLATE.format(connector_names=", ".join(connected_names) or "none", catalog=catalog)


async def _execute_tool_calls(
    user_id: str, pool: ConnectorSessionPool, tool_uses: list,
) -> Tuple[List[dict], List[dict]]:
    """Run every tool_use block from one assistant turn, audit-logging each call.

    Returns (anthropic tool_result content blocks, plain tool-call log entries).
    """
    tool_results = []
    tool_call_log = []
    for tu in tool_uses:
        connector_id, bare_tool_name = split_namespaced(tu.name)
        result = await pool.call_tool(connector_id, bare_tool_name, tu.input)
        success = "error" not in result
        await mcp_audit_log_col.insert_one({
            "user_id": user_id,
            "connector_id": connector_id,
            "tool_name": bare_tool_name,
            "arguments": _summarize(tu.input),
            "result_summary": _summarize(result),
            "success": success,
            "created_at": now_iso(),
        })
        tool_call_log.append({
            "connector_id": connector_id, "tool_name": bare_tool_name,
            "arguments": tu.input, "success": success,
        })
        tool_results.append({
            "type": "tool_result", "tool_use_id": tu.id, "content": json.dumps(result)[:4000],
            "is_error": not success,
        })
    return tool_results, tool_call_log


async def run_prompt(user_id: str, prompt: str) -> Dict[str, Any]:
    """Single-shot tool-use turn — backs the Connectors page's test box."""
    connector_ids = await _connected_connector_ids(user_id)
    if not connector_ids:
        return {
            "reply": "You haven't connected any services yet — connect one from the Connectors page first.",
            "tool_calls": [],
        }

    tool_call_log: List[Dict[str, Any]] = []
    final_text = ""

    async with ConnectorSessionPool(user_id) as pool:
        tools, connected_names = await _open_and_collect_tools(pool, connector_ids)
        system_prompt = _build_system_prompt(user_id, connector_ids, connected_names)
        chat = LlmChat(system_message=system_prompt).with_model("anthropic", DEFAULT_TOOL_MODEL, max_tokens=2048)
        messages: List[dict] = [{"role": "user", "content": prompt}]

        for _ in range(MAX_TOOL_ITERATIONS):
            resp = await chat.create_with_tools(messages, tools, system=system_prompt)
            messages.append({"role": "assistant", "content": resp.content})

            tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
            text_blocks = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
            if text_blocks:
                final_text = "\n".join(text_blocks).strip()

            if not tool_uses:
                break

            tool_results, new_log = await _execute_tool_calls(user_id, pool, tool_uses)
            tool_call_log.extend(new_log)
            messages.append({"role": "user", "content": tool_results})

            if resp.stop_reason != "tool_use":
                break

    return {
        "reply": final_text or "I wasn't able to produce a response — please try rephrasing your request.",
        "tool_calls": tool_call_log,
    }


async def stream_prompt_with_tools(
    user_id: str, conv_id: str, prompt: str, history: List[Dict[str, str]],
    model: str = DEFAULT_TOOL_MODEL,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Tool-use turn for the main AI Workspace chat, yielding the same event
    shape services/ai_service.py's stream_ai_response() yields
    ({"type": "meta"|"delta"|"done"|"error", ...}) plus one additive
    {"type": "tool_status", "message": ...} event right before each tool call —
    routers/chat_routes.py forwards that one straight through to the frontend
    and ignores it for persistence/billing purposes, same as "warn" today.

    Not streamed token-by-token even for the final answer (each loop iteration
    is one non-streaming Anthropic call, same as run_prompt()) — a known,
    acceptable simplification; see CONNECTOR_SETUP.md / the project plan.
    """
    connector_ids = await _connected_connector_ids(user_id)
    try:
        async with ConnectorSessionPool(user_id) as pool:
            tools, connected_names = await _open_and_collect_tools(pool, connector_ids)
            system_prompt = _build_system_prompt(user_id, connector_ids, connected_names)
            yield {"type": "meta", "provider": "anthropic", "model": model}

            chat = LlmChat(system_message=system_prompt).with_model("anthropic", model, max_tokens=4096)
            messages: List[dict] = [{"role": h["role"], "content": h["content"]} for h in history]
            messages.append({"role": "user", "content": prompt})
            final_text = ""

            for _ in range(MAX_TOOL_ITERATIONS):
                resp = await chat.create_with_tools(messages, tools, system=system_prompt)
                messages.append({"role": "assistant", "content": resp.content})

                tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
                text_blocks = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
                if text_blocks:
                    final_text = "\n".join(text_blocks).strip()

                if not tool_uses:
                    break

                for tu in tool_uses:
                    connector_id, _ = split_namespaced(tu.name)
                    cfg = get_connector(connector_id)
                    yield {"type": "tool_status", "message": f"Using {cfg.display_name if cfg else connector_id}..."}

                tool_results, _ = await _execute_tool_calls(user_id, pool, tool_uses)
                messages.append({"role": "user", "content": tool_results})

                if resp.stop_reason != "tool_use":
                    break

        text = final_text or "I wasn't able to produce a response — please try rephrasing your request."
        yield {"type": "delta", "content": text}
        yield {"type": "done", "content": text, "provider": "anthropic", "model": model}
    except Exception as e:
        logger.exception(f"stream_prompt_with_tools failed for user {user_id}")
        yield {"type": "error", "message": str(e)}
