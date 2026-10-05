"""A small, self-hosted MCP server wrapping the Google Calendar REST API.

Spawned as a stdio subprocess per prompt by services/mcp/client_host.py, with
the user's decrypted access token injected via the GOOGLE_CALENDAR_ACCESS_TOKEN
env var (never a CLI argument). Written in-house rather than depending on a
third-party npm MCP package, matching the reasoning in services/mcp/registry.py.
"""
import os

import httpx
from mcp.server.fastmcp import FastMCP

ACCESS_TOKEN_ENV = "GOOGLE_CALENDAR_ACCESS_TOKEN"
CALENDAR_API = "https://www.googleapis.com/calendar/v3/calendars/primary/events"

mcp = FastMCP("google-calendar")


def _headers() -> dict:
    token = os.environ.get(ACCESS_TOKEN_ENV, "")
    return {"Authorization": f"Bearer {token}"}


@mcp.tool()
async def list_events(time_min: str = "", time_max: str = "", max_results: int = 10) -> str:
    """List upcoming events on the user's primary Google Calendar.

    time_min/time_max are optional RFC3339 timestamps (e.g. "2026-09-22T00:00:00Z");
    omit either to leave that bound open.
    """
    params = {"singleEvents": "true", "orderBy": "startTime", "maxResults": max(1, min(max_results, 50))}
    if time_min:
        params["timeMin"] = time_min
    if time_max:
        params["timeMax"] = time_max
    async with httpx.AsyncClient(timeout=15) as http:
        res = await http.get(CALENDAR_API, headers=_headers(), params=params)
    if res.status_code != 200:
        return f"Error listing events ({res.status_code}): {res.text[:300]}"
    items = res.json().get("items", [])
    if not items:
        return "No events found in that range."
    lines = []
    for ev in items:
        start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date")
        lines.append(f"- {ev.get('summary', '(no title)')} [{start}] id={ev.get('id')}")
    return "\n".join(lines)


@mcp.tool()
async def create_event(summary: str, start_time: str, end_time: str, time_zone: str = "UTC", description: str = "") -> str:
    """Create an event on the user's primary Google Calendar.

    start_time/end_time are RFC3339 timestamps (e.g. "2026-09-23T15:00:00").
    """
    body = {
        "summary": summary,
        "description": description,
        "start": {"dateTime": start_time, "timeZone": time_zone},
        "end": {"dateTime": end_time, "timeZone": time_zone},
    }
    async with httpx.AsyncClient(timeout=15) as http:
        res = await http.post(CALENDAR_API, headers=_headers(), json=body)
    if res.status_code not in (200, 201):
        return f"Error creating event ({res.status_code}): {res.text[:300]}"
    ev = res.json()
    return f"Created '{ev.get('summary')}' id={ev.get('id')} link={ev.get('htmlLink')}"


@mcp.tool()
async def delete_event(event_id: str) -> str:
    """Delete an event from the user's primary Google Calendar by its id (from list_events)."""
    async with httpx.AsyncClient(timeout=15) as http:
        res = await http.delete(f"{CALENDAR_API}/{event_id}", headers=_headers())
    if res.status_code not in (200, 204):
        return f"Error deleting event ({res.status_code}): {res.text[:300]}"
    return f"Deleted event {event_id}"


if __name__ == "__main__":
    mcp.run()
