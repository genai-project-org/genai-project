"""Gmail Connect — reads LinkedIn job-alert emails via the Gmail API for Career Pipeline.

This is a SEPARATE consent flow from the app's login OAuth (routers/auth_routes.py's
`/auth/google`): that flow only ever requests profile/email and discards Google's
tokens after reading userinfo once. This one requests the `gmail.readonly` scope with
`access_type=offline&prompt=consent` (built client-side by the Pipeline tab) so we get
a refresh_token worth storing and reusing across scans. Talks to Google via raw httpx
calls, same style as auth_routes.py, rather than the googleapiclient SDK.
"""
import os
import re
import base64
import logging
from datetime import timedelta
from typing import Any, Dict, List, Optional
import httpx
from bs4 import BeautifulSoup
from db import db, now_iso, now_utc

logger = logging.getLogger(__name__)

GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GMAIL_API = "https://gmail.googleapis.com/gmail/v1/users/me"
JOB_ALERT_QUERY = "from:jobalerts-noreply@linkedin.com newer_than:14d"
MAX_MESSAGES = int(os.environ.get("GMAIL_SCAN_MAX_MESSAGES", "20"))

gmail_connections_col = db["gmail_connections"]


async def exchange_code(user_id: str, code: str, redirect_uri: str) -> Dict[str, Any]:
    """Exchange a one-time Gmail-consent auth code for tokens and store the connection."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        raise ValueError("Google OAuth is not configured on this server")
    async with httpx.AsyncClient(timeout=15) as http:
        token_res = await http.post(TOKEN_URL, data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
        if token_res.status_code != 200:
            logger.error(f"Gmail token exchange failed: {token_res.text}")
            raise ValueError("Gmail authorization failed — try connecting again")
        tokens = token_res.json()
        access_token = tokens.get("access_token")
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            # Google only issues a refresh_token on first consent (or when the
            # authorize URL forces prompt=consent, which the frontend always does) —
            # this should not happen in practice, but fail loudly rather than store
            # a connection that will silently stop working once the access token expires.
            raise ValueError("Google did not grant offline access — reconnect and approve access again")
        expires_in = int(tokens.get("expires_in", 3600))

        info_res = await http.get(USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"})
        email = info_res.json().get("email") if info_res.status_code == 200 else None

    expiry = (now_utc() + timedelta(seconds=expires_in)).isoformat()
    await gmail_connections_col.update_one(
        {"user_id": user_id},
        {"$set": {
            "user_id": user_id,
            "email": email,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_expiry": expiry,
            "connected_at": now_iso(),
        }},
        upsert=True,
    )
    return {"connected": True, "email": email}


async def get_status(user_id: str) -> Dict[str, Any]:
    conn = await gmail_connections_col.find_one({"user_id": user_id})
    if not conn:
        return {"connected": False, "email": None}
    return {"connected": True, "email": conn.get("email")}


async def disconnect(user_id: str) -> None:
    await gmail_connections_col.delete_one({"user_id": user_id})


async def _get_valid_access_token(user_id: str) -> Optional[str]:
    conn = await gmail_connections_col.find_one({"user_id": user_id})
    if not conn:
        return None

    expiry = conn.get("token_expiry")
    try:
        from datetime import datetime
        expired = not expiry or now_utc() >= datetime.fromisoformat(expiry)
    except Exception:
        expired = True
    if not expired:
        return conn["access_token"]

    async with httpx.AsyncClient(timeout=15) as http:
        res = await http.post(TOKEN_URL, data={
            "refresh_token": conn["refresh_token"],
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "grant_type": "refresh_token",
        })
    if res.status_code != 200:
        logger.warning(f"Gmail token refresh failed for user {user_id}: {res.text}")
        return None
    tokens = res.json()
    access_token = tokens["access_token"]
    new_expiry = (now_utc() + timedelta(seconds=int(tokens.get("expires_in", 3600)))).isoformat()
    # Google rarely re-issues a refresh_token on a plain refresh — never
    # overwrite the one we already have with a missing value.
    await gmail_connections_col.update_one(
        {"user_id": user_id},
        {"$set": {"access_token": access_token, "token_expiry": new_expiry}},
    )
    return access_token


def _b64url_decode(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded)


def _extract_html_body(payload: Dict[str, Any]) -> str:
    """Depth-first walk of a Gmail message payload for the first text/html part,
    falling back to text/plain (BeautifulSoup parses plain text fine too)."""
    stack = [payload]
    plain_fallback = None
    while stack:
        part = stack.pop()
        mime = part.get("mimeType", "")
        body_data = (part.get("body") or {}).get("data")
        if mime == "text/html" and body_data:
            return _b64url_decode(body_data).decode("utf-8", errors="ignore")
        if mime == "text/plain" and body_data and plain_fallback is None:
            plain_fallback = _b64url_decode(body_data).decode("utf-8", errors="ignore")
        stack.extend(part.get("parts") or [])
    return plain_fallback or ""


def _header(headers: Optional[List[Dict[str, str]]], name: str) -> str:
    for h in headers or []:
        if h.get("name", "").lower() == name.lower():
            return h.get("value", "")
    return ""


def parse_job_alert_email(html: str, subject: str = "", snippet: str = "") -> List[Dict[str, Any]]:
    """Best-effort extraction of job postings from a LinkedIn job-alert email.

    LinkedIn's marketing-email markup isn't documented and can change without
    notice, so this tries an anchor-based strategy and degrades to a single
    subject/snippet record rather than dropping the email entirely.
    """
    jobs: List[Dict[str, Any]] = []
    if html:
        soup = BeautifulSoup(html, "html.parser")
        seen_urls = set()
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "linkedin.com/jobs/view/" not in href and "/comm/jobs/view/" not in href:
                continue
            title = a.get_text(strip=True)
            clean_url = href.split("?")[0]
            if not title or clean_url in seen_urls:
                continue
            seen_urls.add(clean_url)
            # Company/location usually sit in a nearby sibling or parent block —
            # take the parent container's other text lines as a best guess.
            company = None
            location = None
            container = a.find_parent(["td", "div", "table"])
            if container:
                text_lines = [t.strip() for t in container.stripped_strings if t.strip() and t.strip() != title]
                if text_lines:
                    company = text_lines[0][:120]
                if len(text_lines) > 1:
                    location = text_lines[1][:120]
            jobs.append({
                "title": title[:200],
                "company": company,
                "location": location,
                "job_url": clean_url,
            })
    if not jobs:
        # Degrade gracefully: still surface the email rather than silently drop it.
        link_match = re.search(r'https?://[^\s"\'<>]*linkedin\.com/[^\s"\'<>]*jobs[^\s"\'<>]*', html or "")
        jobs.append({
            "title": subject or "LinkedIn job alert",
            "company": None,
            "location": None,
            "job_url": link_match.group(0) if link_match else None,
            "snippet": snippet[:300],
        })
    return jobs


async def fetch_linkedin_alert_emails(user_id: str) -> List[Dict[str, Any]]:
    access_token = await _get_valid_access_token(user_id)
    if not access_token:
        raise ValueError("Gmail is not connected or the connection has expired — reconnect Gmail")

    headers = {"Authorization": f"Bearer {access_token}"}
    jobs: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=20) as http:
        list_res = await http.get(
            f"{GMAIL_API}/messages",
            headers=headers,
            params={"q": JOB_ALERT_QUERY, "maxResults": MAX_MESSAGES},
        )
        if list_res.status_code != 200:
            logger.error(f"Gmail list failed: {list_res.text}")
            raise ValueError("Could not read Gmail — try reconnecting")
        message_ids = [m["id"] for m in list_res.json().get("messages", [])]

        for mid in message_ids:
            msg_res = await http.get(f"{GMAIL_API}/messages/{mid}", headers=headers, params={"format": "full"})
            if msg_res.status_code != 200:
                continue
            msg = msg_res.json()
            payload = msg.get("payload", {})
            subject = _header(payload.get("headers"), "Subject")
            html = _extract_html_body(payload)
            for job in parse_job_alert_email(html, subject=subject, snippet=msg.get("snippet", "")):
                job["source_message_id"] = mid
                jobs.append(job)
    return jobs


def demo() -> None:
    """Offline self-check: python -m services.gmail_service"""
    sample_html = """
    <table><tr><td>
      <a href="https://www.linkedin.com/jobs/view/1234567890/?trk=alert">Senior Backend Engineer</a>
      <div>Zerodha</div>
      <div>Bengaluru, India</div>
    </td></tr></table>
    """
    jobs = parse_job_alert_email(sample_html)
    assert len(jobs) == 1, jobs
    assert jobs[0]["title"] == "Senior Backend Engineer", jobs[0]
    assert jobs[0]["company"] == "Zerodha", jobs[0]
    assert jobs[0]["job_url"] == "https://www.linkedin.com/jobs/view/1234567890/", jobs[0]

    # Unrecognized markup must still degrade to a usable record, not vanish.
    fallback = parse_job_alert_email("<p>no job links here, just text</p>", subject="5 new jobs for you")
    assert len(fallback) == 1 and fallback[0]["title"] == "5 new jobs for you", fallback

    empty = parse_job_alert_email("", subject="LinkedIn Job Alert")
    assert len(empty) == 1 and empty[0]["job_url"] is None, empty

    # Two distinct job links in one email must both survive, deduped by URL only.
    two_jobs_html = sample_html + '<a href="https://www.linkedin.com/jobs/view/999/">Data Analyst</a>'
    assert len(parse_job_alert_email(two_jobs_html)) == 2

    print("gmail_service demo OK")


if __name__ == "__main__":
    demo()
