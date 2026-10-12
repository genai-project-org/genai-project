"""Shared HTTP helper for the in-house stdio MCP tool servers.

Raising (instead of returning an "Error ..." string) makes FastMCP flag the
tool result as isError, which the orchestrator turns into a failed step with a
friendly message — the raw text stays available in the step's details.
"""
from typing import Any, Optional

import httpx


async def request(
    method: str, url: str, *, service: str, headers: Optional[dict] = None,
    params: Optional[dict] = None, json: Any = None, data: Any = None,
) -> Any:
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            res = await http.request(method, url, headers=headers, params=params, json=json, data=data)
    except httpx.HTTPError as e:
        raise RuntimeError(f"{service} could not be reached (timeout/network): {type(e).__name__}") from e
    if res.status_code >= 400:
        raise RuntimeError(f"{service} returned HTTP {res.status_code}: {res.text[:300]}")
    if not res.content:
        return {}
    try:
        return res.json()
    except ValueError:
        return res.text


def clip(text: Any, n: int = 200) -> str:
    s = "" if text is None else str(text).replace("\n", " ").strip()
    return s if len(s) <= n else s[: n - 1] + "…"
