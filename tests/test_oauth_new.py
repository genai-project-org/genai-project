"""Tests for new OAuth id_token verify endpoints (Microsoft, Apple) + regressions.

Focus:
- REGRESSION: email/password login, register, google-verify existence, /auth/microsoft (legacy)
- NEW: /auth/oauth-config reports 4 providers correctly
- NEW: /auth/microsoft-verify → 400 for invalid token, 422 without id_token
- NEW: /auth/apple → 400 for invalid token, 422 without id_token
"""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://iema-ai-platform.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


@pytest.fixture(scope="module")
def sess():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- OAuth config ----------
class TestOAuthConfig:
    def test_oauth_config_shape(self, sess):
        r = sess.get(f"{API}/auth/oauth-config", timeout=15)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["google"]["enabled"] is True
        assert isinstance(data["google"]["client_id"], str) and len(data["google"]["client_id"]) > 5
        assert data["microsoft"]["enabled"] is True
        assert isinstance(data["microsoft"]["client_id"], str) and len(data["microsoft"]["client_id"]) > 5
        assert data["apple"]["enabled"] is True
        assert isinstance(data["apple"]["client_id"], str) and len(data["apple"]["client_id"]) > 3
        assert data["facebook"]["enabled"] is False


# ---------- Microsoft verify ----------
class TestMicrosoftVerify:
    def test_invalid_id_token_returns_400(self, sess):
        r = sess.post(f"{API}/auth/microsoft-verify", json={"id_token": "not.a.valid.jwt"}, timeout=20)
        assert r.status_code == 400, f"Expected 400 got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("detail") == "Invalid Microsoft token"

    def test_missing_id_token_returns_422(self, sess):
        r = sess.post(f"{API}/auth/microsoft-verify", json={}, timeout=15)
        assert r.status_code == 422, f"Expected 422 got {r.status_code}: {r.text}"

    def test_legacy_microsoft_endpoint_exists(self, sess):
        # Should NOT be 404. Since we send bogus code, expect 400 (or 501 if key missing, but keys are set)
        r = sess.post(f"{API}/auth/microsoft", json={"code": "bogus", "redirect_uri": "https://example.com/cb"}, timeout=20)
        assert r.status_code != 404, f"Legacy microsoft endpoint missing: {r.status_code}"
        assert r.status_code in (400, 401, 501), f"Unexpected status {r.status_code}: {r.text}"


# ---------- Apple verify ----------
class TestAppleVerify:
    def test_invalid_id_token_returns_400(self, sess):
        r = sess.post(f"{API}/auth/apple", json={"id_token": "not.a.valid.jwt"}, timeout=20)
        assert r.status_code == 400, f"Expected 400 got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("detail") == "Invalid Apple token"

    def test_missing_id_token_returns_422(self, sess):
        r = sess.post(f"{API}/auth/apple", json={}, timeout=15)
        assert r.status_code == 422, f"Expected 422 got {r.status_code}: {r.text}"


# ---------- Google verify regression ----------
class TestGoogleVerifyRegression:
    def test_invalid_credential_returns_400(self, sess):
        r = sess.post(f"{API}/auth/google-verify", json={"credential": "not.a.valid.jwt"}, timeout=20)
        assert r.status_code == 400, f"Expected 400 got {r.status_code}: {r.text}"
        body = r.json()
        assert body.get("detail") == "Invalid Google token"


# ---------- Email/password regression ----------
class TestEmailPasswordRegression:
    ts = int(time.time())
    email = f"test_all_oauth_{ts}@example.com"
    password = "Test@12345"

    def test_register_success(self, sess):
        r = sess.post(f"{API}/auth/register", json={
            "email": self.email, "password": self.password, "name": "OAuth Regression"
        }, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["user"]["email"] == self.email
        assert body["tokens"]["access_token"]
        assert body["tokens"]["refresh_token"]

    def test_login_success_immediate_after_register(self, sess):
        # jti fix: register + login in same second must both return 200 with distinct tokens
        # (no time.sleep between them). Verifies /app/backend/auth.py jti claim uniqueness.
        r_reg = sess.post(f"{API}/auth/register", json={
            "email": f"test_jti_{int(time.time()*1000)}@example.com",
            "password": self.password, "name": "JTI Test"
        }, timeout=20)
        assert r_reg.status_code == 200, r_reg.text
        reg_body = r_reg.json()
        reg_access = reg_body["tokens"]["access_token"]
        reg_refresh = reg_body["tokens"]["refresh_token"]
        # Immediate login (no sleep)
        r = sess.post(f"{API}/auth/login", json={
            "email": reg_body["user"]["email"], "password": self.password
        }, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["tokens"]["access_token"]
        # Tokens must be distinct (jti fix)
        assert body["tokens"]["access_token"] != reg_access, "access_token collision — jti missing?"
        assert body["tokens"]["refresh_token"] != reg_refresh, "refresh_token collision — jti missing?"

    def test_admin_login(self, sess):
        r = sess.post(f"{API}/auth/login", json={
            "email": "siddharth.bose@iemlabs.com", "password": "Admin@12345"
        }, timeout=20)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["user"]["role"] == "admin"

    def test_login_invalid_credentials(self, sess):
        r = sess.post(f"{API}/auth/login", json={
            "email": "no_such_user_xyz@example.com", "password": "wrong"
        }, timeout=15)
        assert r.status_code == 401
