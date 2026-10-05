"""A small, self-hosted MCP server wrapping a few Slack Web API methods.

Spawned as a stdio subprocess per prompt by services/mcp/client_host.py, with
the user's decrypted bot token injected via the SLACK_BOT_TOKEN env var
(never a CLI argument). Written in-house rather than depending on a
third-party npm MCP package, matching the reasoning in services/mcp/registry.py.

Slack's Web API always returns HTTP 200; success/failure is the `ok` field
in the JSON body, so every call here checks that instead of the status code.
"""
import os

import httpx
from mcp.server.fastmcp import FastMCP

BOT_TOKEN_ENV = "SLACK_BOT_TOKEN"
SLACK_API = "https://slack.com/api"

mcp = FastMCP("slack")


def _headers() -> dict:
    return {"Authorization": f"Bearer {os.environ.get(BOT_TOKEN_ENV, '')}"}


@mcp.tool()
async def list_channels(limit: int = 50) -> str:
    """List public and private channels the bot can see in the workspace."""
    async with httpx.AsyncClient(timeout=15) as http:
        res = await http.get(
            f"{SLACK_API}/conversations.list",
            headers=_headers(),
            params={"types": "public_channel,private_channel", "limit": max(1, min(limit, 200))},
        )
    data = res.json()
    if not data.get("ok"):
        return f"Error listing channels: {data.get('error')}"
    lines = [f"- #{c['name']} id={c['id']}" for c in data.get("channels", [])]
    return "\n".join(lines) if lines else "No channels found."


@mcp.tool()
async def post_message(channel: str, text: str) -> str:
    """Post a message to a Slack channel. `channel` is a channel id or name (e.g. "#general")."""
    async with httpx.AsyncClient(timeout=15) as http:
        res = await http.post(
            f"{SLACK_API}/chat.postMessage",
            headers=_headers(),
            json={"channel": channel, "text": text},
        )
    data = res.json()
    if not data.get("ok"):
        return f"Error posting message: {data.get('error')}"
    return f"Posted to {data.get('channel')} at ts={data.get('ts')}"


@mcp.tool()
async def read_messages(channel: str, limit: int = 20) -> str:
    """Read the most recent messages in a Slack channel by its id."""
    async with httpx.AsyncClient(timeout=15) as http:
        res = await http.get(
            f"{SLACK_API}/conversations.history",
            headers=_headers(),
            params={"channel": channel, "limit": max(1, min(limit, 100))},
        )
    data = res.json()
    if not data.get("ok"):
        return f"Error reading messages: {data.get('error')}"
    lines = [f"[{m.get('ts')}] {m.get('user', 'unknown')}: {m.get('text', '')}" for m in data.get("messages", [])]
    return "\n".join(lines) if lines else "No messages found."


if __name__ == "__main__":
    mcp.run()
