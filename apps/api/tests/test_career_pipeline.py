"""Tests for the Career Pipeline feature (Gmail scan → fit score + outreach draft).

Focus:
- Profile save/load round-trips.
- Gmail status defaults to disconnected for a fresh user.
- Pipeline list starts empty.
- Scan is gated behind both a saved profile and a Gmail connection (400s, not 500s).
- Status updates 404 for a nonexistent/foreign pipeline entry.

Does NOT exercise the real Gmail OAuth exchange or LLM scoring — those need a live
Google consent flow and a real inbox, which this suite has no way to fake. See
services/gmail_service.py's own `demo()` self-check for the email-parsing logic.
"""
import os
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://iema-ai-platform.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

RUN = uuid.uuid4().hex[:8]


@pytest.fixture(scope="module")
def user_client():
    """Fresh user, isolated per test run so pipeline/profile state starts empty."""
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    email = f"pipeline_test_{RUN}@example.com"
    password = "Test@12345"
    r = s.post(f"{API}/auth/register", json={"email": email, "password": password, "name": "Pipeline Test"})
    assert r.status_code in (200, 201), f"register failed: {r.status_code} {r.text}"
    token = r.json()["tokens"]["access_token"]
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s


class TestGmailStatus:
    def test_disconnected_by_default(self, user_client):
        r = user_client.get(f"{API}/career/gmail/status")
        assert r.status_code == 200, r.text
        assert r.json() == {"connected": False, "email": None}


class TestProfile:
    def test_empty_by_default(self, user_client):
        r = user_client.get(f"{API}/career/profile")
        assert r.status_code == 200, r.text
        assert r.json()["profile_text"] == ""

    def test_save_and_reload(self, user_client):
        text = "Senior backend engineer, Python, FastAPI, 5 years, remote India roles."
        r = user_client.post(f"{API}/career/profile", json={"profile_text": text})
        assert r.status_code == 200, r.text
        assert r.json()["profile_text"] == text

        r2 = user_client.get(f"{API}/career/profile")
        assert r2.json()["profile_text"] == text

    def test_too_short_is_rejected(self, user_client):
        r = user_client.post(f"{API}/career/profile", json={"profile_text": "short"})
        assert r.status_code == 422, r.text


class TestPipelineList:
    def test_starts_empty(self, user_client):
        r = user_client.get(f"{API}/career/pipeline")
        assert r.status_code == 200, r.text
        assert r.json() == {"items": []}


class TestScanGating:
    def test_scan_without_gmail_connected_is_400_not_500(self, user_client):
        # test_save_and_reload already saved a profile for this user, so this
        # isolates the Gmail-connection gate specifically.
        r = user_client.post(f"{API}/career/pipeline/scan")
        assert r.status_code == 400, r.text
        assert "gmail" in r.json()["detail"].lower()

    def test_scan_without_profile_is_400(self):
        s = requests.Session()
        s.headers.update({"Content-Type": "application/json"})
        email = f"pipeline_test_noprofile_{RUN}@example.com"
        r = s.post(f"{API}/auth/register", json={"email": email, "password": "Test@12345", "name": "No Profile"})
        assert r.status_code in (200, 201), r.text
        s.headers.update({"Authorization": f"Bearer {r.json()['tokens']['access_token']}"})

        r2 = s.post(f"{API}/career/pipeline/scan")
        assert r2.status_code == 400, r2.text
        assert "profile" in r2.json()["detail"].lower()


class TestPipelineStatusUpdate:
    def test_unknown_job_id_is_404(self, user_client):
        r = user_client.patch(f"{API}/career/pipeline/000000000000000000000000/status", json={"status": "contacted"})
        assert r.status_code == 404, r.text

    def test_invalid_status_is_422(self, user_client):
        r = user_client.patch(f"{API}/career/pipeline/000000000000000000000000/status", json={"status": "not_a_real_status"})
        assert r.status_code == 422, r.text

    def test_malformed_job_id_is_404_not_500(self, user_client):
        r = user_client.patch(f"{API}/career/pipeline/not-an-object-id/status", json={"status": "contacted"})
        assert r.status_code == 404, r.text
