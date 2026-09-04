"""Iter5/Iter6 fix-verification tests:
1) CRITICAL: register + immediate login within same second must both succeed with distinct tokens
2) Back-to-back logins for same user in same second return distinct tokens (jti uniqueness)
3) Refresh flow returns new distinct access+refresh tokens on back-to-back calls
4) Light OAuth regressions:
   - /auth/microsoft-verify -> 400 for invalid id_token
   - /auth/apple -> 400 for invalid id_token
   - /auth/google-verify -> 400 for invalid credential
   - /auth/oauth-config -> google/microsoft/apple enabled, facebook disabled
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://iema-ai-platform.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def _tokens(resp_json):
    """Extract access/refresh tokens whether they're at top-level or under 'tokens' key."""
    if "tokens" in resp_json and isinstance(resp_json["tokens"], dict):
        return resp_json["tokens"]
    return resp_json


@pytest.fixture(scope="module")
def sess():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ------------- CRITICAL: register + immediate login same second -------------
class TestRegisterLoginSameSecond:
    def test_register_then_login_immediately_no_500(self, sess):
        email = f"TEST_iter5_{uuid.uuid4().hex[:8]}@example.com"
        password = "Test@12345"

        r_reg = sess.post(f"{API}/auth/register", json={
            "email": email,
            "password": password,
            "name": "Iter5 Verify",
        }, timeout=20)
        assert r_reg.status_code == 200, f"register failed: {r_reg.status_code} {r_reg.text}"
        reg_tokens = _tokens(r_reg.json())
        assert "access_token" in reg_tokens
        assert "refresh_token" in reg_tokens

        # Immediate login (no sleep)
        r_login = sess.post(f"{API}/auth/login", json={
            "email": email,
            "password": password,
        }, timeout=20)
        assert r_login.status_code == 200, f"login failed: {r_login.status_code} {r_login.text}"
        login_tokens = _tokens(r_login.json())
        assert "access_token" in login_tokens
        assert "refresh_token" in login_tokens

        # Distinct token strings (jti claim)
        assert reg_tokens["access_token"] != login_tokens["access_token"], "access_tokens are identical"
        assert reg_tokens["refresh_token"] != login_tokens["refresh_token"], "refresh_tokens are identical"

    def test_back_to_back_logins_same_second_distinct_tokens(self, sess):
        email = f"TEST_iter5_btb_{uuid.uuid4().hex[:8]}@example.com"
        password = "Test@12345"
        r_reg = sess.post(f"{API}/auth/register", json={
            "email": email, "password": password, "name": "BackToBack",
        }, timeout=20)
        assert r_reg.status_code == 200, r_reg.text

        r1 = sess.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
        r2 = sess.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=20)
        assert r1.status_code == 200, f"login#1: {r1.status_code} {r1.text}"
        assert r2.status_code == 200, f"login#2: {r2.status_code} {r2.text}"
        d1, d2 = _tokens(r1.json()), _tokens(r2.json())
        assert d1["access_token"] != d2["access_token"], "back-to-back access_tokens identical"
        assert d1["refresh_token"] != d2["refresh_token"], "back-to-back refresh_tokens identical"


# ------------- Refresh flow distinct tokens -------------
class TestRefreshFlow:
    def test_refresh_returns_distinct_tokens_back_to_back(self, sess):
        email = f"TEST_iter5_ref_{uuid.uuid4().hex[:8]}@example.com"
        password = "Test@12345"
        r_reg = sess.post(f"{API}/auth/register", json={
            "email": email, "password": password, "name": "Ref",
        }, timeout=20)
        assert r_reg.status_code == 200, r_reg.text
        refresh = _tokens(r_reg.json())["refresh_token"]

        r1 = sess.post(f"{API}/auth/refresh", json={"refresh_token": refresh}, timeout=20)
        assert r1.status_code == 200, f"refresh#1: {r1.status_code} {r1.text}"
        d1 = _tokens(r1.json())
        assert "access_token" in d1 and "refresh_token" in d1

        new_ref = d1.get("refresh_token", refresh)
        r2 = sess.post(f"{API}/auth/refresh", json={"refresh_token": new_ref}, timeout=20)
        if r2.status_code != 200:
            r2 = sess.post(f"{API}/auth/refresh", json={"refresh_token": refresh}, timeout=20)
        assert r2.status_code == 200, f"refresh#2: {r2.status_code} {r2.text}"
        d2 = _tokens(r2.json())

        assert d1["access_token"] != d2["access_token"], "refresh access_tokens identical"
        assert d1["refresh_token"] != d2["refresh_token"], "refresh refresh_tokens identical"


# ------------- OAuth regression -------------
class TestOAuthRegression:
    def test_oauth_config(self, sess):
        r = sess.get(f"{API}/auth/oauth-config", timeout=15)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["google"]["enabled"] is True
        assert d["microsoft"]["enabled"] is True
        assert d["apple"]["enabled"] is True
        assert d["facebook"]["enabled"] is False
        # client_ids present
        assert d["google"].get("client_id"), "google client_id missing"
        assert d["microsoft"].get("client_id"), "microsoft client_id missing"
        assert d["apple"].get("client_id"), "apple client_id missing"

    def test_microsoft_verify_invalid_returns_400(self, sess):
        r = sess.post(f"{API}/auth/microsoft-verify", json={"id_token": "not-a-token"}, timeout=15)
        assert r.status_code == 400, f"got {r.status_code}: {r.text}"

    def test_apple_invalid_returns_400(self, sess):
        r = sess.post(f"{API}/auth/apple", json={"id_token": "not-a-token"}, timeout=15)
        assert r.status_code == 400, f"got {r.status_code}: {r.text}"

    def test_google_verify_invalid_returns_400(self, sess):
        r = sess.post(f"{API}/auth/google-verify", json={"credential": "not-a-token"}, timeout=15)
        assert r.status_code == 400, f"got {r.status_code}: {r.text}"
