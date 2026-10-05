"""The MCP client host — connects to a user's authorized MCP servers.

Per-request scope: a ConnectorSessionPool is opened once per prompt
(orchestrator_service.py), holds one live MCP ClientSession per connected
connector for the duration of that prompt's tool-use loop, and is torn down
afterward. No cross-request pooling in phase 1 — simplest correct thing;
revisit if per-prompt subprocess/connection spin-up becomes a latency issue.
"""
import logging
import os
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Tuple

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from services.mcp import api_key_service, oauth_service
from services.mcp.registry import API_ROOT_DIR, ConnectorConfig, get_connector

logger = logging.getLogger(__name__)

# Namespacing separator between connector id and the tool's own name, e.g.
# "google_calendar__create_event" — lets the orchestrator route a tool_use
# block back to the right connector's session without ambiguity.
NAMESPACE_SEP = "__"


def _namespaced(connector_id: str, tool_name: str) -> str:
    return f"{connector_id}{NAMESPACE_SEP}{tool_name}"


def split_namespaced(full_name: str) -> Tuple[str, str]:
    connector_id, _, tool_name = full_name.partition(NAMESPACE_SEP)
    return connector_id, tool_name


def _mcp_content_to_text(result) -> str:
    parts = []
    for block in getattr(result, "content", []) or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
        else:
            parts.append(str(block))
    return "\n".join(parts) if parts else ""


class ConnectorSessionPool:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self._stack = AsyncExitStack()
        self._sessions: Dict[str, ClientSession] = {}

    async def __aenter__(self) -> "ConnectorSessionPool":
        await self._stack.__aenter__()
        return self

    async def __aexit__(self, *exc_info):
        await self._stack.__aexit__(*exc_info)

    async def connect(self, connector_id: str) -> None:
        """Open a live, initialized MCP session for one connected connector."""
        if connector_id in self._sessions:
            return
        cfg = get_connector(connector_id)
        if not cfg:
            raise ValueError(f"Unknown connector: {connector_id}")
        if cfg.mcp_status != "ready":
            raise ValueError(
                f"{cfg.display_name} isn't wired up for actions yet — its OAuth/API-key connection "
                f"works, but no tool server has been built for it. {cfg.mcp_notes}".strip()
            )

        if cfg.transport == "stdio":
            if cfg.auth_type == "api_key":
                creds = await api_key_service.get_credentials(self.user_id, connector_id)
                injected_env = {cfg.credential_env_map[field]: creds[field] for field in cfg.credential_fields}
            else:
                access_token = await oauth_service.get_valid_access_token(self.user_id, connector_id)
                injected_env = {cfg.token_env_var: access_token}
            read, write = await self._stack.enter_async_context(
                stdio_client(StdioServerParameters(
                    command=cfg.stdio_command,
                    args=cfg.stdio_args,
                    env={**os.environ, **injected_env},
                    cwd=str(API_ROOT_DIR),
                ))
            )
        elif cfg.transport == "http":
            # oauth2-only — see ConnectorConfig.http_url's docstring.
            access_token = await oauth_service.get_valid_access_token(self.user_id, connector_id)
            read, write, _ = await self._stack.enter_async_context(
                streamablehttp_client(cfg.http_url, headers={"Authorization": f"Bearer {access_token}"})
            )
        else:
            raise ValueError(f"Unknown transport for connector {connector_id}: {cfg.transport}")

        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._sessions[connector_id] = session

    async def list_tools_anthropic(self, connector_id: str) -> List[dict]:
        session = self._sessions[connector_id]
        result = await session.list_tools()
        return [
            {
                "name": _namespaced(connector_id, tool.name),
                "description": tool.description or "",
                "input_schema": tool.inputSchema,
            }
            for tool in result.tools
        ]

    async def call_tool(self, connector_id: str, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        session = self._sessions.get(connector_id)
        if not session:
            return {"error": f"{connector_id} is not connected in this session"}
        try:
            result = await session.call_tool(tool_name, arguments)
        except Exception as e:
            logger.exception(f"MCP tool call failed: {connector_id}.{tool_name}")
            return {"error": str(e)[:300]}
        text = _mcp_content_to_text(result)
        if getattr(result, "isError", False):
            return {"error": text or "Tool call failed"}
        return {"result": text}
