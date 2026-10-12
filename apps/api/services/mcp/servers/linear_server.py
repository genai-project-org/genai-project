"""In-house MCP server over Linear's GraphQL API (OAuth access token in LINEAR_ACCESS_TOKEN; a legacy personal key in LINEAR_API_KEY also works)."""
import os
from typing import Optional

from mcp.server.fastmcp import FastMCP

from services.mcp.servers._common import request

mcp = FastMCP("linear")


async def _gql(query: str, variables: Optional[dict] = None) -> dict:
    oauth = os.environ.get("LINEAR_ACCESS_TOKEN", "")
    # OAuth tokens are sent as a Bearer token; personal API keys go in the header bare.
    auth = f"Bearer {oauth}" if oauth else os.environ.get("LINEAR_API_KEY", "")
    data = await request(
        "POST", "https://api.linear.app/graphql", service="Linear",
        headers={"Authorization": auth, "Content-Type": "application/json"},
        json={"query": query, "variables": variables or {}},
    )
    if isinstance(data, dict) and data.get("errors"):
        raise RuntimeError(f"Linear returned an error: {data['errors'][0].get('message')}")
    return data["data"]


@mcp.tool()
async def list_teams() -> str:
    """List Linear teams (needed to create issues)."""
    d = await _gql("{ teams { nodes { id key name } } }")
    return "\n".join(f"- {t['name']} key={t['key']} id={t['id']}" for t in d["teams"]["nodes"]) or "No teams."


@mcp.tool()
async def list_issues(limit: int = 15, query: str = "") -> str:
    """List recent Linear issues, optionally filtered by a text query on the title."""
    flt = {"title": {"containsIgnoreCase": query}} if query else {}
    d = await _gql(
        "query($n:Int,$f:IssueFilter){ issues(first:$n, filter:$f, orderBy:updatedAt){ nodes "
        "{ identifier title url state{name} assignee{name} } } }",
        {"n": max(1, min(limit, 50)), "f": flt},
    )
    lines = [f"- {i['identifier']} [{i['state']['name']}] {i['title']} "
             f"(assignee: {(i.get('assignee') or {}).get('name', 'unassigned')}) {i['url']}" for i in d["issues"]["nodes"]]
    return "\n".join(lines) or "No issues found."


@mcp.tool()
async def create_issue(team_id: str, title: str, description: str = "") -> str:
    """Create a Linear issue in a team (use list_teams to get team_id)."""
    d = await _gql(
        "mutation($i:IssueCreateInput!){ issueCreate(input:$i){ success issue{ identifier url } } }",
        {"i": {"teamId": team_id, "title": title, "description": description}},
    )
    issue = d["issueCreate"]["issue"]
    return f"Created {issue['identifier']}: {issue['url']}"


@mcp.tool()
async def add_comment(issue_id: str, body: str) -> str:
    """Comment on a Linear issue (issue_id is the issue UUID)."""
    await _gql("mutation($i:CommentCreateInput!){ commentCreate(input:$i){ success } }",
               {"i": {"issueId": issue_id, "body": body}})
    return "Comment added."


if __name__ == "__main__":
    mcp.run()
