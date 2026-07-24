"""Iteration 8 P0 tests: Data Lake middleware + AI Studio (summarize/image) + Career Intelligence."""
import os
import time
import uuid
import pytest
import requests
from pymongo import MongoClient

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://iema-ai-platform.preview.emergentagent.com').rstrip('/')
API = f"{BASE_URL}/api"

MONGO_URL = os.environ.get('MONGO_URL', 'mongodb://localhost:27017')
DB_NAME = os.environ.get('DB_NAME', 'iema_ai_v2')

ADMIN_EMAIL = "siddharth.bose@iemlabs.com"
ADMIN_PASSWORD = "Admin@12345"


# --- Fixtures ---
@pytest.fixture(scope="session")
def mongo_db():
    """Direct Mongo access for Data Lake events verification."""
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="session")
def admin_token():
    """Login as admin, return access token + user_id."""
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text[:300]}"
    data = r.json()
    return {
        "access": data["tokens"]["access_token"],
        "refresh": data["tokens"]["refresh_token"],
        "user_id": data["user"]["id"],
    }


@pytest.fixture(scope="session")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token['access']}"}


# --- 1. Regression: auth ---
class TestAuthRegression:
    def test_admin_login(self, admin_token):
        assert admin_token["access"]
        assert admin_token["user_id"]

    def test_register_new_user_still_works(self):
        email = f"TEST_iter8_{uuid.uuid4().hex[:8]}@example.com"
        r = requests.post(f"{API}/auth/register", json={
            "email": email, "name": "Iter8 Test", "password": "Test@12345"
        }, timeout=30)
        assert r.status_code == 200, f"Register failed: {r.status_code} {r.text[:300]}"
        j = r.json()
        assert j["user"]["email"] == email.lower()
        assert j["tokens"]["access_token"]

    def test_me_endpoint(self, auth_headers):
        r = requests.get(f"{API}/auth/me", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        assert r.json()["email"] == ADMIN_EMAIL


# --- 2. AI Studio: Summarize (default, eli5, executive) ---
class TestStudioSummarize:
    LONG_TEXT = (
        "OpenAI released GPT-Image-1 in October 2024, a new image generation model available via the API. "
        "It supports text-to-image with quality tiers low, medium, high. Pricing is roughly $0.011 per low-quality image, "
        "$0.042 for medium and $0.167 for high. The model can also do inpainting and image editing. "
        "Anthropic Claude Haiku 4.5, released in late 2025, is priced at $1/M input tokens and $5/M output tokens, "
        "outperforming Claude 3.5 Sonnet on many reasoning benchmarks. India tech job market grew 12% YoY in Q3 2025."
    )

    def test_summarize_default_style(self, auth_headers):
        r = requests.post(f"{API}/studio/summarize",
                          json={"text": self.LONG_TEXT, "style": "default"},
                          headers=auth_headers, timeout=90)
        assert r.status_code == 200, f"Summarize default failed: {r.status_code} {r.text[:300]}"
        j = r.json()
        assert "summary" in j and len(j["summary"]) > 20
        assert j["credits_used"] == 2
        assert isinstance(j["balance"], (int, float))

    def test_summarize_eli5(self, auth_headers):
        r = requests.post(f"{API}/studio/summarize",
                          json={"text": self.LONG_TEXT, "style": "eli5"},
                          headers=auth_headers, timeout=90)
        assert r.status_code == 200, f"Summarize eli5 failed: {r.text[:300]}"
        j = r.json()
        assert len(j["summary"]) > 20
        assert j["credits_used"] == 2

    def test_summarize_executive(self, auth_headers):
        r = requests.post(f"{API}/studio/summarize",
                          json={"text": self.LONG_TEXT, "style": "executive"},
                          headers=auth_headers, timeout=90)
        assert r.status_code == 200, f"Summarize exec failed: {r.text[:300]}"
        j = r.json()
        assert len(j["summary"]) > 20
        assert j["credits_used"] == 2

    def test_summarize_rejects_short_text(self, auth_headers):
        r = requests.post(f"{API}/studio/summarize",
                          json={"text": "too short", "style": "default"},
                          headers=auth_headers, timeout=15)
        # pydantic min_length=20 → 422
        assert r.status_code == 422

    def test_summarize_requires_auth(self):
        r = requests.post(f"{API}/studio/summarize",
                          json={"text": self.LONG_TEXT, "style": "default"}, timeout=15)
        assert r.status_code in (401, 403)


# --- 3. AI Studio: Image (ONE call only across whole suite) ---
class TestStudioImage:
    def test_image_gen_low_quality_single(self, auth_headers):
        """Only image-gen call in the entire test suite (10 credits)."""
        r = requests.post(f"{API}/studio/image",
                          json={"prompt": "A minimalist mountain landscape at sunrise, flat design",
                                "quality": "low", "n": 1},
                          headers=auth_headers, timeout=180)
        # If S3 not configured or emergent image gen fails, main agent should investigate
        assert r.status_code == 200, f"Image gen failed: {r.status_code} {r.text[:500]}"
        j = r.json()
        assert "images" in j and isinstance(j["images"], list) and len(j["images"]) == 1
        img = j["images"][0]
        assert "url" in img and img["url"].startswith("http")
        assert "key" in img
        assert j["credits_used"] == 10
        # Verify URL is reachable
        head = requests.get(img["url"], timeout=30, stream=True)
        assert head.status_code == 200, f"Image URL not HTTP 200: {head.status_code}"

    def test_image_gen_requires_auth(self):
        r = requests.post(f"{API}/studio/image",
                          json={"prompt": "test", "quality": "low", "n": 1}, timeout=15)
        assert r.status_code in (401, 403)


# --- 4. Career: Jobs (Adzuna keys unset → mock fallback) ---
class TestCareerJobs:
    def test_jobs_returns_mock(self, auth_headers):
        r = requests.post(f"{API}/career/jobs",
                          json={"query": f"python-{uuid.uuid4().hex[:6]}", "location": "Bengaluru"},
                          headers=auth_headers, timeout=30)
        assert r.status_code == 200, f"Jobs search failed: {r.text[:300]}"
        j = r.json()
        assert j["source"] == "mock", f"Expected source='mock', got {j.get('source')}"
        assert j["count"] == 5
        assert len(j["results"]) == 5
        first = j["results"][0]
        for field in ("id", "title", "company", "location", "salary_min", "salary_max"):
            assert field in first, f"Missing field {field} in job result"

    def test_jobs_requires_auth(self):
        r = requests.post(f"{API}/career/jobs",
                          json={"query": "python", "location": "Bengaluru"}, timeout=15)
        assert r.status_code in (401, 403)


# --- 5. Career: Learning path (cache behaviour) ---
class TestLearningPath:
    def test_learning_path_first_call_generates(self, auth_headers, mongo_db):
        # Use a unique role/skills combo to force cache miss on first call
        role = f"TEST_Iter8_Backend_{uuid.uuid4().hex[:8]}"
        skills = ["python", "fastapi"]
        # Wipe any pre-existing entry (defensive)
        r1 = requests.post(f"{API}/career/learning-path",
                           json={"role": role, "skills": skills},
                           headers=auth_headers, timeout=90)
        assert r1.status_code == 200, f"LP first failed: {r1.status_code} {r1.text[:400]}"
        j1 = r1.json()
        assert j1["cached"] is False
        assert j1["credits_used"] == 5
        md = j1.get("roadmap_markdown", "")
        assert len(md) > 100
        # Section headers check
        assert ("Skill Gap" in md) or ("90-Day" in md) or ("90 Day" in md), f"Missing expected headers in markdown: {md[:400]}"

        # Second identical call → cached=True, credits_used=0
        r2 = requests.post(f"{API}/career/learning-path",
                           json={"role": role, "skills": skills},
                           headers=auth_headers, timeout=30)
        assert r2.status_code == 200
        j2 = r2.json()
        assert j2["cached"] is True, f"Expected cached=True on second call, got {j2}"
        assert j2.get("credits_used", 0) == 0

    def test_learning_path_requires_auth(self):
        r = requests.post(f"{API}/career/learning-path",
                          json={"role": "Backend", "skills": []}, timeout=15)
        assert r.status_code in (401, 403)


# --- 6. Data Lake middleware — events collection ---
class TestDataLake:
    def test_api_call_event_logged(self, auth_headers, admin_token, mongo_db):
        # Trigger a known logged endpoint
        r = requests.get(f"{API}/auth/me", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        time.sleep(1.0)  # let async insert flush
        doc = mongo_db["events"].find_one(
            {"event_type": "api_call", "user_id": admin_token["user_id"], "payload.path": "/api/auth/me"},
            sort=[("created_at", -1)],
        )
        assert doc is not None, "No api_call event logged for /api/auth/me"
        assert doc["payload"]["method"] == "GET"
        assert doc["meta"]["status"] == 200
        assert doc["user_id"] == admin_token["user_id"]

    def test_studio_summarize_event_logged(self, admin_token, mongo_db):
        # Verify studio_summarize event exists (from earlier tests)
        doc = mongo_db["events"].find_one(
            {"event_type": "studio_summarize", "user_id": admin_token["user_id"]},
            sort=[("created_at", -1)],
        )
        assert doc is not None, "No studio_summarize event logged"
        assert "style" in doc["payload"]
        assert "input_chars" in doc["payload"]

    def test_studio_image_event_logged(self, admin_token, mongo_db):
        doc = mongo_db["events"].find_one(
            {"event_type": "studio_image", "user_id": admin_token["user_id"]},
            sort=[("created_at", -1)],
        )
        assert doc is not None, "No studio_image event logged"
        assert doc["payload"]["quality"] == "low"
        assert doc["payload"]["n"] == 1

    def test_career_job_search_event_logged(self, admin_token, mongo_db):
        doc = mongo_db["events"].find_one(
            {"event_type": "career_job_search", "user_id": admin_token["user_id"]},
            sort=[("created_at", -1)],
        )
        assert doc is not None, "No career_job_search event logged"
        assert doc["payload"]["source"] == "mock"

    def test_career_learning_path_event_logged(self, admin_token, mongo_db):
        doc = mongo_db["events"].find_one(
            {"event_type": "career_learning_path", "user_id": admin_token["user_id"]},
            sort=[("created_at", -1)],
        )
        assert doc is not None, "No career_learning_path event logged"
        assert "role" in doc["payload"]

    def test_health_endpoint_not_logged(self, mongo_db):
        """SKIP_PATHS should exclude /api/health from events."""
        before = mongo_db["events"].count_documents({"payload.path": "/api/health"})
        r = requests.get(f"{API}/health", timeout=10)
        assert r.status_code == 200
        time.sleep(0.5)
        after = mongo_db["events"].count_documents({"payload.path": "/api/health"})
        assert after == before, f"Health endpoint should be skipped, count changed {before}->{after}"


# --- 7. Chat regression (small message) ---
class TestChatRegression:
    def test_chat_conversations_list(self, auth_headers):
        r = requests.get(f"{API}/chat/conversations", headers=auth_headers, timeout=15)
        assert r.status_code == 200, f"Chat convos failed: {r.status_code} {r.text[:200]}"
        body = r.json()
        # Endpoint returns {"items": [...]} envelope
        assert isinstance(body, dict) and "items" in body and isinstance(body["items"], list)
