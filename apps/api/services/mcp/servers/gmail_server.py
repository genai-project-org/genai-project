"""A small, self-hosted MCP server wrapping the Gmail REST API.

Spawned as a stdio subprocess per prompt by services/mcp/client_host.py, with
the user's decrypted access token injected via the GMAIL_ACCESS_TOKEN env var
(never a CLI argument). Mirrors google_calendar_server.py's shape — same
Google OAuth app, same bearer-token-over-REST pattern, different API.
"""
import base64
import os
from email.mime.text import MIMEText

import httpx
from mcp.server.fastmcp import FastMCP

ACCESS_TOKEN_ENV = "GMAIL_ACCESS_TOKEN"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"

mcp = FastMCP("gmail")


def _headers() -> dict:
    return {"Authorization": f"Bearer {os.environ.get(ACCESS_TOKEN_ENV, '')}"}


@mcp.tool()
async def list_messages(query: str = "", max_results: int = 10) -> str:
    """List the user's recent Gmail messages, optionally filtered by a Gmail search query (e.g. "is:unread", "from:someone@example.com")."""
    params = {"maxResults": max(1, min(max_results, 50))}
    if query:
        params["q"] = query
    async with httpx.AsyncClient(timeout=15) as http:
        res = await http.get(f"{GMAIL_API}/messages", headers=_headers(), params=params)
    if res.status_code != 200:
        return f"Error listing messages ({res.status_code}): {res.text[:300]}"
    ids = [m["id"] for m in res.json().get("messages", [])]
    if not ids:
        return "No messages found."
    lines = []
    async with httpx.AsyncClient(timeout=15) as http:
        for mid in ids:
            r = await http.get(f"{GMAIL_API}/messages/{mid}", headers=_headers(), params={"format": "metadata", "metadataHeaders": ["Subject", "From"]})
            if r.status_code != 200:
                continue
            msg = r.json()
            headers_list = msg.get("payload", {}).get("headers", [])
            subject = next((h["value"] for h in headers_list if h["name"] == "Subject"), "(no subject)")
            sender = next((h["value"] for h in headers_list if h["name"] == "From"), "unknown")
            lines.append(f"- [{mid}] from {sender}: {subject} — {msg.get('snippet', '')[:100]}")
    return "\n".join(lines) if lines else "No messages found."


@mcp.tool()
async def read_message(message_id: str) -> str:
    """Read the full subject, sender, and plain-text body of one Gmail message by its id (from list_messages)."""
    async with httpx.AsyncClient(timeout=15) as http:
        res = await http.get(f"{GMAIL_API}/messages/{message_id}", headers=_headers(), params={"format": "full"})
    if res.status_code != 200:
        return f"Error reading message ({res.status_code}): {res.text[:300]}"
    msg = res.json()
    headers_list = msg.get("payload", {}).get("headers", [])
    subject = next((h["value"] for h in headers_list if h["name"] == "Subject"), "(no subject)")
    sender = next((h["value"] for h in headers_list if h["name"] == "From"), "unknown")

    def _extract_text(payload: dict) -> str:
        stack = [payload]
        while stack:
            part = stack.pop()
            body_data = (part.get("body") or {}).get("data")
            if part.get("mimeType") == "text/plain" and body_data:
                padded = body_data + "=" * (-len(body_data) % 4)
                return base64.urlsafe_b64decode(padded).decode("utf-8", errors="ignore")
            stack.extend(part.get("parts") or [])
        return msg.get("snippet", "")

    body = _extract_text(msg.get("payload", {}))
    return f"From: {sender}\nSubject: {subject}\n\n{body[:3000]}"


@mcp.tool()
async def send_message(to: str, subject: str, body: str) -> str:
    """Send a plain-text email from the user's Gmail account."""
    mime = MIMEText(body)
    mime["to"] = to
    mime["subject"] = subject
    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode()
    async with httpx.AsyncClient(timeout=15) as http:
        res = await http.post(f"{GMAIL_API}/messages/send", headers=_headers(), json={"raw": raw})
    if res.status_code not in (200, 202):
        return f"Error sending message ({res.status_code}): {res.text[:300]}"
    return f"Sent to {to}: id={res.json().get('id')}"


if __name__ == "__main__":
    mcp.run()
