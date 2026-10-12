"""In-house MCP server over the Asana REST API (OAuth or personal access token in ASANA_ACCESS_TOKEN)."""
import os

from mcp.server.fastmcp import FastMCP

from services.mcp.servers._common import request

API = "https://app.asana.com/api/1.0"
mcp = FastMCP("asana")


def _h() -> dict:
    return {"Authorization": f"Bearer {os.environ.get('ASANA_ACCESS_TOKEN', '')}"}


@mcp.tool()
async def list_workspaces() -> str:
    """List Asana workspaces the user belongs to."""
    d = await request("GET", f"{API}/workspaces", service="Asana", headers=_h())
    return "\n".join(f"- {w['name']} gid={w['gid']}" for w in d["data"]) or "No workspaces."


@mcp.tool()
async def list_projects(workspace_gid: str, limit: int = 25) -> str:
    """List projects in a workspace."""
    d = await request("GET", f"{API}/projects", service="Asana", headers=_h(),
                      params={"workspace": workspace_gid, "limit": max(1, min(limit, 100)), "opt_fields": "name"})
    return "\n".join(f"- {p['name']} gid={p['gid']}" for p in d["data"]) or "No projects."


@mcp.tool()
async def list_tasks(project_gid: str, limit: int = 25) -> str:
    """List tasks in a project."""
    d = await request("GET", f"{API}/tasks", service="Asana", headers=_h(),
                      params={"project": project_gid, "limit": max(1, min(limit, 100)),
                              "opt_fields": "name,completed,due_on"})
    lines = [f"- [{'x' if t.get('completed') else ' '}] {t['name']} gid={t['gid']} due={t.get('due_on') or 'none'}" for t in d["data"]]
    return "\n".join(lines) or "No tasks."


@mcp.tool()
async def create_task(workspace_gid: str, name: str, notes: str = "", project_gid: str = "", due_on: str = "") -> str:
    """Create a task (optionally in a project; due_on is YYYY-MM-DD)."""
    body = {"workspace": workspace_gid, "name": name, "notes": notes}
    if project_gid:
        body["projects"] = [project_gid]
    if due_on:
        body["due_on"] = due_on
    d = await request("POST", f"{API}/tasks", service="Asana", headers=_h(), json={"data": body})
    return f"Created task '{name}': {d['data'].get('permalink_url', d['data']['gid'])}"


@mcp.tool()
async def complete_task(task_gid: str) -> str:
    """Mark a task complete."""
    await request("PUT", f"{API}/tasks/{task_gid}", service="Asana", headers=_h(), json={"data": {"completed": True}})
    return "Task marked complete."


if __name__ == "__main__":
    mcp.run()
