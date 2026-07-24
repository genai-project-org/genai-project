"""Iteration 9 P2 tests — Code Builder (create/list/get/preview/save/refine/share/delete/github),
Adzuna live-source validation, and Data Lake events for builder_*."""
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

# Cost budget: create=15, refine=8, share=0 → 23 credits total
UNIQUE_PROMPT = f"Build a simple TODO list app with add/remove/complete — test-{uuid.uuid4().hex[:6]}"


# --- Fixtures ---
@pytest.fixture(scope="session")
def mongo_db():
    client = MongoClient(MONGO_URL)
    yield client[DB_NAME]
    client.close()


@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    assert r.status_code == 200, f"Admin login failed: {r.status_code} {r.text[:300]}"
    data = r.json()
    return {
        "access": data["tokens"]["access_token"],
        "user_id": data["user"]["id"],
    }


@pytest.fixture(scope="session")
def auth_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token['access']}"}


@pytest.fixture(scope="session")
def project_id_holder():
    """Shared holder so tests within the class can chain."""
    return {"id": None}


# --- 1. Regression: auth ---
class TestAuthRegression:
    def test_admin_login(self, admin_token):
        assert admin_token["access"] and admin_token["user_id"]

    def test_me(self, auth_headers):
        r = requests.get(f"{API}/auth/me", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        assert r.json()["email"] == ADMIN_EMAIL


# --- 2. Builder: Create + cache behaviour ---
class TestBuilderCreate:
    def test_create_project_fresh(self, auth_headers, project_id_holder, mongo_db, admin_token):
        # Ensure fresh cache for this unique prompt
        import hashlib
        key = hashlib.sha256(f"{admin_token['user_id']}::{UNIQUE_PROMPT.strip().lower()}".encode()).hexdigest()
        mongo_db.builder_cache.delete_one({"_id": key})

        r = requests.post(f"{API}/builder/projects",
                          json={"prompt": UNIQUE_PROMPT},
                          headers=auth_headers, timeout=180)
        assert r.status_code == 200, f"Create failed: {r.status_code} {r.text[:500]}"
        j = r.json()
        assert j["cached"] is False
        assert j["credits_used"] == 15
        proj = j["project"]
        assert "id" in proj and proj["id"]
        assert "name" in proj and proj["name"]
        assert isinstance(proj["files"], list) and len(proj["files"]) >= 1
        # At least one file with .html or .js path
        exts = [f["path"].lower() for f in proj["files"]]
        assert any(p.endswith(".html") or p.endswith(".js") for p in exts), f"No .html/.js in {exts}"
        project_id_holder["id"] = proj["id"]

    def test_create_project_cached(self, auth_headers, project_id_holder):
        # Second identical call → cached=True, credits_used=0
        r = requests.post(f"{API}/builder/projects",
                          json={"prompt": UNIQUE_PROMPT},
                          headers=auth_headers, timeout=60)
        assert r.status_code == 200, r.text[:400]
        j = r.json()
        assert j["cached"] is True
        assert j["credits_used"] == 0

    def test_create_prompt_too_short_rejected(self, auth_headers):
        r = requests.post(f"{API}/builder/projects",
                          json={"prompt": "hi"},
                          headers=auth_headers, timeout=15)
        assert r.status_code == 422


# --- 3. Builder: List + Get ---
class TestBuilderListGet:
    def test_list_excludes_files(self, auth_headers, project_id_holder):
        r = requests.get(f"{API}/builder/projects", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert "items" in j and isinstance(j["items"], list)
        assert len(j["items"]) >= 1
        for it in j["items"]:
            assert "files" not in it, "files should be excluded on list view"
            assert "id" in it and "name" in it and "updated_at" in it
        # Verify our project is in the list
        assert any(it["id"] == project_id_holder["id"] for it in j["items"])

    def test_get_returns_full_project(self, auth_headers, project_id_holder):
        pid = project_id_holder["id"]
        r = requests.get(f"{API}/builder/projects/{pid}", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert j["id"] == pid
        assert isinstance(j["files"], list) and len(j["files"]) >= 1

    def test_get_404_for_random(self, auth_headers):
        r = requests.get(f"{API}/builder/projects/507f1f77bcf86cd799439011",
                         headers=auth_headers, timeout=15)
        assert r.status_code == 404


# --- 4. Builder: Preview composition ---
class TestBuilderPreview:
    def test_preview_returns_composed_html(self, auth_headers, project_id_holder):
        pid = project_id_holder["id"]
        r = requests.get(f"{API}/builder/projects/{pid}/preview",
                         headers=auth_headers, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert "html" in j
        html = j["html"].lstrip().lower()
        assert html.startswith("<!doctype") or html.startswith("<html"), f"HTML preview shape wrong: {html[:80]}"

    def test_preview_does_not_inline_external_urls(self, auth_headers, project_id_holder):
        """External https:// script/link tags should NOT be inlined (kept as-is)."""
        pid = project_id_holder["id"]
        # Save a project with a known external cdn tag + a sibling script that MUST be inlined
        payload = {"files": [
            {"path": "index.html", "language": "html",
             "content": "<!DOCTYPE html><html><head><script src=\"https://cdn.tailwindcss.com\"></script><link rel=\"stylesheet\" href=\"style.css\"><script src=\"app.js\"></script></head><body>hi</body></html>"},
            {"path": "style.css", "language": "css", "content": "body{color:red}"},
            {"path": "app.js", "language": "javascript", "content": "console.log('hello-inline')"},
        ]}
        s = requests.patch(f"{API}/builder/projects/{pid}/files", json=payload, headers=auth_headers, timeout=15)
        assert s.status_code == 200
        r = requests.get(f"{API}/builder/projects/{pid}/preview", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        html = r.json()["html"]
        # External URL preserved (still a src=https://cdn.tailwindcss.com reference)
        assert "https://cdn.tailwindcss.com" in html, "External CDN link should be preserved as-is"
        assert "<script src=\"https://cdn.tailwindcss.com\"" in html or "src='https://cdn.tailwindcss.com'" in html
        # Sibling app.js content INLINED
        assert "console.log('hello-inline')" in html, "Sibling script content should be inlined"
        # Sibling style.css INLINED
        assert "body{color:red}" in html, "Sibling stylesheet content should be inlined"
        # style.css link tag should NOT still reference the file
        assert 'href="style.css"' not in html and "href='style.css'" not in html


# --- 5. Builder: Save files (free) ---
class TestBuilderSaveFiles:
    def test_save_files_no_credits(self, auth_headers, project_id_holder):
        pid = project_id_holder["id"]
        payload = {"files": [
            {"path": "index.html", "language": "html",
             "content": "<!DOCTYPE html><html><body><h1>Manual edit token abc123xyz</h1></body></html>"},
        ]}
        r = requests.patch(f"{API}/builder/projects/{pid}/files", json=payload,
                           headers=auth_headers, timeout=15)
        assert r.status_code == 200
        j = r.json()
        assert j["ok"] is True
        assert j["files"][0]["path"] == "index.html"
        # Verify persistence via GET
        g = requests.get(f"{API}/builder/projects/{pid}", headers=auth_headers, timeout=15)
        assert g.status_code == 200
        content = g.json()["files"][0]["content"]
        assert "abc123xyz" in content


# --- 6. Builder: Refine (8 credits) ---
class TestBuilderRefine:
    def test_refine_adds_footer(self, auth_headers, project_id_holder):
        pid = project_id_holder["id"]
        instr = "Add a footer that says Built with IEMA.ai"
        r = requests.post(f"{API}/builder/projects/{pid}/refine",
                          json={"instruction": instr},
                          headers=auth_headers, timeout=180)
        assert r.status_code == 200, f"Refine failed: {r.status_code} {r.text[:500]}"
        j = r.json()
        assert j["credits_used"] == 8
        assert isinstance(j["files"], list) and len(j["files"]) >= 1
        # Look for footer text in some file's content (prefer index.html)
        combined = " ".join(f.get("content", "") for f in j["files"])
        assert "IEMA.ai" in combined or "IEMA" in combined, f"Refined project should mention IEMA.ai/footer text"


# --- 7. Builder: Share (S3 signed URL) ---
class TestBuilderShare:
    def test_share_returns_valid_signed_url(self, auth_headers, project_id_holder, mongo_db):
        pid = project_id_holder["id"]
        r = requests.post(f"{API}/builder/projects/{pid}/share",
                          headers=auth_headers, timeout=60)
        assert r.status_code == 200, f"Share failed: {r.status_code} {r.text[:400]}"
        j = r.json()
        url = j.get("share_url")
        assert url and url.startswith("http")
        # Verify signed URL reachable and returns HTML
        head = requests.get(url, timeout=30)
        assert head.status_code == 200, f"Signed URL not 200: {head.status_code} {head.text[:200]}"
        assert "<html" in head.text.lower() or "<!doctype" in head.text.lower()

        # Second call should reuse same S3 key
        from bson import ObjectId
        doc1 = mongo_db.builder_projects.find_one({"_id": ObjectId(pid)}, {"share_key": 1})
        key1 = doc1.get("share_key")
        assert key1

        r2 = requests.post(f"{API}/builder/projects/{pid}/share",
                           headers=auth_headers, timeout=60)
        assert r2.status_code == 200
        doc2 = mongo_db.builder_projects.find_one({"_id": ObjectId(pid)}, {"share_key": 1})
        assert doc2.get("share_key") == key1, "Second share call should reuse same S3 key"
        # New URL should still be a valid signed URL
        url2 = r2.json()["share_url"]
        assert url2.startswith("http")


# --- 8. Builder: GitHub error paths (no real PAT) ---
class TestBuilderGithub:
    def test_github_status_starts_unconnected(self, auth_headers, mongo_db, admin_token):
        # Defensive: clear github_pat for admin so test is deterministic
        from bson import ObjectId
        mongo_db.users.update_one({"_id": ObjectId(admin_token["user_id"])}, {"$unset": {"github_pat": ""}})
        r = requests.get(f"{API}/builder/github/status", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        assert r.json()["connected"] is False

    def test_github_push_no_pat_saved_returns_400(self, auth_headers, project_id_holder):
        pid = project_id_holder["id"]
        r = requests.post(f"{API}/builder/projects/{pid}/github/push",
                          json={"repo": "some/repo"},  # no pat
                          headers=auth_headers, timeout=30)
        assert r.status_code == 400
        # Accept either detail keyword
        assert "PAT" in r.text or "pat" in r.text

    def test_github_push_bad_repo_shape_returns_400(self, auth_headers, project_id_holder):
        pid = project_id_holder["id"]
        r = requests.post(f"{API}/builder/projects/{pid}/github/push",
                          json={"pat": "ghp_garbage_token_1234567890", "repo": "invalidrepo"},
                          headers=auth_headers, timeout=30)
        assert r.status_code == 400
        assert "owner/repo" in r.text

    def test_github_push_bad_pat_does_not_500(self, auth_headers, project_id_holder):
        """With garbage PAT + repo, endpoint should NOT 500 — should return 200 with errors[]."""
        pid = project_id_holder["id"]
        r = requests.post(f"{API}/builder/projects/{pid}/github/push",
                          json={"pat": "ghp_garbage_token_1234567890",
                                "repo": "nonexistent/repo123abc",
                                "save_pat": False},
                          headers=auth_headers, timeout=60)
        # Must NOT 500. Accept 200 with errors OR 400 per spec fallback.
        assert r.status_code in (200, 400, 401, 403, 404), f"Unexpected {r.status_code}: {r.text[:300]}"
        if r.status_code == 200:
            j = r.json()
            assert "errors" in j and isinstance(j["errors"], list)
            assert len(j["errors"]) >= 1 or len(j.get("pushed", [])) == 0

    def test_github_status_after_save_pat(self, auth_headers, project_id_holder, mongo_db, admin_token):
        """Push with save_pat=true + valid-shape repo should persist encrypted PAT; then status=connected."""
        pid = project_id_holder["id"]
        # This will fail auth but save_pat should still store the PAT (per builder_routes code: save_pat runs before validation of repo? Let's check)
        # In builder_routes: save_pat is applied after resolving 'pat' but BEFORE repo check. So garbage PAT + bad repo will still save.
        r = requests.post(f"{API}/builder/projects/{pid}/github/push",
                          json={"pat": "ghp_garbage_test_pat_ZZZ", "repo": "foo/bar", "save_pat": True},
                          headers=auth_headers, timeout=60)
        # Don't care about status of push itself; just that PAT was saved
        s = requests.get(f"{API}/builder/github/status", headers=auth_headers, timeout=15)
        assert s.status_code == 200
        assert s.json()["connected"] is True

        # Cleanup: disconnect
        d = requests.delete(f"{API}/builder/github/disconnect", headers=auth_headers, timeout=15)
        assert d.status_code == 200
        s2 = requests.get(f"{API}/builder/github/status", headers=auth_headers, timeout=15)
        assert s2.json()["connected"] is False


# --- 9. Data lake — builder_* events logged ---
class TestBuilderDataLake:
    def test_builder_create_event_logged(self, admin_token, mongo_db):
        time.sleep(0.5)
        doc = mongo_db.events.find_one(
            {"event_type": "builder_create", "user_id": admin_token["user_id"]},
            sort=[("created_at", -1)],
        )
        assert doc is not None, "No builder_create event"
        assert "name" in doc["payload"]
        assert "files" in doc["payload"]

    def test_builder_refine_event_logged(self, admin_token, mongo_db):
        doc = mongo_db.events.find_one(
            {"event_type": "builder_refine", "user_id": admin_token["user_id"]},
            sort=[("created_at", -1)],
        )
        assert doc is not None, "No builder_refine event"
        assert "project_id" in doc["payload"]

    def test_builder_share_event_logged(self, admin_token, mongo_db):
        doc = mongo_db.events.find_one(
            {"event_type": "builder_share", "user_id": admin_token["user_id"]},
            sort=[("created_at", -1)],
        )
        assert doc is not None, "No builder_share event"


# --- 10. Adzuna LIVE ---
class TestAdzunaLive:
    def test_jobs_live_adzuna(self, auth_headers, mongo_db):
        # Ensure fresh cache
        mongo_db.job_cache.delete_many({})
        r = requests.post(f"{API}/career/jobs",
                          json={"query": "python developer", "location": "Bengaluru"},
                          headers=auth_headers, timeout=45)
        assert r.status_code == 200, f"Jobs failed: {r.text[:300]}"
        j = r.json()
        assert j["source"] == "adzuna", f"Expected source='adzuna', got '{j.get('source')}'"
        assert j["count"] > 10, f"Expected count>10, got {j['count']}"
        assert len(j["results"]) >= 1
        first = j["results"][0]
        MOCK_COMPANIES = {"Zerodha", "Razorpay", "CRED", "Swiggy", "Freshworks"}
        assert first.get("company") not in MOCK_COMPANIES, \
            f"Company '{first.get('company')}' looks like mock data"
        # Basic field validation
        assert first.get("title")
        assert first.get("url")


# --- 11. Regression from prior iterations ---
class TestPriorRegression:
    def test_studio_summarize_still_works(self, auth_headers):
        r = requests.post(f"{API}/studio/summarize",
                          json={"text": "This is a short piece of text that describes the general state of AI in 2026. Many advances have been made.",
                                "style": "default"},
                          headers=auth_headers, timeout=60)
        assert r.status_code == 200, f"Summarize regression failed: {r.text[:300]}"
        assert "summary" in r.json()

    def test_career_learning_path_still_works(self, auth_headers, mongo_db):
        role = f"TEST_Iter9_{uuid.uuid4().hex[:6]}"
        r = requests.post(f"{API}/career/learning-path",
                          json={"role": role, "skills": ["python", "sql"]},
                          headers=auth_headers, timeout=60)
        assert r.status_code == 200, f"LP regression failed: {r.text[:300]}"
        j = r.json()
        assert "roadmap_markdown" in j and len(j["roadmap_markdown"]) > 50


# --- 12. Builder: Delete (LAST — cleans up test project) ---
class TestBuilderDelete:
    def test_delete_project_and_verify_gone(self, auth_headers, project_id_holder):
        pid = project_id_holder["id"]
        r = requests.delete(f"{API}/builder/projects/{pid}", headers=auth_headers, timeout=15)
        assert r.status_code == 200
        g = requests.get(f"{API}/builder/projects/{pid}", headers=auth_headers, timeout=15)
        assert g.status_code == 404
