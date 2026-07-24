"""Iteration 10 Batch A backend tests — Counseling, KB retrieval, admin settings, template gallery."""
import os
import time
import uuid
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://iema-ai-platform.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "siddharth.bose@iemlabs.com"
ADMIN_PASSWORD = "Admin@12345"

# Unique suffix per test-run so KB cache always starts fresh
RUN = uuid.uuid4().hex[:8]


# ---------- Fixtures ----------
@pytest.fixture(scope="session")
def s():
    ses = requests.Session()
    ses.headers.update({"Content-Type": "application/json"})
    return ses


@pytest.fixture(scope="session")
def admin_token(s):
    r = s.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    body = r.json()
    return body.get("tokens", {}).get("access_token") or body.get("access_token")


@pytest.fixture(scope="session")
def admin_client(s, admin_token):
    ses = requests.Session()
    ses.headers.update({"Content-Type": "application/json", "Authorization": f"Bearer {admin_token}"})
    return ses


@pytest.fixture(scope="session")
def user_client(s):
    """Fresh non-admin user for admin-forbid tests."""
    email = f"testuser_{RUN}@example.com"
    password = "Test@1234"
    r = s.post(f"{API}/auth/register", json={"email": email, "password": password, "name": "Test User"})
    assert r.status_code in (200, 201), f"register failed: {r.status_code} {r.text}"
    body = r.json()
    token = body.get("tokens", {}).get("access_token") or body.get("access_token")
    if not token:
        # login instead
        r2 = s.post(f"{API}/auth/login", json={"email": email, "password": password})
        assert r2.status_code == 200
        b2 = r2.json()
        token = b2.get("tokens", {}).get("access_token") or b2.get("access_token")
    ses = requests.Session()
    ses.headers.update({"Content-Type": "application/json", "Authorization": f"Bearer {token}"})
    ses.email = email
    return ses


# ---------- Public templates ----------
class TestPublicTemplates:
    def test_list_templates_no_auth(self):
        r = requests.get(f"{API}/builder/templates")
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        items = data["items"]
        assert len(items) >= 6, f"expected 6 templates, got {len(items)}"
        slugs = {i["slug"] for i in items}
        for expected in ("todo", "pomodoro", "calculator", "portfolio", "landing", "weather"):
            assert expected in slugs, f"missing template: {expected}"
        for i in items:
            assert "name" in i and "description" in i and "order" in i and "slug" in i

    def test_pomodoro_preview_no_auth(self):
        r = requests.get(f"{API}/builder/templates/pomodoro/preview")
        assert r.status_code == 200
        data = r.json()
        assert "html" in data and "name" in data
        html = data["html"]
        assert "<script" in html.lower(), "preview must contain <script>"
        lower = html.lower()
        # Timer-like keywords
        assert any(k in lower for k in ("timer", "pomodoro", "25:00", "countdown", "setinterval", "settimeout")), \
            "pomodoro HTML should contain timer keywords"

    def test_use_template_requires_auth(self):
        r = requests.post(f"{API}/builder/templates/todo/use")
        assert r.status_code in (401, 403)

    def test_use_todo_template(self, admin_client):
        # Snapshot before
        r_before = admin_client.get(f"{API}/builder/projects")
        assert r_before.status_code == 200
        before_ids = {p["id"] for p in r_before.json().get("items", [])}

        r = admin_client.post(f"{API}/builder/templates/todo/use")
        assert r.status_code == 200, f"use template failed: {r.text}"
        data = r.json()
        assert "project" in data
        proj = data["project"]
        assert proj.get("name") == "Minimalist Todo"
        assert isinstance(proj.get("files"), list) and len(proj["files"]) > 0
        assert "id" in proj

        # verify it's now in the list
        r_after = admin_client.get(f"{API}/builder/projects")
        assert r_after.status_code == 200
        after_ids = {p["id"] for p in r_after.json().get("items", [])}
        assert proj["id"] in after_ids

        # cleanup — delete the just-created project
        admin_client.delete(f"{API}/builder/projects/{proj['id']}")


# ---------- Counseling ----------
UNIQUE_CAREER = f"How do I switch from frontend to full-stack engineering in 6 months (RUN-{RUN})?"
UNIQUE_PSYCH  = f"I feel overwhelmed after a job rejection today (RUN-{RUN}). What can I do tonight?"
UNIQUE_ACAD   = f"Best 90-day study plan for GATE CSE data-structures section (RUN-{RUN})?"


class TestCounseling:
    def test_career_llm_then_kb(self, admin_client):
        # First call — expect LLM
        r1 = admin_client.post(f"{API}/counseling", json={"mode": "career", "message": UNIQUE_CAREER})
        assert r1.status_code == 200, r1.text
        d1 = r1.json()
        assert d1["mode"] == "career"
        assert d1["source"] == "llm", f"expected source=llm, got {d1['source']}"
        assert d1["credits_used"] == 3
        assert "disclaimer" in d1 and isinstance(d1["disclaimer"], str) and len(d1["disclaimer"]) > 0
        assert len(d1["response"]) > 20

        # Second identical call — expect KB exact match
        r2 = admin_client.post(f"{API}/counseling", json={"mode": "career", "message": UNIQUE_CAREER})
        assert r2.status_code == 200, r2.text
        d2 = r2.json()
        assert d2["source"] == "kb", f"expected source=kb on 2nd call, got {d2['source']}"
        assert d2.get("match") == "exact"
        assert d2["credits_used"] == 0

    def test_psychology_disclaimer_has_icall(self, admin_client):
        r = admin_client.post(f"{API}/counseling", json={"mode": "psychology", "message": UNIQUE_PSYCH})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["mode"] == "psychology"
        assert "icall" in d["disclaimer"].lower() or "9152987821" in d["disclaimer"], \
            f"psychology disclaimer missing iCall/helpline: {d['disclaimer']}"
        # source should be llm (unique message)
        assert d["source"] in ("llm", "kb")

    def test_academic_mode(self, admin_client):
        r = admin_client.post(f"{API}/counseling", json={"mode": "academic", "message": UNIQUE_ACAD})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["mode"] == "academic"
        assert d["source"] in ("llm", "kb")
        assert len(d["response"]) > 20
        assert isinstance(d["disclaimer"], str)

    def test_invalid_mode(self, admin_client):
        r = admin_client.post(f"{API}/counseling", json={"mode": "foo", "message": "hello there test message"})
        assert r.status_code == 400


# ---------- Studio summarize KB ----------
class TestStudioSummarize:
    def test_llm_then_kb(self, admin_client):
        unique_text = (
            f"[RUN-{RUN}] The Indian tech ecosystem in 2026 has seen unprecedented growth in AI startups. "
            "Bengaluru remains the hub with over 400 active AI companies producing generative AI tooling, "
            "healthcare LLMs, and vernacular NLP products for tier-2 and tier-3 markets across India."
        )
        r1 = admin_client.post(f"{API}/studio/summarize", json={"text": unique_text, "style": "concise"})
        assert r1.status_code == 200, r1.text
        d1 = r1.json()
        assert "source" in d1
        assert d1["source"] == "llm"
        # 2 credits reflected somewhere — response either 'credits_used' or wallet drop
        # spec says 2 credits; we just verify source semantics here
        assert "summary" in d1 or "response" in d1 or "text" in d1

        r2 = admin_client.post(f"{API}/studio/summarize", json={"text": unique_text, "style": "concise"})
        assert r2.status_code == 200, r2.text
        d2 = r2.json()
        assert d2["source"] == "kb", f"expected kb, got {d2['source']}"
        if "score" in d2:
            assert isinstance(d2["score"], (int, float))
        if "credits_used" in d2:
            assert d2["credits_used"] == 0


# ---------- Career learning-path KB ----------
class TestCareerLearningPath:
    def test_llm_then_kb(self, admin_client):
        role = f"TEST_BatchA_{RUN}_DataEngineer"
        r1 = admin_client.post(f"{API}/career/learning-path", json={"role": role})
        assert r1.status_code == 200, r1.text
        d1 = r1.json()
        assert d1.get("source") == "llm"
        r2 = admin_client.post(f"{API}/career/learning-path", json={"role": role})
        assert r2.status_code == 200
        d2 = r2.json()
        assert d2.get("source") in ("kb", "cache")
        if "credits_used" in d2:
            assert d2["credits_used"] == 0


# ---------- Builder create KB ----------
class TestBuilderKB:
    def test_llm_then_kb(self, admin_client):
        prompt = f"Build a single-page HTML calculator that supports +-*/ and clears with C. RUN-{RUN} unique-tag {uuid.uuid4().hex[:6]}"
        r1 = admin_client.post(f"{API}/builder/projects", json={"prompt": prompt})
        assert r1.status_code == 200, r1.text
        d1 = r1.json()
        # first call — LLM path
        assert d1.get("cached") in (False, None) or d1.get("credits_used", 0) > 0
        p1_id = d1["project"]["id"]

        r2 = admin_client.post(f"{API}/builder/projects", json={"prompt": prompt})
        assert r2.status_code == 200
        d2 = r2.json()
        # Second call — expect cached true / credits 0
        assert d2.get("cached") is True or d2.get("credits_used", 15) == 0, \
            f"expected KB hit, got: {d2}"
        p2_id = d2["project"]["id"]

        # cleanup
        admin_client.delete(f"{API}/builder/projects/{p1_id}")
        admin_client.delete(f"{API}/builder/projects/{p2_id}")


# ---------- Admin routes ----------
class TestAdminEndpoints:
    def test_kb_stats(self, admin_client):
        r = admin_client.get(f"{API}/admin/kb/stats")
        assert r.status_code == 200, r.text
        d = r.json()
        assert "total_entries" in d and isinstance(d["total_entries"], int)
        assert "total_hits" in d and isinstance(d["total_hits"], int)
        assert "by_kind" in d and isinstance(d["by_kind"], dict)

    def test_get_settings(self, admin_client):
        r = admin_client.get(f"{API}/admin/settings")
        assert r.status_code == 200, r.text
        d = r.json()
        assert "settings" in d and "defaults" in d
        s = d["settings"]
        assert "kb_similarity_threshold" in s
        assert "kb_enabled" in s
        defs = d["defaults"]
        assert defs["kb_similarity_threshold"] == 0.85
        assert defs["kb_enabled"] is True

    def test_post_settings_valid_and_reset(self, admin_client):
        # Change threshold to 0.6
        r = admin_client.post(f"{API}/admin/settings", json={"key": "kb_similarity_threshold", "value": 0.6})
        assert r.status_code == 200, r.text
        # Round-trip
        r2 = admin_client.get(f"{API}/admin/settings")
        assert r2.status_code == 200
        assert abs(r2.json()["settings"]["kb_similarity_threshold"] - 0.6) < 1e-6
        # Reset to 0.85 (leave clean state)
        r3 = admin_client.post(f"{API}/admin/settings", json={"key": "kb_similarity_threshold", "value": 0.85})
        assert r3.status_code == 200
        r4 = admin_client.get(f"{API}/admin/settings")
        assert abs(r4.json()["settings"]["kb_similarity_threshold"] - 0.85) < 1e-6

    def test_post_settings_bad_key(self, admin_client):
        r = admin_client.post(f"{API}/admin/settings", json={"key": "totally_bogus_key", "value": 42})
        assert r.status_code == 400

    def test_post_settings_out_of_range(self, admin_client):
        r = admin_client.post(f"{API}/admin/settings", json={"key": "kb_similarity_threshold", "value": 1.7})
        assert r.status_code == 400

    def test_non_admin_forbidden_kb_stats(self, user_client):
        r = user_client.get(f"{API}/admin/kb/stats")
        assert r.status_code in (401, 403), f"non-admin got {r.status_code}"

    def test_non_admin_forbidden_settings(self, user_client):
        r = user_client.get(f"{API}/admin/settings")
        assert r.status_code in (401, 403)
        r2 = user_client.post(f"{API}/admin/settings", json={"key": "kb_similarity_threshold", "value": 0.7})
        assert r2.status_code in (401, 403)


# ---------- Regression ----------
class TestRegression:
    def test_auth_me(self, admin_client):
        r = admin_client.get(f"{API}/auth/me")
        assert r.status_code == 200
        assert r.json().get("email") == ADMIN_EMAIL

    def test_career_jobs_adzuna(self, admin_client):
        r = admin_client.post(f"{API}/career/jobs", json={"query": "python", "location": "India", "page": 1})
        assert r.status_code == 200, r.text
        d = r.json()
        # source should be adzuna if live keys work; accept either
        assert d.get("source") in ("adzuna", "cache") or "items" in d
