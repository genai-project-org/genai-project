"""Generic REST tool server — a safe fallback for connectors whose provider has
no hosted MCP server that accepts a third-party OAuth token.

Spawned per prompt by services/mcp/client_host.py. Configuration arrives via
env (never argv): REST_API_NAME, REST_BASE_URL, REST_ACCESS_TOKEN,
REST_ALLOWED_HOSTS (comma list, "*.example.com" wildcards ok),
REST_EXTRA_HEADERS (JSON), REST_RESOLVER ("atlassian" | "basecamp" | "").

The model gets api_get / api_post / api_put / api_patch / api_delete. The
bearer token is only ever sent to an allowed host over https, so a prompt
can't redirect it elsewhere. Tool names carry the HTTP verb so the
orchestrator's confirm-before-destructive rule (api_delete) applies.
"""
import json
import os
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx
from mcp.server.fastmcp import FastMCP


NAME = os.environ.get("REST_API_NAME", "API")
TOKEN = os.environ.get("REST_ACCESS_TOKEN", "")
ALLOWED = [h.strip().lower() for h in os.environ.get("REST_ALLOWED_HOSTS", "").split(",") if h.strip()]
EXTRA_HEADERS: Dict[str, str] = json.loads(os.environ.get("REST_EXTRA_HEADERS", "") or "{}")
MAX_CHARS = 6000

mcp = FastMCP(NAME.lower().replace(" ", "_"))
_base: Optional[str] = None


def host_allowed(host: str, allowed: list) -> bool:
    host = (host or "").lower()
    for pat in allowed:
        if pat.startswith("*."):
            if host.endswith(pat[1:]) and host != pat[2:]:
                return True
        elif host == pat:
            return True
    return False


def build_url(base: str, path: str, allowed: list) -> str:
    """Join a relative path to the base, or accept an absolute https URL on an allowed host."""
    path = (path or "").strip()
    if "://" in path:
        u = urlparse(path)
        if u.scheme != "https" or not host_allowed(u.hostname, allowed):
            raise ValueError(f"URL host not allowed for {NAME}")
        return path
    if path.startswith("//") or ".." in path.split("?")[0].split("/"):
        raise ValueError("Invalid path")
    url = base.rstrip("/") + "/" + path.lstrip("/")
    u = urlparse(url)
    if u.scheme != "https" or not host_allowed(u.hostname, allowed):
        raise ValueError(f"URL host not allowed for {NAME}")
    return url


async def _resolve_base() -> str:
    global _base
    if _base:
        return _base
    base = os.environ.get("REST_BASE_URL", "")
    resolver = os.environ.get("REST_RESOLVER", "")
    headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json", **EXTRA_HEADERS}
    if resolver == "atlassian":
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.get("https://api.atlassian.com/oauth/token/accessible-resources", headers=headers)
        if r.status_code >= 400 or not r.json():
            raise RuntimeError(f"{NAME} returned HTTP {r.status_code}: no accessible site for this account")
        base = base.replace("{cloudid}", r.json()[0]["id"])
    elif resolver == "basecamp":
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.get("https://launchpad.37signals.com/authorization.json", headers=headers)
        if r.status_code >= 400:
            raise RuntimeError(f"{NAME} returned HTTP {r.status_code}: {r.text[:200]}")
        accounts = [a for a in r.json().get("accounts", []) if a.get("product") in ("bc3", "bc4")] or r.json().get("accounts", [])
        if not accounts:
            raise RuntimeError(f"{NAME} found no accounts for this user")
        base = base.replace("{cloudid}", str(accounts[0]["id"]))
    _base = base
    return base


async def _call(method: str, path: str, query: Optional[Dict[str, Any]], body: Any) -> str:
    base = await _resolve_base()
    url = build_url(base, path, ALLOWED)
    headers = {"Authorization": f"Bearer {TOKEN}", "Accept": "application/json", **EXTRA_HEADERS}
    kwargs: Dict[str, Any] = {"params": query or None}
    if body not in (None, "", {}):
        kwargs["json"] = body
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as http:
            res = await http.request(method, url, headers=headers, **kwargs)
    except httpx.HTTPError as e:
        raise RuntimeError(f"{NAME} could not be reached (timeout/network): {type(e).__name__}") from e
    if res.status_code >= 400:
        raise RuntimeError(f"{NAME} returned HTTP {res.status_code}: {res.text[:400]}")
    if not res.content:
        return f"OK (HTTP {res.status_code}, empty body)"
    text = res.text
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + f"\n... [truncated {len(res.text) - MAX_CHARS} chars; narrow the query or page]"
    return text


@mcp.tool()
async def api_get(path: str, query: Optional[Dict[str, Any]] = None) -> str:
    """GET a read-only endpoint. `path` is relative to the API base (or a full https URL on an allowed host); `query` holds URL parameters."""
    return await _call("GET", path, query, None)


@mcp.tool()
async def api_post(path: str, body: Optional[Dict[str, Any]] = None, query: Optional[Dict[str, Any]] = None) -> str:
    """POST (create / RPC-style call / search) with an optional JSON body. Path rules as in api_get."""
    return await _call("POST", path, query, body)


@mcp.tool()
async def api_put(path: str, body: Optional[Dict[str, Any]] = None, query: Optional[Dict[str, Any]] = None) -> str:
    """PUT (replace/update) with an optional JSON body. Path rules as in api_get."""
    return await _call("PUT", path, query, body)


@mcp.tool()
async def api_patch(path: str, body: Optional[Dict[str, Any]] = None, query: Optional[Dict[str, Any]] = None) -> str:
    """PATCH (partial update) with an optional JSON body. Path rules as in api_get."""
    return await _call("PATCH", path, query, body)


@mcp.tool()
async def api_delete(path: str, query: Optional[Dict[str, Any]] = None) -> str:
    """DELETE a resource. Irreversible — the user confirms it first. Path rules as in api_get."""
    return await _call("DELETE", path, query, None)


if __name__ == "__main__":
    mcp.run()
