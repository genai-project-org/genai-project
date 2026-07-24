"""Focused regression tests for auth bug fix (Google GIS + email/password)."""
import os
import time
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://iema-ai-platform.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "siddharth.bose@iemlabs.com"
ADMIN_PASSWORD = "Admin@12345"


@pytest.fixture(scope="module")
def session():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- Email/Password login regression ----------
class TestEmailLogin:
    def test_admin_login_success(self, session):
        r = session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 200, r.text
        data = r.json()
        assert "user" in data and "tokens" in data
        assert data["user"]["email"] == ADMIN_EMAIL
        assert data["tokens"]["access_token"]
        assert data["tokens"]["refresh_token"]

    def test_admin_login_wrong_password(self, session):
        r = session.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": "WRONG"})
        assert r.status_code == 401


# ---------- Register regression ----------
class TestEmailRegister:
    def test_register_new_user(self, session):
        ts = int(time.time())
        email = f"test_bugfix_{ts}@example.com"
        r = session.post(f"{API}/auth/register", json={
            "email": email, "password": "Test@12345", "name": "Bugfix Tester"
        })
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["user"]["email"] == email
        assert data["user"]["name"] == "Bugfix Tester"
        assert data["tokens"]["access_token"]

        # Verify /me works with the returned token
        me = session.get(
            f"{API}/auth/me",
            headers={"Authorization": f"Bearer {data['tokens']['access_token']}"},
        )
        assert me.status_code == 200
        assert me.json()["email"] == email

    def test_register_duplicate_email(self, session):
        # admin already exists → 409
        r = session.post(f"{API}/auth/register", json={
            "email": ADMIN_EMAIL, "password": "Whatever@1", "name": "X"
        })
        assert r.status_code == 409


# ---------- NEW /auth/google-verify endpoint ----------
class TestGoogleIdTokenVerify:
    def test_google_verify_endpoint_exists_and_400_on_invalid(self, session):
        r = session.post(f"{API}/auth/google-verify", json={"credential": "not-a-real-token"})
        # Must NOT be 404 (endpoint exists) and must NOT be 500 (must handle error gracefully)
        assert r.status_code != 404, "Endpoint /auth/google-verify not found"
        assert r.status_code != 500, f"Endpoint should not 500: {r.text}"
        assert r.status_code == 400, f"Expected 400, got {r.status_code}: {r.text}"
        detail = r.json().get("detail", "")
        assert "Invalid Google token" in detail or "audience" in detail.lower() or "issuer" in detail.lower()

    def test_google_verify_missing_credential(self, session):
        r = session.post(f"{API}/auth/google-verify", json={})
        # Pydantic validation → 422
        assert r.status_code == 422

    def test_google_verify_empty_credential(self, session):
        r = session.post(f"{API}/auth/google-verify", json={"credential": ""})
        # Empty string is accepted by pydantic (str), Google will reject → 400
        assert r.status_code in (400, 422)


# ---------- Existing /auth/google (code flow) still exists ----------
class TestGoogleCodeFlowStillExists:
    def test_google_code_endpoint_exists(self, session):
        r = session.post(f"{API}/auth/google", json={"code": "bogus_code_xyz", "redirect_uri": "https://example.com/cb"})
        assert r.status_code != 404, "Legacy /auth/google endpoint was removed"
        assert r.status_code != 500, f"Endpoint should not 500: {r.text}"
        # Expected 400 (invalid code exchange)
        assert r.status_code == 400


# ---------- OAuth config endpoint ----------
class TestOAuthConfig:
    def test_oauth_config_reports_google_enabled(self, session):
        r = session.get(f"{API}/auth/oauth-config")
        assert r.status_code == 200
        data = r.json()
        assert data["google"]["enabled"] is True
        assert data["google"]["client_id"]  # non-empty
