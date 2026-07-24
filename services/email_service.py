"""Email service using Resend with dev-mode fallback."""
import os
import asyncio
import logging
from typing import Optional
import resend

logger = logging.getLogger(__name__)

RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "onboarding@resend.dev")
SENDER_NAME = os.environ.get("SENDER_NAME", "IEMA.ai")
APP_URL = os.environ.get("APP_URL", "http://localhost:3000")

if RESEND_API_KEY:
    resend.api_key = RESEND_API_KEY

_dev_outbox = []  # In-memory dev-mode outbox for testing


def is_configured() -> bool:
    return bool(RESEND_API_KEY)


async def send_email(to: str, subject: str, html: str) -> dict:
    """Send an email. Falls back to dev-mode log if RESEND_API_KEY not set."""
    if not RESEND_API_KEY:
        entry = {"to": to, "subject": subject, "html": html}
        _dev_outbox.append(entry)
        logger.warning(f"[DEV EMAIL] To: {to} | Subject: {subject}")
        logger.info(f"[DEV EMAIL BODY]\n{html[:500]}")
        return {"status": "dev_mode", "queued": True}
    params = {
        "from": f"{SENDER_NAME} <{SENDER_EMAIL}>",
        "to": [to],
        "subject": subject,
        "html": html,
    }
    try:
        result = await asyncio.to_thread(resend.Emails.send, params)
        return {"status": "sent", "id": result.get("id")}
    except Exception as e:
        logger.exception(f"Resend email error: {e}")
        return {"status": "error", "error": str(e)}


def get_dev_outbox(email: Optional[str] = None):
    if email:
        return [e for e in _dev_outbox if e["to"] == email]
    return list(_dev_outbox)


# ================ Templates ================
def _wrap(title: str, body_html: str) -> str:
    return f"""<!doctype html><html><body style="margin:0;background:#0a0a0f;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#e5e5e5;padding:40px 20px">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:520px;margin:0 auto;background:#12121a;border:1px solid #26262e;border-radius:12px;overflow:hidden">
  <tr><td style="padding:24px 28px;border-bottom:1px solid #26262e">
    <div style="font-size:18px;font-weight:600;letter-spacing:-0.02em">
      <span style="color:#3b82f6">■</span> IEMA<span style="color:#3b82f6">.</span>ai
    </div>
  </td></tr>
  <tr><td style="padding:32px 28px">
    <h1 style="margin:0 0 12px;font-size:22px;font-weight:600;color:#fff;letter-spacing:-0.02em">{title}</h1>
    {body_html}
  </td></tr>
  <tr><td style="padding:20px 28px;border-top:1px solid #26262e;font-size:12px;color:#71717a">
    You are receiving this because you have an account at IEMA.ai. If this wasn't you, ignore this email.
    <div style="margin-top:8px">© 2026 IEMA.ai — Built with care.</div>
  </td></tr>
</table>
</body></html>"""


def verify_email_template(name: str, code: str) -> str:
    body = f"""<p style="color:#a1a1aa;line-height:1.6">Hi {name},</p>
<p style="color:#a1a1aa;line-height:1.6">Use the code below to verify your email address:</p>
<div style="text-align:center;margin:24px 0">
  <div style="display:inline-block;background:#1a1a24;border:1px solid #3b82f6;border-radius:8px;padding:16px 32px;font-family:'JetBrains Mono',monospace;font-size:32px;font-weight:600;letter-spacing:8px;color:#3b82f6">{code}</div>
</div>
<p style="color:#71717a;font-size:13px;line-height:1.6">This code expires in 15 minutes.</p>"""
    return _wrap("Verify your email", body)


def reset_password_template(name: str, reset_url: str) -> str:
    body = f"""<p style="color:#a1a1aa;line-height:1.6">Hi {name},</p>
<p style="color:#a1a1aa;line-height:1.6">We received a request to reset your password. Click the button below to choose a new one:</p>
<div style="text-align:center;margin:24px 0">
  <a href="{reset_url}" style="display:inline-block;background:#3b82f6;color:#fff;text-decoration:none;padding:12px 28px;border-radius:8px;font-weight:500">Reset Password</a>
</div>
<p style="color:#71717a;font-size:13px;line-height:1.6">Or copy this link: <br><span style="color:#3b82f6;word-break:break-all">{reset_url}</span></p>
<p style="color:#71717a;font-size:13px;line-height:1.6">This link expires in 1 hour. If you didn't request this, ignore this email — your password stays the same.</p>"""
    return _wrap("Reset your password", body)


def reset_otp_template(name: str, otp: str) -> str:
    """One-time reset code (6 digits). Second factor before we let the user
    set a new password. Deliberately does NOT include a clickable reset link
    — the code must be re-entered on the same device that initiated the
    request, blocking email-based takeover."""
    body = f"""<p style="color:#a1a1aa;line-height:1.6">Hi {name},</p>
<p style="color:#a1a1aa;line-height:1.6">Use the code below to reset your IEMA.ai password. Do NOT share this code with anyone.</p>
<div style="text-align:center;margin:28px 0">
  <div style="display:inline-block;background:#0a0a0f;border:1px solid #27272a;border-radius:12px;padding:20px 36px;font-family:'SFMono-Regular',Consolas,monospace;font-size:38px;letter-spacing:12px;color:#3b82f6;font-weight:600">{otp}</div>
</div>
<p style="color:#71717a;font-size:13px;line-height:1.6">This code expires in <b>10 minutes</b> and can only be used once. If you didn't request a reset, ignore this email — your password stays the same.</p>"""
    return _wrap("Your IEMA.ai reset code", body)



def welcome_template(name: str) -> str:
    body = f"""<p style="color:#a1a1aa;line-height:1.6">Hi {name},</p>
<p style="color:#a1a1aa;line-height:1.6">Welcome to IEMA.ai — one workspace to think, learn, build and grow with AI. You've been credited with <b style="color:#3b82f6">100 welcome credits</b> to start, plus <b>20 free credits every day</b>.</p>
<div style="margin:24px 0"><a href="{APP_URL}/chat" style="display:inline-block;background:#3b82f6;color:#fff;text-decoration:none;padding:12px 28px;border-radius:8px;font-weight:500">Open workspace</a></div>
<p style="color:#71717a;font-size:13px;line-height:1.6">Explore Career Intelligence, Mock Interviews, Resume Intelligence and more — all in one place.</p>"""
    return _wrap("Welcome to IEMA.ai", body)
