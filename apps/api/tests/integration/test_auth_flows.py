"""Integration tests for routers/auth_routes.py, exercised through FastAPI's
TestClient against the real endpoints, with only the DB (mongomock, via
conftest.py) and outbound network calls mocked/avoided.

No OAuth provider flows are covered here (google/microsoft/github/linkedin/
apple all require a real upstream token exchange) — every OAuth client-id env
var is deliberately left empty in conftest.py, so those routes 501 immediately
and aren't meaningfully testable without a live mock HTTP layer. The password
based register/login/refresh/reset flows are the real, fully-mockable core.
"""
import pytest

from db import users_col, wallets_col, sessions_col
from routers.auth_routes import reset_tokens_col

pytestmark = pytest.mark.integration


# ------------------------------ register ------------------------------

def test_register_creates_user_and_wallet(client):
    resp = client.post("/api/auth/register", json={
        "email": "newbie@example.com", "password": "Str0ngPass!", "name": "Newbie",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["email"] == "newbie@example.com"
    assert body["user"]["plan"] == "free"
    assert "access_token" in body["tokens"] and "refresh_token" in body["tokens"]
    # Registration must have provisioned a wallet, not just a user doc.
    import asyncio
    user_id = body["user"]["id"]
    wallet = asyncio.run(wallets_col.find_one({"user_id": user_id}))
    assert wallet is not None


def test_register_duplicate_email_conflicts(client, register_user):
    register_user(email="dupe@example.com")
    resp = client.post("/api/auth/register", json={
        "email": "dupe@example.com", "password": "Str0ngPass!", "name": "Someone Else",
    })
    assert resp.status_code == 409


def test_register_rejects_short_password(client):
    resp = client.post("/api/auth/register", json={
        "email": "short@example.com", "password": "abc", "name": "Short",
    })
    assert resp.status_code == 422


# ------------------------------ login ------------------------------

def test_login_success(client, register_user):
    register_user(email="loginok@example.com", password="Str0ngPass!")
    resp = client.post("/api/auth/login", json={
        "email": "loginok@example.com", "password": "Str0ngPass!",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["email"] == "loginok@example.com"
    assert "access_token" in body["tokens"]


def test_login_wrong_password_is_rejected(client, register_user):
    register_user(email="wrongpw@example.com", password="Str0ngPass!")
    resp = client.post("/api/auth/login", json={
        "email": "wrongpw@example.com", "password": "totally-different",
    })
    assert resp.status_code == 401


def test_login_unknown_email_is_rejected(client):
    resp = client.post("/api/auth/login", json={
        "email": "nobody-here@example.com", "password": "whatever123",
    })
    assert resp.status_code == 401


def test_login_disabled_account_is_forbidden(client, register_user):
    user, _tokens, _headers = register_user(email="disabled@example.com", password="Str0ngPass!")
    import asyncio
    from bson import ObjectId
    asyncio.run(users_col.update_one({"_id": ObjectId(user["id"])}, {"$set": {"is_active": False}}))
    resp = client.post("/api/auth/login", json={
        "email": "disabled@example.com", "password": "Str0ngPass!",
    })
    assert resp.status_code == 403


# ------------------------------ refresh / logout ------------------------------

def test_refresh_issues_a_new_token_pair(client, register_user):
    _user, tokens, _headers = register_user()
    resp = client.post("/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"]
    assert body["refresh_token"]


def test_refresh_rejects_an_access_token(client, register_user):
    _user, tokens, _headers = register_user()
    resp = client.post("/api/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert resp.status_code == 401


def test_refresh_rejects_garbage_token(client):
    resp = client.post("/api/auth/refresh", json={"refresh_token": "not-a-jwt"})
    assert resp.status_code == 401


def test_logout_deletes_the_session(client, register_user):
    user, tokens, _headers = register_user()
    import asyncio
    assert asyncio.run(sessions_col.count_documents({"user_id": user["id"]})) == 1
    resp = client.post("/api/auth/logout", json={"refresh_token": tokens["refresh_token"]})
    assert resp.status_code == 200
    assert asyncio.run(sessions_col.count_documents({"user_id": user["id"]})) == 0


# ------------------------------ /me ------------------------------

def test_me_requires_auth(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_me_returns_the_current_user(client, auth_user):
    user, _tokens, headers = auth_user
    resp = client.get("/api/auth/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == user["email"]


def test_update_me_changes_name_and_theme(client, auth_user):
    _user, _tokens, headers = auth_user
    resp = client.patch("/api/auth/me", json={"name": "New Name", "theme": "dark"}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "New Name"


def test_update_me_rejects_invalid_ai_provider(client, auth_user):
    _user, _tokens, headers = auth_user
    resp = client.patch("/api/auth/me", json={"ai_provider": "not-a-real-provider"}, headers=headers)
    assert resp.status_code == 400


def test_delete_me_removes_the_account(client, auth_user):
    user, _tokens, headers = auth_user
    resp = client.delete("/api/auth/me", headers=headers)
    assert resp.status_code == 200
    import asyncio
    from bson import ObjectId
    assert asyncio.run(users_col.find_one({"_id": ObjectId(user["id"])})) is None
    # Subsequent requests with the now-orphaned token must be unauthenticated.
    resp2 = client.get("/api/auth/me", headers=headers)
    assert resp2.status_code == 401


# ------------------------------ oauth-config (public) ------------------------------

def test_oauth_config_reports_all_providers_disabled_by_default(client):
    resp = client.get("/api/auth/oauth-config")
    assert resp.status_code == 200
    body = resp.json()
    for provider in ("google", "apple", "github", "linkedin"):
        assert body[provider]["enabled"] is False


# ------------------------------ forgot/reset password ------------------------------

def test_forgot_password_unknown_email_still_returns_ok(client):
    """No user enumeration: an unknown email gets the same {"ok": true}."""
    resp = client.post("/api/auth/forgot-password", json={"email": "ghost@example.com"})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


def test_full_password_reset_flow(client, register_user, monkeypatch):
    # `forgot_password` draws its OTP from `secrets.randbelow(...)`. Pin it to a
    # known value instead of brute-forcing the bcrypt hash at rest (correct per
    # the app's design, but computationally way too slow to do 10^6 times here).
    import routers.auth_routes as auth_routes
    monkeypatch.setattr(auth_routes.secrets, "randbelow", lambda _n: 123456)

    register_user(email="resetme@example.com", password="OldPassw0rd!")

    resp = client.post("/api/auth/forgot-password", json={"email": "resetme@example.com"})
    assert resp.status_code == 200

    import asyncio
    doc = asyncio.run(reset_tokens_col.find_one({"email": "resetme@example.com", "kind": "reset_otp"}))
    assert doc is not None

    resp = client.post("/api/auth/verify-reset-otp", json={"email": "resetme@example.com", "otp": "123456"})
    assert resp.status_code == 200, resp.text
    reset_token = resp.json()["reset_token"]

    resp = client.post("/api/auth/reset-password", json={
        "token": reset_token, "new_password": "BrandNewPassw0rd!",
    })
    assert resp.status_code == 200

    # Old password must no longer work, new one must.
    resp = client.post("/api/auth/login", json={"email": "resetme@example.com", "password": "OldPassw0rd!"})
    assert resp.status_code == 401
    resp = client.post("/api/auth/login", json={"email": "resetme@example.com", "password": "BrandNewPassw0rd!"})
    assert resp.status_code == 200


def test_verify_reset_otp_rejects_wrong_code(client, register_user, monkeypatch):
    import routers.auth_routes as auth_routes
    monkeypatch.setattr(auth_routes.secrets, "randbelow", lambda _n: 123456)

    register_user(email="wrongotp@example.com", password="OldPassw0rd!")
    client.post("/api/auth/forgot-password", json={"email": "wrongotp@example.com"})

    resp = client.post("/api/auth/verify-reset-otp", json={"email": "wrongotp@example.com", "otp": "654321"})
    assert resp.status_code == 400
