"""The prompt-to-action loop: user prompt -> model -> real MCP tool calls.

Modeled on services/interview_agent.py's run_turn() — generalized from a
hardcoded tool list to whatever tools the user's currently-connected, enabled
connectors expose. One core generator, `_orchestrate()`, yields structured
events; the two public entry points are thin wrappers over it:

- run_prompt(): collects the events into a single result, used by the
  "Quick test" box on the Connectors page (POST /mcp/prompt).
- stream_prompt_with_tools(): re-yields the events to routers/chat_routes.py,
  which forwards them over SSE to the Workspace chat UI.

Event shapes (all dicts with a "type"):
  meta        {provider, model}
  plan        {text, items: [str]}            the model's short plan, once
  step        {id, index, status, connector_id, connector_name, tool, title,
               args, args_readable, summary, raw, error, friendly_error,
               duration_ms, retryable}
              status: pending -> running -> done | failed (same id re-emitted)
  delta/done  final answer text
  error       {message}

step status also includes "needs_connect" (a @-mentioned connector isn't
connected; the UI shows a Connect button) and "awaiting_confirm" (a
destructive/irreversible tool call that is held until the user confirms it in
the timeline, which re-runs it through POST /mcp/steps/retry).                        always human-readable
"""
import asyncio
import json
import logging
import os
import re
import time
from typing import Any, AsyncGenerator, Dict, List, Optional, Tuple

from db import mcp_audit_log_col, mcp_connections_col, now_iso
from services.llm_client import LlmChat
from services.mcp.client_host import ConnectorSessionPool, split_namespaced
from services.mcp.registry import connector_catalog_summary, get_connector

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 10
DEFAULT_TOOL_MODEL = "claude-sonnet-5"
# Demo mode hides raw provider error text from step details (the friendly
# message is always shown) so a failed call on stage never shows a stack/JSON dump.
DEMO_MODE = os.environ.get("MCP_DEMO_MODE", "").lower() in ("1", "true", "yes")

SYSTEM_PROMPT_TEMPLATE = """You are an assistant that performs real actions on the user's behalf across \
third-party services they've explicitly connected. You may ONLY act within the connected services listed \
below, using the tools provided — never claim to have done something you didn't actually call a tool for.

CONNECTED SERVICES: {connector_names}

ALL SERVICES THIS PLATFORM SUPPORTS (connected and not-yet-connected — use this to tell the user exactly \
what to connect when their request needs a service not listed above as connected; never attempt, fake, or \
silently ignore a request for a not-connected service):
{catalog}
{mention_note}
WORKFLOW:
1. If the request needs two or more tool calls, begin your FIRST reply with a short numbered plan (one line \
per step, max 6 lines, plain language, no tool names), then immediately start calling tools. For a single \
simple lookup, skip the plan and just call the tool.
2. Use tools as needed, including across multiple services. Pass ids returned by earlier steps into later ones.
3. If a tool fails, do not retry the same call more than once. Continue with any remaining independent steps, \
and in the final answer say in one plain sentence what could not be done and why (never paste error text, \
JSON or stack traces).
4. Some tools (delete, send, merge, ...) are held for the user's one-click confirmation: they return \
"not executed yet"; treat that as success-pending and tell the user to confirm it in the timeline.
5. If the request needs a service that isn't connected, tell the user plainly which one to connect, with a \
markdown link exactly like this: [Connectors page](/connectors) — don't attempt it or pretend you did it.
6. Finish with a clear, concise plain-language answer of what you did or found — the user sees a live \
timeline of your tool calls, so don't repeat raw tool output; summarize it."""


# Tool names (generic across every connector) that are destructive or irreversible
# and therefore wait for a one-click user confirmation instead of auto-running.
_CONFIRM_RE = re.compile(r"(^|_)(delete|remove|send|merge|archive|cancel|revoke|trash|destroy|drop)(_|$)")


def needs_confirmation(tool: str) -> bool:
    return bool(_CONFIRM_RE.search(tool or ""))


# ---------- small helpers ----------

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


def _clip(text: Any, n: int = 160) -> str:
    s = "" if text is None else str(text).replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def humanize(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


def readable_args(args: Dict[str, Any]) -> List[Dict[str, str]]:
    out = []
    for k, v in (args or {}).items():
        val = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
        out.append({"label": humanize(k), "value": _clip(val, 140)})
    return out


def summarize_result(text: str) -> str:
    """One-line, human-friendly description of a tool's text output."""
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    if not lines:
        return "Done (no output)"
    bullets = [l for l in lines if l.startswith("- ")]
    if len(lines) > 1 and len(bullets) >= len(lines) / 2:
        return f"{len(bullets)} item{'s' if len(bullets) != 1 else ''} — {_clip(bullets[0][2:], 90)}"
    return _clip(" ".join(lines), 160)


def friendly_error(connector_name: str, raw: str) -> str:
    """Map a raw provider/tool error to one plain sentence for the timeline."""
    r = (raw or "").lower()
    if any(k in r for k in ("401", "invalid_auth", "unauthorized", "token_expired", "invalid_token", "reconnect", "expired", "not_authed", "invalid_grant", "unauthenticated")):
        return f"{connector_name} rejected the saved credentials — reconnect it on the Connectors page."
    if any(k in r for k in ("403", "forbidden", "missing_scope", "not_allowed", "permission", "restricted_resource", "access_denied")):
        return f"{connector_name} didn't allow that action — the connected account may lack permission or access to that item."
    if "404" in r or "not_found" in r or "not found" in r or "channel_not_found" in r:
        return f"{connector_name} couldn't find that item — check the name or id."
    if "429" in r or "rate" in r and "limit" in r or "ratelimited" in r:
        return f"{connector_name} is rate-limiting requests right now — try again in a minute."
    if any(k in r for k in ("timeout", "timed out", "could not be reached", "network", "connection")):
        return f"{connector_name} didn't respond in time — check your connection and retry."
    if "isn't wired up" in r or "not wired" in r:
        return f"{connector_name} can be connected, but actions aren't available for it yet."
    if "422" in r or "400" in r or "invalid" in r or "validation" in r:
        return f"{connector_name} rejected the request details — the inputs may need adjusting."
    return f"{connector_name} couldn't complete that action. You can retry, or open details to see why."


def _step_payload(step_id: str, index: int, status: str, connector_id: str, tool: str,
                  args: Dict[str, Any], **extra) -> Dict[str, Any]:
    cfg = get_connector(connector_id)
    name = cfg.display_name if cfg else connector_id
    base = {
        "type": "step", "id": step_id, "index": index, "status": status,
        "connector_id": connector_id, "connector_name": name, "tool": tool,
        "title": f"{name}: {humanize(tool)}",
        "args": args, "args_readable": readable_args(args),
        "summary": None, "raw": None, "error": None, "friendly_error": None,
        "duration_ms": None, "retryable": False,
    }
    base.update(extra)
    return base


def _parse_plan(text: str) -> Dict[str, Any]:
    items = []
    for line in text.splitlines():
        m = re.match(r"^\s*(?:\d+[.)]|[-*•])\s+(.*\S)", line)
        if m:
            items.append(m.group(1).strip())
    return {"type": "plan", "text": text.strip(), "items": items[:8]}


async def _open_and_collect_tools(
    pool: ConnectorSessionPool, connector_ids: List[str],
) -> Tuple[List[dict], List[str], List[Tuple[str, str]]]:
    """Open an MCP session per connector and gather their tool schemas.

    Returns (tools, connected display names, [(connector_id, raw_error)] for
    connectors that failed to start — surfaced as failed steps, not swallowed).
    """
    tools: List[dict] = []
    connected_names: List[str] = []
    failures: List[Tuple[str, str]] = []
    for connector_id in connector_ids:
        cfg = get_connector(connector_id)
        if not cfg:
            continue
        try:
            await asyncio.wait_for(pool.connect(connector_id), timeout=30)
            tools.extend(await pool.list_tools_anthropic(connector_id))
            connected_names.append(cfg.display_name)
        except Exception as e:
            logger.warning(f"Could not start MCP session for {connector_id}/{pool.user_id}: {e!r}")
            failures.append((connector_id, str(e) or type(e).__name__))
    return tools, connected_names, failures


def _build_system_prompt(connector_ids: List[str], connected_names: List[str], mentioned: List[str]) -> str:
    catalog = connector_catalog_summary(set(connector_ids))
    note = ""
    if mentioned:
        names = ", ".join(get_connector(m).display_name for m in mentioned)
        note = (f"\nThe user explicitly @-mentioned: {names}. Use ONLY these services' tools for this request, "
                "and act autonomously — don't ask for confirmation before read actions or ordinary writes.\n")
    return SYSTEM_PROMPT_TEMPLATE.format(
        connector_names=", ".join(connected_names) or "none", catalog=catalog, mention_note=note)


async def _run_tool(user_id: str, pool: ConnectorSessionPool, connector_id: str, tool: str,
                    args: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    """Execute one tool call and audit-log it. Returns (result dict, duration ms)."""
    start = time.monotonic()
    result = await pool.call_tool(connector_id, tool, args)
    ms = int((time.monotonic() - start) * 1000)
    await mcp_audit_log_col.insert_one({
        "user_id": user_id, "connector_id": connector_id, "tool_name": tool,
        "arguments": _summarize(args), "result_summary": _summarize(result),
        "success": "error" not in result, "created_at": now_iso(),
    })
    return result, ms


def _finish_step(step_id: str, index: int, connector_id: str, tool: str, args: Dict[str, Any],
                 result: Dict[str, Any], ms: int) -> Dict[str, Any]:
    cfg = get_connector(connector_id)
    name = cfg.display_name if cfg else connector_id
    if "error" in result:
        raw = result["error"]
        return _step_payload(
            step_id, index, "failed", connector_id, tool, args,
            error=raw, friendly_error=friendly_error(name, raw), duration_ms=ms, retryable=True,
            raw="Details hidden in demo mode." if DEMO_MODE else raw,
        )
    text = result.get("result", "")
    return _step_payload(
        step_id, index, "done", connector_id, tool, args,
        summary=summarize_result(text), raw=text[:4000], duration_ms=ms,
    )


# ---------- core loop ----------

async def _orchestrate(
    user_id: str, prompt: str, history: List[Dict[str, str]], model: str, max_tokens: int,
    mentions: Optional[List[str]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    connected_all = await _connected_connector_ids(user_id)
    mentioned = [m for m in dict.fromkeys(mentions or []) if get_connector(m)]
    step_counter = 0
    missing: List[str] = []
    if mentioned:
        missing = [m for m in mentioned if m not in connected_all]
        mentioned = [m for m in mentioned if m in connected_all]
        connector_ids = mentioned or ([] if missing else connected_all)
    else:
        connector_ids = connected_all

    if missing:
        yield {"type": "meta", "provider": "anthropic", "model": model}
    for cid in missing:
        step_counter += 1
        cfg = get_connector(cid)
        if cfg.mcp_status == "ready":
            yield _step_payload(f"s{step_counter}", step_counter, "needs_connect", cid, "connect", {},
                                title=f"Connect {cfg.display_name}",
                                friendly_error=f"{cfg.display_name} isn't connected yet — connect it to run this.")
        else:
            yield _step_payload(f"s{step_counter}", step_counter, "failed", cid, "connect", {},
                                title=f"{cfg.display_name} unavailable",
                                friendly_error=f"{cfg.display_name} can be listed, but actions aren't available for it yet.")

    if not connector_ids:
        if missing:
            names = ", ".join(get_connector(m).display_name for m in missing)
            text = f"I need {names} connected to do that. Use the Connect button above (or the [Connectors page](/connectors)), then ask again."
        else:
            text = "You haven't connected any services yet — connect one from the [Connectors page](/connectors) first."
        yield {"type": "delta", "content": text}
        yield {"type": "done", "content": text, "provider": "anthropic", "model": model}
        return

    async with ConnectorSessionPool(user_id) as pool:
        tools, connected_names, failures = await _open_and_collect_tools(pool, connector_ids)
        if not missing:
            yield {"type": "meta", "provider": "anthropic", "model": model}

        for cid, raw in failures:
            step_counter += 1
            cfg = get_connector(cid)
            name = cfg.display_name if cfg else cid
            yield _step_payload(
                f"s{step_counter}", step_counter, "failed", cid, "connect", {},
                title=f"Connect to {name}", error=raw, friendly_error=friendly_error(name, raw),
                raw="Details hidden in demo mode." if DEMO_MODE else raw,
            )

        system_prompt = _build_system_prompt(connector_ids, connected_names, mentioned)
        chat = LlmChat(system_message=system_prompt).with_model("anthropic", model, max_tokens=max_tokens)
        messages: List[dict] = [{"role": h["role"], "content": h["content"]} for h in history]
        messages.append({"role": "user", "content": prompt})
        final_text = ""
        plan_sent = False

        for _ in range(MAX_TOOL_ITERATIONS):
            resp = await chat.create_with_tools(messages, tools, system=system_prompt)
            messages.append({"role": "assistant", "content": resp.content})

            tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
            text = "\n".join(b.text for b in resp.content if getattr(b, "type", None) == "text").strip()
            if text:
                final_text = text
            if not tool_uses:
                break

            if text and not plan_sent:
                plan_sent = True
                yield _parse_plan(text)

            # Announce every call in this turn as pending, then run in order.
            prepared = []
            for tu in tool_uses:
                step_counter += 1
                connector_id, bare = split_namespaced(tu.name)
                prepared.append((f"s{step_counter}", step_counter, connector_id, bare, tu))
                yield _step_payload(f"s{step_counter}", step_counter, "pending", connector_id, bare, tu.input)

            tool_results = []
            for step_id, index, connector_id, bare, tu in prepared:
                if needs_confirmation(bare):
                    yield _step_payload(
                        step_id, index, "awaiting_confirm", connector_id, bare, tu.input,
                        friendly_error="This action can't be undone, so it's waiting for your confirmation.",
                    )
                    tool_results.append({
                        "type": "tool_result", "tool_use_id": tu.id, "is_error": False,
                        "content": "Not executed yet: the user must confirm this action in the timeline.",
                    })
                    continue
                yield _step_payload(step_id, index, "running", connector_id, bare, tu.input)
                result, ms = await _run_tool(user_id, pool, connector_id, bare, tu.input)
                done = _finish_step(step_id, index, connector_id, bare, tu.input, result, ms)
                yield done
                tool_results.append({
                    "type": "tool_result", "tool_use_id": tu.id,
                    "content": json.dumps(result)[:4000], "is_error": "error" in result,
                })
            messages.append({"role": "user", "content": tool_results})

            if resp.stop_reason != "tool_use":
                break

    final = final_text or "I wasn't able to produce a response — please try rephrasing your request."
    yield {"type": "delta", "content": final}
    yield {"type": "done", "content": final, "provider": "anthropic", "model": model}


def _friendly_fatal(e: Exception) -> str:
    logger.exception("Workspace orchestration failed")
    if "api_key" in str(e).lower() or "is not set" in str(e):
        return "The AI model isn't configured on this server yet, so I can't plan actions. Please contact the admin."
    return "Something went wrong while running your request. Nothing further was changed — please try again."


# ---------- public entry points ----------

async def stream_prompt_with_tools(
    user_id: str, conv_id: str, prompt: str, history: List[Dict[str, str]],
    model: str = DEFAULT_TOOL_MODEL, mentions: Optional[List[str]] = None,
) -> AsyncGenerator[Dict[str, Any], None]:
    """Workspace chat entry point — yields the event shapes documented above.

    Not streamed token-by-token for the final answer (each loop iteration is
    one non-streaming model call); the live timeline carries the progress.
    """
    try:
        async for evt in _orchestrate(user_id, prompt, history, model, max_tokens=4096, mentions=mentions):
            yield evt
    except Exception as e:
        yield {"type": "error", "message": _friendly_fatal(e)}


async def run_prompt(user_id: str, prompt: str, mentions: Optional[List[str]] = None) -> Dict[str, Any]:
    """Single-shot turn — backs the Connectors page's test box."""
    steps: Dict[str, Dict[str, Any]] = {}
    reply = ""
    plan: Optional[Dict[str, Any]] = None
    try:
        async for evt in _orchestrate(user_id, prompt, [], DEFAULT_TOOL_MODEL, max_tokens=2048, mentions=mentions):
            if evt["type"] == "step":
                steps[evt["id"]] = evt
            elif evt["type"] == "plan":
                plan = evt
            elif evt["type"] == "done":
                reply = evt["content"]
    except Exception as e:
        reply = _friendly_fatal(e)
    ordered = sorted(steps.values(), key=lambda s: s["index"])
    return {
        "reply": reply,
        "plan": plan,
        "steps": ordered,
        "tool_calls": [
            {"connector_id": s["connector_id"], "tool_name": s["tool"], "arguments": s["args"],
             "success": s["status"] == "done"}
            for s in ordered if s["status"] in ("done", "failed") and s["tool"] != "connect"
        ],
    }


async def retry_step(user_id: str, connector_id: str, tool: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """Re-run one tool call from the timeline's Retry button and return the new step payload."""
    cfg = get_connector(connector_id)
    if not cfg:
        raise ValueError("Unknown connector")
    conn = await mcp_connections_col.find_one({"user_id": user_id, "connector_id": connector_id})
    if not conn or conn.get("enabled") is False:
        raise ValueError(f"{cfg.display_name} isn't connected or is turned off")
    async with ConnectorSessionPool(user_id) as pool:
        start = time.monotonic()
        try:
            await asyncio.wait_for(pool.connect(connector_id), timeout=30)
        except Exception as e:
            ms = int((time.monotonic() - start) * 1000)
            return _finish_step("retry", 0, connector_id, tool, args, {"error": str(e) or type(e).__name__}, ms)
        result, ms = await _run_tool(user_id, pool, connector_id, tool, args)
    return _finish_step("retry", 0, connector_id, tool, args, result, ms)
