"""In-house MCP server over the Notion REST API (public-integration OAuth token
in NOTION_ACCESS_TOKEN). Notion only exposes pages the user shared with the
integration during the consent screen."""
import os

from mcp.server.fastmcp import FastMCP

from services.mcp.servers._common import request

API = "https://api.notion.com/v1"
mcp = FastMCP("notion")


def _h() -> dict:
    return {
        "Authorization": f"Bearer {os.environ.get('NOTION_ACCESS_TOKEN', '')}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }


def _title(obj: dict) -> str:
    if obj.get("object") == "database":
        return "".join(t.get("plain_text", "") for t in obj.get("title", [])) or "(untitled database)"
    for prop in obj.get("properties", {}).values():
        if prop.get("type") == "title":
            return "".join(t.get("plain_text", "") for t in prop.get("title", [])) or "(untitled)"
    return "(untitled)"


def _paragraphs(content: str) -> list:
    return [{
        "object": "block", "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": chunk[:1900]}}]},
    } for chunk in content.split("\n") if chunk.strip()][:90]


@mcp.tool()
async def search(query: str = "", limit: int = 10) -> str:
    """Search pages and databases the user shared with the integration."""
    data = await request("POST", f"{API}/search", service="Notion", headers=_h(),
                         json={"query": query, "page_size": max(1, min(limit, 25))})
    lines = [f"- [{r['object']}] {_title(r)} id={r['id']} ({r.get('url', '')})" for r in data.get("results", [])]
    return "\n".join(lines) or "Nothing found (only pages shared with the integration are visible)."


@mcp.tool()
async def read_page(page_id: str) -> str:
    """Read the text content of a Notion page by id."""
    page = await request("GET", f"{API}/pages/{page_id}", service="Notion", headers=_h())
    blocks = await request("GET", f"{API}/blocks/{page_id}/children", service="Notion", headers=_h(),
                           params={"page_size": 100})
    out = [f"# {_title(page)}"]
    for b in blocks.get("results", []):
        rich = b.get(b["type"], {}).get("rich_text", [])
        text = "".join(t.get("plain_text", "") for t in rich)
        if text:
            out.append(text)
    return "\n".join(out)


@mcp.tool()
async def create_page(parent_page_id: str, title: str, content: str = "") -> str:
    """Create a new page under an existing page (parent_page_id), with optional plain-text content."""
    page = await request("POST", f"{API}/pages", service="Notion", headers=_h(), json={
        "parent": {"page_id": parent_page_id},
        "properties": {"title": {"title": [{"type": "text", "text": {"content": title}}]}},
        "children": _paragraphs(content),
    })
    return f"Created page '{title}': {page.get('url')}"


@mcp.tool()
async def append_to_page(page_id: str, content: str) -> str:
    """Append plain-text paragraphs to an existing page."""
    children = _paragraphs(content)
    await request("PATCH", f"{API}/blocks/{page_id}/children", service="Notion", headers=_h(),
                  json={"children": children})
    return f"Appended {len(children)} paragraph(s) to the page."


if __name__ == "__main__":
    mcp.run()
