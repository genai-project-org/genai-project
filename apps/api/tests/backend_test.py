"""
IEMA.ai v2 backend integration tests.
Covers: auth, wallet, chat streaming, credit deduction, usage, packs, payments,
notifications, admin.
"""
import os
import json
import time
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    # fallback to frontend .env
    try:
        with open("/app/frontend/.env") as f:
            for line in f:
                if line.startswith("REACT_APP_BACKEND_URL="):
                    BASE_URL = line.split("=", 1)[1].strip().strip('"').rstrip("/")
                    break
    except Exception:
        pass

API = f"{BASE_URL}/api"
ADMIN_EMAIL = "siddharth.bose@iemlabs.com"
ADMIN_PASSWORD = "Admin@12345"

TEST_USER_EMAIL = f"test_iema_{int(time.time())}@example.com"
TEST_USER_PASSWORD = "Test@12345"
TEST_USER_NAME = "IEMA Tester"

# Shared state across tests
STATE = {}


# ---------- Health ----------
def test_health():
    r = requests.get(f"{API}/health", timeout=10)
    assert r.status_code == 200
    assert r.json().get("status") == "healthy"


# ---------- Auth: Register ----------
def test_register_new_user_and_wallet_seed():
    payload = {
        "email": TEST_USER_EMAIL,
        "password": TEST_USER_PASSWORD,
        "name": TEST_USER_NAME,
    }
    r = requests.post(f"{API}/auth/register", json=payload, timeout=15)
    assert r.status_code == 200, f"register failed: {r.status_code} {r.text}"
    data = r.json()
    assert "user" in data and "tokens" in data
    assert data["user"]["email"] == TEST_USER_EMAIL
    assert data["user"]["role"] == "user"
    assert data["tokens"]["access_token"]
    assert data["tokens"]["refresh_token"]
    STATE["user_id"] = data["user"]["id"]
    STATE["access_token"] = data["tokens"]["access_token"]
    STATE["refresh_token"] = data["tokens"]["refresh_token"]


def _user_headers():
    return {"Authorization": f"Bearer {STATE['access_token']}"}


def test_register_duplicate_returns_409():
    payload = {
        "email": TEST_USER_EMAIL,
        "password": TEST_USER_PASSWORD,
        "name": TEST_USER_NAME,
    }
    r = requests.post(f"{API}/auth/register", json=payload, timeout=15)
    assert r.status_code == 409


def test_auth_me_returns_current_user():
    r = requests.get(f"{API}/auth/me", headers=_user_headers(), timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d["email"] == TEST_USER_EMAIL
    assert d["id"] == STATE["user_id"]


def test_login_valid_credentials():
    r = requests.post(f"{API}/auth/login", json={
        "email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD
    }, timeout=15)
    assert r.status_code == 200
    d = r.json()
    assert d["tokens"]["access_token"]
    assert d["tokens"]["refresh_token"]


def test_login_invalid_password_returns_401():
    r = requests.post(f"{API}/auth/login", json={
        "email": TEST_USER_EMAIL, "password": "WrongPass123"
    }, timeout=10)
    assert r.status_code == 401


def test_refresh_returns_new_token_pair():
    r = requests.post(f"{API}/auth/refresh", json={
        "refresh_token": STATE["refresh_token"]
    }, timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d["access_token"]
    assert d["refresh_token"]


def test_refresh_with_invalid_token():
    r = requests.post(f"{API}/auth/refresh", json={
        "refresh_token": "invalid.token.here"
    }, timeout=10)
    assert r.status_code == 401


# ---------- Admin login ----------
def test_admin_login_and_role():
    r = requests.post(f"{API}/auth/login", json={
        "email": ADMIN_EMAIL, "password": ADMIN_PASSWORD
    }, timeout=15)
    assert r.status_code == 200, f"admin login failed: {r.text}"
    d = r.json()
    assert d["user"]["role"] == "admin"
    STATE["admin_token"] = d["tokens"]["access_token"]
    STATE["admin_id"] = d["user"]["id"]


def _admin_headers():
    return {"Authorization": f"Bearer {STATE['admin_token']}"}


# ---------- Wallet ----------
def test_wallet_returns_all_buckets_and_total_120():
    r = requests.get(f"{API}/wallet/", headers=_user_headers(), timeout=10)
    assert r.status_code == 200
    d = r.json()
    for key in ["welcome_credits", "daily_credits", "bonus_credits",
                "referral_credits", "promotional_credits", "purchased_credits", "total"]:
        assert key in d, f"missing bucket {key}"
    assert d["welcome_credits"] == 100
    assert d["daily_credits"] == 20
    assert d["total"] == 120


def test_wallet_transactions_show_signup_and_daily():
    r = requests.get(f"{API}/wallet/transactions", headers=_user_headers(), timeout=10)
    assert r.status_code == 200
    d = r.json()
    kinds = {t["kind"] for t in d["items"]}
    assert "signup_bonus" in kinds
    assert "daily_refill" in kinds


# ---------- Packs ----------
def test_packs_usd():
    r = requests.get(f"{API}/packs/?currency=usd", timeout=10)
    assert r.status_code == 200
    items = r.json()["items"]
    slugs = {p["slug"] for p in items}
    assert {"starter-usd", "standard-usd", "pro-usd", "business-usd"}.issubset(slugs)
    for p in items:
        assert p["currency"] == "usd"


def test_packs_inr():
    r = requests.get(f"{API}/packs/?currency=inr", timeout=10)
    assert r.status_code == 200
    items = r.json()["items"]
    slugs = {p["slug"] for p in items}
    assert {"starter-inr", "standard-inr", "pro-inr", "business-inr"}.issubset(slugs)


# ---------- Chat streaming ----------
def _read_sse(response, max_seconds=45):
    """Parse SSE lines from a streaming response. Returns list of parsed JSON events."""
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


def test_chat_stream_hello_deducts_credit():
    # get wallet before
    wr = requests.get(f"{API}/wallet/", headers=_user_headers(), timeout=10)
    before_total = wr.json()["total"]

    with requests.post(
        f"{API}/chat/stream",
        json={"content": "hello"},
        headers=_user_headers(),
        stream=True,
        timeout=60,
    ) as r:
        assert r.status_code == 200, f"stream failed: {r.status_code} {r.text[:500]}"
        events = _read_sse(r, max_seconds=45)

    types = [e.get("type") for e in events]
    assert "conversation" in types, f"missing conversation: {types}"
    assert "meta" in types, f"missing meta: {types}"
    assert "delta" in types, f"missing delta tokens: {types}"
    assert "done" in types, f"missing done: {types}"
    assert "saved" in types, f"missing saved: {types}"

    meta = next(e for e in events if e["type"] == "meta")
    assert meta.get("provider") == "anthropic"
    assert meta.get("model") == "claude-haiku-4-5-20251001"

    conv_evt = next(e for e in events if e["type"] == "conversation")
    STATE["conversation_id"] = conv_evt["conversation_id"]

    # wallet after
    wr2 = requests.get(f"{API}/wallet/", headers=_user_headers(), timeout=10)
    after_total = wr2.json()["total"]
    assert after_total == before_total - 1, f"expected 1 credit deducted, before={before_total}, after={after_total}"


def test_list_conversations_after_chat():
    r = requests.get(f"{API}/chat/conversations", headers=_user_headers(), timeout=10)
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) >= 1
    assert any(i["id"] == STATE["conversation_id"] for i in items)


def test_get_conversation_returns_messages():
    cid = STATE["conversation_id"]
    r = requests.get(f"{API}/chat/conversations/{cid}", headers=_user_headers(), timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d["conversation"]["id"] == cid
    assert len(d["messages"]) >= 2  # user + assistant
    roles = [m["role"] for m in d["messages"]]
    assert "user" in roles and "assistant" in roles


def test_rename_conversation():
    cid = STATE["conversation_id"]
    r = requests.patch(f"{API}/chat/conversations/{cid}",
                       json={"title": "Renamed Chat"},
                       headers=_user_headers(), timeout=10)
    assert r.status_code == 200
    # verify persistence
    g = requests.get(f"{API}/chat/conversations/{cid}", headers=_user_headers(), timeout=10)
    assert g.json()["conversation"]["title"] == "Renamed Chat"


def test_pin_conversation_toggle():
    cid = STATE["conversation_id"]
    r = requests.post(f"{API}/chat/conversations/{cid}/pin",
                      headers=_user_headers(), timeout=10)
    assert r.status_code == 200
    assert r.json()["pinned"] is True
    # toggle back
    r2 = requests.post(f"{API}/chat/conversations/{cid}/pin",
                       headers=_user_headers(), timeout=10)
    assert r2.json()["pinned"] is False


# ---------- Usage analytics ----------
def test_usage_summary():
    r = requests.get(f"{API}/usage/summary", headers=_user_headers(), timeout=10)
    assert r.status_code == 200
    d = r.json()
    for k in ["credits_used_today", "credits_used_week", "credits_used_month",
              "credits_used_lifetime", "requests_today", "requests_week",
              "requests_month", "requests_lifetime", "avg_credits_per_request",
              "most_used_provider", "most_used_model"]:
        assert k in d
    assert d["requests_lifetime"] >= 1
    assert d["most_used_provider"] == "anthropic"


def test_usage_timeline_30d():
    r = requests.get(f"{API}/usage/timeline?period=30d", headers=_user_headers(), timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert "items" in d
    if d["items"]:
        it = d["items"][0]
        assert "date" in it and "credits" in it and "requests" in it


# ---------- Payments ----------
def test_stripe_checkout_creates_session():
    r = requests.post(
        f"{API}/payments/stripe/checkout",
        json={"pack_slug": "starter-usd", "origin_url": "https://example.com"},
        headers=_user_headers(),
        timeout=25,
    )
    assert r.status_code == 200, f"stripe checkout failed: {r.text}"
    d = r.json()
    assert d.get("url", "").startswith("http")
    assert d.get("session_id")
    STATE["stripe_session_id"] = d["session_id"]


def test_stripe_status_pending_or_expired():
    sid = STATE.get("stripe_session_id")
    if not sid:
        pytest.skip("no stripe session")
    r = requests.get(f"{API}/payments/stripe/status/{sid}",
                     headers=_user_headers(), timeout=15)
    assert r.status_code == 200
    assert r.json()["status"] in {"pending", "expired", "paid"}


def test_razorpay_order_creation():
    r = requests.post(
        f"{API}/payments/razorpay/order",
        json={"pack_slug": "starter-inr"},
        headers=_user_headers(),
        timeout=25,
    )
    assert r.status_code == 200, f"razorpay order failed: {r.text}"
    d = r.json()
    assert d["order_id"]
    assert d["amount"] == 39900  # 399 INR in paise
    assert d["currency"] == "INR"
    assert d["key_id"] == "rzp_test_TDhESSSBMNRfAM"
    assert d["credits"] >= 500
    STATE["razorpay_order_id"] = d["order_id"]


def test_razorpay_verify_invalid_signature():
    if not STATE.get("razorpay_order_id"):
        pytest.skip("no razorpay order")
    r = requests.post(
        f"{API}/payments/razorpay/verify",
        json={
            "razorpay_order_id": STATE["razorpay_order_id"],
            "razorpay_payment_id": "pay_invalid",
            "razorpay_signature": "invalid_sig",
        },
        headers=_user_headers(),
        timeout=10,
    )
    assert r.status_code == 400


def test_payment_history():
    r = requests.get(f"{API}/payments/history", headers=_user_headers(), timeout=10)
    assert r.status_code == 200
    items = r.json()["items"]
    providers = {p["provider"] for p in items}
    assert "stripe" in providers or "razorpay" in providers


# ---------- Notifications ----------
def test_notifications_list():
    r = requests.get(f"{API}/notifications/", headers=_user_headers(), timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert "items" in d and "unread_count" in d


def test_notifications_mark_all_read_idempotent():
    r = requests.post(f"{API}/notifications/mark-all-read",
                      headers=_user_headers(), timeout=10)
    assert r.status_code == 200
    # Call again
    r2 = requests.post(f"{API}/notifications/mark-all-read",
                       headers=_user_headers(), timeout=10)
    assert r2.status_code == 200


# ---------- Admin routes ----------
def test_admin_routes_require_admin_role():
    r = requests.get(f"{API}/admin/stats", headers=_user_headers(), timeout=10)
    assert r.status_code == 403


def test_admin_stats():
    r = requests.get(f"{API}/admin/stats", headers=_admin_headers(), timeout=10)
    assert r.status_code == 200
    d = r.json()
    for k in ["total_users", "total_conversations", "total_messages",
              "total_ai_requests", "revenue"]:
        assert k in d
    assert d["total_users"] >= 1


def test_admin_users_list_with_credits_total():
    r = requests.get(f"{API}/admin/users?limit=100", headers=_admin_headers(), timeout=10)
    assert r.status_code == 200
    d = r.json()
    assert d["total"] >= 1
    # find our test user
    matches = [u for u in d["items"] if u["email"] == TEST_USER_EMAIL]
    assert matches, "test user not in admin users list"
    assert "credits_total" in matches[0]


def test_admin_wallet_adjust_adds_credits():
    # Get before
    r0 = requests.get(f"{API}/wallet/", headers=_user_headers(), timeout=10)
    before = r0.json()["total"]
    r = requests.post(f"{API}/admin/wallet/adjust", json={
        "user_id": STATE["user_id"],
        "amount": 50,
        "bucket": "bonus",
        "description": "TEST_ admin adjust",
    }, headers=_admin_headers(), timeout=10)
    assert r.status_code == 200
    r2 = requests.get(f"{API}/wallet/", headers=_user_headers(), timeout=10)
    after = r2.json()["total"]
    assert after == before + 50


def test_admin_toggle_active_and_re_enable():
    uid = STATE["user_id"]
    r = requests.post(f"{API}/admin/users/{uid}/toggle-active",
                      headers=_admin_headers(), timeout=10)
    assert r.status_code == 200
    assert r.json()["is_active"] is False
    # re-enable
    r2 = requests.post(f"{API}/admin/users/{uid}/toggle-active",
                       headers=_admin_headers(), timeout=10)
    assert r2.status_code == 200
    assert r2.json()["is_active"] is True


def test_admin_promote_toggle():
    uid = STATE["user_id"]
    r = requests.post(f"{API}/admin/users/{uid}/promote",
                      headers=_admin_headers(), timeout=10)
    assert r.status_code == 200
    assert r.json()["role"] == "admin"
    # toggle back
    r2 = requests.post(f"{API}/admin/users/{uid}/promote",
                       headers=_admin_headers(), timeout=10)
    assert r2.json()["role"] == "user"


# ---------- Profile update ----------
def test_patch_me_updates_name():
    r = requests.patch(f"{API}/auth/me", json={"name": "Renamed IEMA"},
                       headers=_user_headers(), timeout=10)
    assert r.status_code == 200
    assert r.json()["name"] == "Renamed IEMA"


# ---------- Insufficient credits ----------
def test_insufficient_credits_returns_402():
    # Set wallet to 0 via admin negative adjustment isn't allowed easily.
    # We'll drain by direct wallet manipulation via admin negative adjust bucket bonus.
    # Simpler: check wallet, and reduce all buckets to 0 by admin adjust negatively.
    # Since add_credits only adds positive, we simulate by making chat request many times.
    # Instead: create a fresh user with 120 credits, and use admin adjust with negative amount not supported.
    # Directly hit stream after zeroing via mongo not allowed here. So skip if hard.
    # Approach: use admin adjust to add -120 (bonus can go negative? in code just adds). Let's just use admin adjust negative.
    r = requests.post(f"{API}/admin/wallet/adjust", json={
        "user_id": STATE["user_id"],
        "amount": -1000,  # large negative to drain
        "bucket": "welcome",
        "description": "TEST_ drain",
    }, headers=_admin_headers(), timeout=10)
    # add_credits doesn't check for negatives, but it will just add negative to welcome bucket
    if r.status_code != 200:
        pytest.skip("cannot drain wallet for insufficient credits test")

    # verify wallet total <= 0
    w = requests.get(f"{API}/wallet/", headers=_user_headers(), timeout=10).json()
    if w["total"] >= 1:
        pytest.skip(f"wallet still has {w['total']} credits, skip 402 test")

    r2 = requests.post(f"{API}/chat/stream",
                       json={"content": "hi again"},
                       headers=_user_headers(), timeout=15)
    assert r2.status_code == 402


# ---------- Delete conversation & delete account ----------
def test_delete_conversation():
    cid = STATE.get("conversation_id")
    if not cid:
        pytest.skip("no conv")
    r = requests.delete(f"{API}/chat/conversations/{cid}",
                        headers=_user_headers(), timeout=10)
    assert r.status_code == 200
    # verify gone
    g = requests.get(f"{API}/chat/conversations/{cid}", headers=_user_headers(), timeout=10)
    assert g.status_code == 404


def test_delete_account_and_revokes_sessions():
    r = requests.delete(f"{API}/auth/me", headers=_user_headers(), timeout=10)
    assert r.status_code == 200
    assert r.json().get("ok") is True
    # /me now returns 401
    r2 = requests.get(f"{API}/auth/me", headers=_user_headers(), timeout=10)
    assert r2.status_code == 401
