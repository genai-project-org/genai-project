"""
IEMA.ai v2 - Phase 2 backend integration tests.

Covers the additions on top of iteration 1:
- OAuth config endpoint (Google/Microsoft/Apple/Facebook)
- Microsoft OAuth error path
- Forgot password (no user enumeration) + reset password flow
- Send verify email (auth-required, idempotent 6-digit code)
- Verify email (wrong / correct / expired)
- Multimodal file upload (POST /api/uploads/image) + auth + validation
- Chat streaming with image attachments (credit cost = 1 + 3*images)
"""
import os
import io
import json
import time
import base64
import pytest
import requests
import pymongo
from datetime import datetime, timedelta, timezone

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    with open("/app/frontend/.env") as f:
        for line in f:
            if line.startswith("REACT_APP_BACKEND_URL="):
                BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
                break

API = f"{BASE_URL}/api"

# Direct mongo access for verifying reset_tokens / email_codes creation
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "iema_ai_v2")
_mongo = pymongo.MongoClient(MONGO_URL)
_db = _mongo[DB_NAME]

ADMIN_EMAIL = "siddharth.bose@iemlabs.com"
ADMIN_PASSWORD = "Admin@12345"

TIMESTAMP = int(time.time())
TEST_USER_EMAIL = f"test_iema_ph2_{TIMESTAMP}@example.com"
TEST_USER_PASSWORD = "Test@12345"
TEST_USER_NEW_PASSWORD = "NewPass@12345"
TEST_USER_NAME = "Phase2 Tester"

STATE = {}


# ---------------- Bootstrapping fixtures ----------------
@pytest.fixture(scope="module", autouse=True)
def bootstrap_user():
    """Register a fresh test user and admin login, then clean up at end."""
    # register user
    r = requests.post(f"{API}/auth/register", json={
        "email": TEST_USER_EMAIL,
        "password": TEST_USER_PASSWORD,
        "name": TEST_USER_NAME,
    }, timeout=15)
    assert r.status_code == 200, f"register failed: {r.text}"
    d = r.json()
    STATE["user_id"] = d["user"]["id"]
    STATE["access_token"] = d["tokens"]["access_token"]
    STATE["refresh_token"] = d["tokens"]["refresh_token"]

    # admin login
    ra = requests.post(f"{API}/auth/login", json={
        "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD,
    }, timeout=15)
    assert ra.status_code == 200
    STATE["admin_token"] = ra.json()["tokens"]["access_token"]

    yield

    # teardown: attempt delete of test user
    try:
        requests.delete(f"{API}/auth/me", headers=_uh(), timeout=10)
    except Exception:
        pass


def _uh():
    return {"Authorization": f"Bearer {STATE['access_token']}"}


def _ah():
    return {"Authorization": f"Bearer {STATE['admin_token']}"}


# ---------------- OAuth config ----------------
def test_oauth_config_returns_expected_providers():
    r = requests.get(f"{API}/auth/oauth-config", timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d["google"]["enabled"] is True
    assert d["google"]["client_id"]
    assert d["microsoft"]["enabled"] is True
    assert d["microsoft"]["client_id"]
    assert d["apple"]["enabled"] is False
    assert d["facebook"]["enabled"] is False


# ---------------- Microsoft OAuth error path ----------------
def test_microsoft_oauth_with_fake_code_returns_400():
    r = requests.post(f"{API}/auth/microsoft", json={
        "code": "fake_ms_code",
        "redirect_uri": "https://example.com/auth/callback",
    }, timeout=20)
    assert r.status_code == 400, f"expected 400, got {r.status_code}: {r.text}"


# ---------------- Forgot / Reset password ----------------
def test_forgot_password_random_email_returns_ok_no_enum():
    r = requests.post(f"{API}/auth/forgot-password", json={
        "email": f"does_not_exist_{TIMESTAMP}@example.com",
    }, timeout=10)
    assert r.status_code == 200
    assert r.json() == {"ok": True}


def test_forgot_password_existing_user_creates_reset_token():
    # Clean any previous tokens for this user
    _db.reset_tokens.delete_many({"user_id": STATE["user_id"]})

    r = requests.post(f"{API}/auth/forgot-password", json={
        "email": TEST_USER_EMAIL,
    }, timeout=10)
    assert r.status_code == 200
    assert r.json() == {"ok": True}

    # A reset token should exist for the user
    tok_doc = _db.reset_tokens.find_one({"user_id": STATE["user_id"], "used": False})
    assert tok_doc is not None, "reset token not created for existing user"
    assert tok_doc.get("token")
    STATE["reset_token"] = tok_doc["token"]


def test_reset_password_with_invalid_token_returns_400():
    r = requests.post(f"{API}/auth/reset-password", json={
        "token": "invalid-token-xyz",
        "new_password": "Whatever@12345",
    }, timeout=10)
    assert r.status_code == 400


def test_reset_password_with_valid_token_succeeds_and_invalidates_sessions():
    token = STATE.get("reset_token")
    assert token, "no reset token"

    # Count sessions before (should be >= 1 from register + admin)
    sessions_before = _db.sessions.count_documents({"user_id": STATE["user_id"]})
    assert sessions_before >= 1

    r = requests.post(f"{API}/auth/reset-password", json={
        "token": token,
        "new_password": TEST_USER_NEW_PASSWORD,
    }, timeout=10)
    assert r.status_code == 200, r.text
    assert r.json() == {"ok": True}

    # Token marked used
    used = _db.reset_tokens.find_one({"token": token})
    assert used["used"] is True

    # All sessions for the user should be deleted
    sessions_after = _db.sessions.count_documents({"user_id": STATE["user_id"]})
    assert sessions_after == 0

    # Old password should now fail
    r_old = requests.post(f"{API}/auth/login", json={
        "email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD,
    }, timeout=10)
    assert r_old.status_code == 401

    # New password should work; refresh access token in STATE
    r_new = requests.post(f"{API}/auth/login", json={
        "email": TEST_USER_EMAIL, "password": TEST_USER_NEW_PASSWORD,
    }, timeout=15)
    assert r_new.status_code == 200
    STATE["access_token"] = r_new.json()["tokens"]["access_token"]
    STATE["refresh_token"] = r_new.json()["tokens"]["refresh_token"]


def test_reset_password_reuse_same_token_returns_400():
    r = requests.post(f"{API}/auth/reset-password", json={
        "token": STATE["reset_token"],
        "new_password": "SomethingElse@123",
    }, timeout=10)
    assert r.status_code == 400


# ---------------- Verify email flow ----------------
def test_send_verify_email_requires_auth():
    r = requests.post(f"{API}/auth/send-verify-email", timeout=10)
    # No token
    assert r.status_code in (401, 403)


def test_send_verify_email_creates_code_and_is_idempotent():
    # cleanup
    _db.email_codes.delete_many({"user_id": STATE["user_id"], "purpose": "verify"})

    r = requests.post(f"{API}/auth/send-verify-email", headers=_uh(), timeout=10)
    assert r.status_code == 200
    assert r.json().get("ok") is True

    doc1 = _db.email_codes.find_one({"user_id": STATE["user_id"], "purpose": "verify"})
    assert doc1 is not None
    assert len(doc1["code"]) == 6 and doc1["code"].isdigit()
    first_code = doc1["code"]
    STATE["verify_code"] = first_code

    # Idempotent — call again, code may rotate but only one doc must exist
    r2 = requests.post(f"{API}/auth/send-verify-email", headers=_uh(), timeout=10)
    assert r2.status_code == 200
    count = _db.email_codes.count_documents({"user_id": STATE["user_id"], "purpose": "verify"})
    assert count == 1, f"expected exactly 1 pending code, got {count}"
    STATE["verify_code"] = _db.email_codes.find_one(
        {"user_id": STATE["user_id"], "purpose": "verify"})["code"]


def test_verify_email_wrong_code_returns_400():
    r = requests.post(f"{API}/auth/verify-email", json={"code": "000000"},
                      headers=_uh(), timeout=10)
    # Only fails if 000000 happens to match — extremely unlikely
    if STATE.get("verify_code") == "000000":
        # regenerate
        _db.email_codes.update_one(
            {"user_id": STATE["user_id"], "purpose": "verify"},
            {"$set": {"code": "111111"}},
        )
        STATE["verify_code"] = "111111"
        r = requests.post(f"{API}/auth/verify-email", json={"code": "000000"},
                          headers=_uh(), timeout=10)
    assert r.status_code == 400
    assert "Invalid" in r.text or "invalid" in r.text


def test_verify_email_expired_code_returns_400():
    # Force expiration
    _db.email_codes.update_one(
        {"user_id": STATE["user_id"], "purpose": "verify"},
        {"$set": {"expires_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()}},
    )
    code = STATE["verify_code"]
    r = requests.post(f"{API}/auth/verify-email", json={"code": code},
                      headers=_uh(), timeout=10)
    assert r.status_code == 400
    assert "expired" in r.text.lower()


def test_verify_email_correct_code_marks_verified_and_removes():
    # Re-issue code
    r = requests.post(f"{API}/auth/send-verify-email", headers=_uh(), timeout=10)
    assert r.status_code == 200
    doc = _db.email_codes.find_one({"user_id": STATE["user_id"], "purpose": "verify"})
    code = doc["code"]

    r2 = requests.post(f"{API}/auth/verify-email", json={"code": code},
                       headers=_uh(), timeout=10)
    assert r2.status_code == 200, r2.text
    assert r2.json().get("verified") is True

    # Code removed
    assert _db.email_codes.find_one({"user_id": STATE["user_id"], "purpose": "verify"}) is None

    # User marked verified
    me = requests.get(f"{API}/auth/me", headers=_uh(), timeout=10).json()
    assert me["email_verified"] is True


# ---------------- Uploads: image ----------------
def _tiny_jpeg_bytes() -> bytes:
    """1x1 red-pixel JPEG (~125 bytes) — a valid minimal image for S3/vision."""
    b64 = ("/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh"
           "0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIy"
           "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAA"
           "EDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAv/xAAUEAEAAAAAAAAAAAAAAAAAAAAA"
           "/8QAFAEBAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AH+P/9k=")
    return base64.b64decode(b64)


def test_upload_image_without_auth_returns_401():
    files = {"file": ("x.jpg", _tiny_jpeg_bytes(), "image/jpeg")}
    r = requests.post(f"{API}/uploads/image", files=files, timeout=30)
    assert r.status_code in (401, 403)


def test_upload_image_non_image_returns_400():
    files = {"file": ("x.txt", b"hello world", "text/plain")}
    r = requests.post(f"{API}/uploads/image", files=files, headers=_uh(), timeout=30)
    assert r.status_code == 400


def test_upload_image_oversize_returns_400():
    big = b"\x00" * (9 * 1024 * 1024)  # 9 MB
    files = {"file": ("big.png", big, "image/png")}
    r = requests.post(f"{API}/uploads/image", files=files, headers=_uh(), timeout=60)
    assert r.status_code == 400


def test_upload_image_valid_jpeg_returns_key_and_signed_url():
    files = {"file": ("tiny.jpg", _tiny_jpeg_bytes(), "image/jpeg")}
    r = requests.post(f"{API}/uploads/image", files=files, headers=_uh(), timeout=60)
    assert r.status_code == 200, f"upload failed: {r.status_code} {r.text}"
    d = r.json()
    assert "key" in d and d["key"].startswith("chat/")
    assert d["content_type"] == "image/jpeg"
    assert d["size"] > 0
    assert d["filename"] == "tiny.jpg"
    STATE["upload_url"] = d["url"]
    STATE["upload_key"] = d["key"]
    # Accept either SigV4 (X-Amz-Signature) or SigV2 (Signature=) presigned URLs
    assert d["url"].startswith("https://")
    assert ("X-Amz-Signature" in d["url"]) or ("Signature=" in d["url"]), \
        f"URL missing signature params: {d['url']}"

    # signed URL should return 200 when fetched
    fr = requests.get(d["url"], timeout=30)
    assert fr.status_code == 200, f"presigned URL fetch failed: {fr.status_code}"
    assert fr.headers.get("Content-Type", "").startswith("image/")


# ---------------- Chat with attachments ----------------
def _read_sse(response, max_seconds=60):
    events = []
    start = time.time()
    for line in response.iter_lines(decode_unicode=True):
        if time.time() - start > max_seconds:
            break
        if not line:
            continue
        if line.startswith("data: "):
            payload = line[6:]
            if payload.strip() == "[DONE]":
                break
            try:
                events.append(json.loads(payload))
            except json.JSONDecodeError:
                pass
    return events


def test_chat_stream_with_one_image_deducts_4_credits():
    url = STATE.get("upload_url")
    if not url:
        pytest.skip("no upload URL")

    w0 = requests.get(f"{API}/wallet/", headers=_uh(), timeout=10).json()
    before = w0["total"]

    with requests.post(
        f"{API}/chat/stream",
        json={
            "content": "Describe this image briefly.",
            "attachments": [{
                "url": url,
                "content_type": "image/jpeg",
                "filename": "tiny.jpg",
            }],
        },
        headers=_uh(),
        stream=True,
        timeout=90,
    ) as r:
        assert r.status_code == 200, f"stream failed: {r.status_code} {r.text[:400]}"
        events = _read_sse(r, max_seconds=60)

    types = [e.get("type") for e in events]
    assert "conversation" in types
    saved = next((e for e in events if e.get("type") == "saved"), None)
    assert saved, f"no saved event; got types={types}"
    assert saved["credits_used"] == 4, f"expected 4 credits, got {saved['credits_used']}"

    w1 = requests.get(f"{API}/wallet/", headers=_uh(), timeout=10).json()
    assert w1["total"] == before - 4, f"expected {before - 4}, got {w1['total']}"


def test_chat_stream_with_two_images_deducts_7_credits():
    url = STATE.get("upload_url")
    if not url:
        pytest.skip("no upload URL")

    w0 = requests.get(f"{API}/wallet/", headers=_uh(), timeout=10).json()
    before = w0["total"]

    with requests.post(
        f"{API}/chat/stream",
        json={
            "content": "Compare these images in one sentence.",
            "attachments": [
                {"url": url, "content_type": "image/jpeg", "filename": "a.jpg"},
                {"url": url, "content_type": "image/jpeg", "filename": "b.jpg"},
            ],
        },
        headers=_uh(),
        stream=True,
        timeout=90,
    ) as r:
        assert r.status_code == 200
        events = _read_sse(r, max_seconds=60)
    saved = next((e for e in events if e.get("type") == "saved"), None)
    assert saved, "no saved event"
    assert saved["credits_used"] == 7, f"expected 7 credits, got {saved['credits_used']}"

    w1 = requests.get(f"{API}/wallet/", headers=_uh(), timeout=10).json()
    assert w1["total"] == before - 7


def test_chat_stream_with_attachments_and_no_credits_returns_402():
    # Drain wallet via admin negative adjust
    requests.post(f"{API}/admin/wallet/adjust", json={
        "user_id": STATE["user_id"],
        "amount": -100000,
        "bucket": "welcome",
        "description": "TEST_ph2 drain",
    }, headers=_ah(), timeout=10)
    # Drain the other buckets too, just in case
    for bucket in ["daily", "bonus", "referral", "purchased", "promotional"]:
        requests.post(f"{API}/admin/wallet/adjust", json={
            "user_id": STATE["user_id"],
            "amount": -100000,
            "bucket": bucket,
            "description": f"TEST_ph2 drain {bucket}",
        }, headers=_ah(), timeout=10)

    w = requests.get(f"{API}/wallet/", headers=_uh(), timeout=10).json()
    if w["total"] >= 4:
        pytest.skip(f"could not drain wallet (still {w['total']} credits)")

    r = requests.post(
        f"{API}/chat/stream",
        json={
            "content": "hi",
            "attachments": [{"url": STATE.get("upload_url") or "https://x/y.jpg",
                             "content_type": "image/jpeg", "filename": "x.jpg"}],
        },
        headers=_uh(),
        timeout=20,
    )
    assert r.status_code == 402
