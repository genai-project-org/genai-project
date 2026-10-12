"""In-house MCP server over the Trello REST API (TRELLO_API_KEY operator key + per-user TRELLO_TOKEN)."""
import os
from typing import Optional

from mcp.server.fastmcp import FastMCP

from services.mcp.servers._common import request

API = "https://api.trello.com/1"
mcp = FastMCP("trello")


def _auth(extra: Optional[dict] = None) -> dict:
    return {"key": os.environ.get("TRELLO_API_KEY", ""), "token": os.environ.get("TRELLO_TOKEN", ""), **(extra or {})}


@mcp.tool()
async def list_boards() -> str:
    """List the user's open Trello boards."""
    d = await request("GET", f"{API}/members/me/boards", service="Trello", params=_auth({"filter": "open", "fields": "name,url"}))
    return "\n".join(f"- {b['name']} id={b['id']}" for b in d) or "No boards."


@mcp.tool()
async def list_lists(board_id: str) -> str:
    """List the lists (columns) on a board."""
    d = await request("GET", f"{API}/boards/{board_id}/lists", service="Trello", params=_auth({"fields": "name"}))
    return "\n".join(f"- {x['name']} id={x['id']}" for x in d) or "No lists."


@mcp.tool()
async def list_cards(list_id: str) -> str:
    """List cards in a list."""
    d = await request("GET", f"{API}/lists/{list_id}/cards", service="Trello", params=_auth({"fields": "name,url,due"}))
    return "\n".join(f"- {c['name']} id={c['id']} {c['url']}" for c in d) or "No cards."


@mcp.tool()
async def create_card(list_id: str, name: str, desc: str = "") -> str:
    """Create a card in a list."""
    c = await request("POST", f"{API}/cards", service="Trello", params=_auth({"idList": list_id, "name": name, "desc": desc}))
    return f"Created card '{name}': {c.get('url')}"


if __name__ == "__main__":
    mcp.run()
