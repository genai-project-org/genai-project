"""In-house MCP server over the GitHub REST API.

Spawned per prompt by services/mcp/client_host.py with the user's OAuth token
in GITHUB_ACCESS_TOKEN (env, never argv).
"""
import os

from mcp.server.fastmcp import FastMCP

from services.mcp.servers._common import clip, request

API = "https://api.github.com"
mcp = FastMCP("github")


def _h() -> dict:
    return {
        "Authorization": f"Bearer {os.environ.get('GITHUB_ACCESS_TOKEN', '')}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "iema-workspace",
    }


@mcp.tool()
async def list_repos(limit: int = 20) -> str:
    """List the authenticated user's most recently updated GitHub repositories."""
    data = await request("GET", f"{API}/user/repos", service="GitHub", headers=_h(),
                         params={"sort": "updated", "per_page": max(1, min(limit, 50))})
    lines = [f"- {r['full_name']} ({'private' if r['private'] else 'public'}) — {clip(r.get('description'), 80)}" for r in data]
    return "\n".join(lines) or "No repositories found."


@mcp.tool()
async def list_issues(repo: str, state: str = "open", limit: int = 15) -> str:
    """List issues in a repo ("owner/name"). state: open, closed or all."""
    data = await request("GET", f"{API}/repos/{repo}/issues", service="GitHub", headers=_h(),
                         params={"state": state, "per_page": max(1, min(limit, 50))})
    lines = [f"- #{i['number']} [{i['state']}] {i['title']} ({i['html_url']})" for i in data if "pull_request" not in i]
    return "\n".join(lines) or "No issues found."


@mcp.tool()
async def create_issue(repo: str, title: str, body: str = "") -> str:
    """Create an issue in a repo ("owner/name")."""
    i = await request("POST", f"{API}/repos/{repo}/issues", service="GitHub", headers=_h(),
                      json={"title": title, "body": body})
    return f"Created issue #{i['number']}: {i['html_url']}"


@mcp.tool()
async def list_pull_requests(repo: str, state: str = "open", limit: int = 15) -> str:
    """List pull requests in a repo ("owner/name")."""
    data = await request("GET", f"{API}/repos/{repo}/pulls", service="GitHub", headers=_h(),
                         params={"state": state, "per_page": max(1, min(limit, 50))})
    lines = [f"- #{p['number']} [{p['state']}] {p['title']} by {p['user']['login']} ({p['html_url']})" for p in data]
    return "\n".join(lines) or "No pull requests found."


@mcp.tool()
async def search_code(query: str, limit: int = 10) -> str:
    """Search code across GitHub using a query such as "TODO repo:owner/name"."""
    data = await request("GET", f"{API}/search/code", service="GitHub", headers=_h(),
                         params={"q": query, "per_page": max(1, min(limit, 30))})
    lines = [f"- {i['repository']['full_name']}:{i['path']} ({i['html_url']})" for i in data.get("items", [])]
    return "\n".join(lines) or "No matches."


@mcp.tool()
async def add_issue_comment(repo: str, issue_number: int, body: str) -> str:
    """Comment on an issue or pull request."""
    c = await request("POST", f"{API}/repos/{repo}/issues/{issue_number}/comments", service="GitHub",
                      headers=_h(), json={"body": body})
    return f"Comment added: {c['html_url']}"


if __name__ == "__main__":
    mcp.run()
