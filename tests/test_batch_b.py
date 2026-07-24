"""Batch B backend tests — pricing engine, plans, analytics, queries,
user details, wallet window, KB engine, multi-social linking, capability manifest,
and spend() flow regression.
"""
import os
import time
import uuid
import pytest
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split("\n")[0]).rstrip("/")
API = f"{BASE_URL}/api"

ADMIN_EMAIL = "siddharth.bose@iemlabs.com"
ADMIN_PASSWORD = "Admin@12345"


# ---------- Fixtures ----------
@pytest.fixture(scope="session")
def admin_token():
    r = requests.post(f"{API}/auth/login",
                      json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert r.status_code == 200, f"admin login failed: {r.status_code} {r.text}"
    body = r.json()
    return body["tokens"]["access_token"]


@pytest.fixture(scope="session")
def admin_headers(admin_token):
    return {"Authorization": f"Bearer {admin_token}"}


@pytest.fixture(scope="session")
def admin_id(admin_headers):
    r = requests.get(f"{API}/auth/me", headers=admin_headers)
    assert r.status_code == 200
    return r.json()["id"]


@pytest.fixture(scope="session")
def new_user_headers():
    """Fresh disposable non-admin user."""
    email = f"testuser_batchB_{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/auth/register",
                      json={"email": email, "name": "BatchB Tester", "password": "Test@1234"})
    assert r.status_code == 200, f"register failed: {r.text}"
    tok = r.json()["tokens"]["access_token"]
    return {"Authorization": f"Bearer {tok}"}


# ============ Pricing Engine ============
class TestPricing:
    def test_list_pricing_admin(self, admin_headers):
        r = requests.get(f"{API}/admin/pricing", headers=admin_headers)
        assert r.status_code == 200
        items = r.json()["items"]
        assert isinstance(items, list)
        assert len(items) >= 13
        keys = {i["service_key"] for i in items}
        for k in ["chat_message", "studio_summarize", "counseling_career",
                  "builder_create", "builder_refine", "career_learning_path"]:
            assert k in keys

    def test_patch_pricing_persists(self, admin_headers):
        # set to 4
        r = requests.patch(f"{API}/admin/pricing/studio_summarize",
                           headers=admin_headers, json={"credit_cost": 4})
        assert r.status_code == 200, r.text
        # verify persistence
        r2 = requests.get(f"{API}/admin/pricing", headers=admin_headers)
        assert r2.status_code == 200
        item = next((i for i in r2.json()["items"] if i["service_key"] == "studio_summarize"), None)
        assert item is not None
        assert float(item["credit_cost"]) == 4.0
        # reset
        r3 = requests.patch(f"{API}/admin/pricing/studio_summarize",
                            headers=admin_headers, json={"credit_cost": 2})
        assert r3.status_code == 200

    def test_patch_pricing_reject_out_of_range(self, admin_headers):
        r = requests.patch(f"{API}/admin/pricing/studio_summarize",
                           headers=admin_headers, json={"credit_cost": -1})
        assert r.status_code == 400
        r2 = requests.patch(f"{API}/admin/pricing/studio_summarize",
                            headers=admin_headers, json={"credit_cost": 10001})
        assert r2.status_code == 400

    def test_pricing_non_admin_forbidden(self, new_user_headers):
        r = requests.get(f"{API}/admin/pricing", headers=new_user_headers)
        assert r.status_code == 403


# ============ Plans ============
class TestPlans:
    def test_list_plans(self, admin_headers):
        r = requests.get(f"{API}/admin/plans", headers=admin_headers)
        assert r.status_code == 200
        items = r.json()["items"]
        plan_ids = {p["plan_id"] for p in items}
        assert {"free", "pro", "team"}.issubset(plan_ids)

    def test_patch_plan_persists(self, admin_headers):
        r = requests.patch(f"{API}/admin/plans/pro",
                           headers=admin_headers, json={"monthly_credits": 600, "window_hours": 6})
        assert r.status_code == 200
        # verify
        r2 = requests.get(f"{API}/admin/plans", headers=admin_headers)
        pro = next(p for p in r2.json()["items"] if p["plan_id"] == "pro")
        assert float(pro["monthly_credits"]) == 600
        assert int(pro["window_hours"]) == 6
        # reset
        rr = requests.patch(f"{API}/admin/plans/pro", headers=admin_headers,
                            json={"monthly_credits": 500, "window_hours": 5})
        assert rr.status_code == 200


# ============ Analytics ============
class TestAnalytics:
    def test_provider_usage(self, admin_headers):
        r = requests.get(f"{API}/admin/analytics/provider-usage?period=7d", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert "items" in body
        providers = {i["provider"] for i in body["items"]}
        # We've made anthropic calls in prior iterations
        assert "anthropic" in providers, f"expected anthropic in {providers}"

    def test_timeseries(self, admin_headers):
        r = requests.get(f"{API}/admin/analytics/timeseries?period=7d", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert body["granularity"] in ("hour", "day")
        assert isinstance(body["items"], list)

    def test_finance(self, admin_headers):
        r = requests.get(f"{API}/admin/analytics/finance?period=30d", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        for k in ("expense_usd", "income_credits", "income_inr_estimate",
                  "income_usd_estimate", "margin_usd_estimate"):
            assert k in body, f"missing {k}"


# ============ Queries ============
class TestQueries:
    def test_queries_search(self, admin_headers):
        r = requests.get(f"{API}/admin/queries?q=python&kind=counseling_career",
                         headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert "items" in body and "total" in body

    def test_queries_non_admin(self, new_user_headers):
        r = requests.get(f"{API}/admin/queries", headers=new_user_headers)
        assert r.status_code == 403


# ============ User Details ============
class TestUserDetails:
    def test_admin_user_details(self, admin_headers, admin_id):
        r = requests.get(f"{API}/admin/users/{admin_id}/details", headers=admin_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body is not None, "response body is null (missing return in endpoint)"
        assert "user" in body and "wallet" in body and "top_services" in body and "recent_queries" in body
        assert body["user"]["id"] == admin_id

    def test_invalid_user_id(self, admin_headers):
        r = requests.get(f"{API}/admin/users/invalid_id_xyz/details", headers=admin_headers)
        assert r.status_code == 400

    def test_missing_user(self, admin_headers):
        # valid ObjectId format but doesn't exist
        r = requests.get(f"{API}/admin/users/507f1f77bcf86cd799439011/details", headers=admin_headers)
        assert r.status_code == 404


# ============ Wallet Window ============
class TestWallet:
    def test_wallet_window(self, admin_headers):
        r = requests.get(f"{API}/wallet/window", headers=admin_headers)
        assert r.status_code == 200, r.text
        body = r.json()
        assert "plan" in body and "window" in body
        w = body["window"]
        assert w["used"] <= w["cap"]
        # resets_at is ISO
        assert isinstance(w["resets_at"], str) and "T" in w["resets_at"]

    def test_free_plan_cap(self, new_user_headers):
        r = requests.get(f"{API}/wallet/window", headers=new_user_headers)
        assert r.status_code == 200
        w = r.json()["window"]
        assert float(w["cap"]) == 15.0
        assert int(w["window_hours"]) == 4


# ============ KB Engine ============
class TestKBEngine:
    def test_engine_status(self, admin_headers):
        r = requests.get(f"{API}/admin/kb/engine/status", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert body.get("running") is True
        assert "interval_hours" in body

    def test_engine_run(self, admin_headers):
        r = requests.post(f"{API}/admin/kb/engine/run", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert body.get("ok") is True
        assert "message" in body


# ============ Multi-social Linking ============
class TestLinkedAccounts:
    def test_list_linked_admin_empty(self, admin_headers):
        r = requests.get(f"{API}/auth/me/linked", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert "linked" in body
        assert body.get("primary_email") == ADMIN_EMAIL
        # Admin is email primary → linked should be an empty array
        assert body["linked"] == []

    def test_link_and_unlink(self, admin_headers):
        # link
        r = requests.post(f"{API}/auth/me/link", headers=admin_headers,
                          json={"provider": "github", "provider_id": "test123",
                                "email": "ghtest@example.com"})
        assert r.status_code == 200, r.text
        # idempotent upsert
        r2 = requests.post(f"{API}/auth/me/link", headers=admin_headers,
                           json={"provider": "github", "provider_id": "test123",
                                 "email": "ghtest@example.com"})
        assert r2.status_code == 200
        # verify list
        r3 = requests.get(f"{API}/auth/me/linked", headers=admin_headers)
        assert r3.status_code == 200
        providers = [l["provider"] for l in r3.json()["linked"]]
        assert providers.count("github") == 1
        # unlink
        r4 = requests.delete(f"{API}/auth/me/link/github", headers=admin_headers)
        assert r4.status_code == 200
        # verify gone
        r5 = requests.get(f"{API}/auth/me/linked", headers=admin_headers)
        providers2 = [l["provider"] for l in r5.json()["linked"]]
        assert "github" not in providers2

    def test_reject_unsupported_provider(self, admin_headers):
        r = requests.post(f"{API}/auth/me/link", headers=admin_headers,
                          json={"provider": "facebook", "provider_id": "fb1"})
        assert r.status_code == 400


# ============ Capability Manifest ============
class TestCapabilityManifest:
    def test_chat_recommends_studio_not_external(self, admin_headers):
        r = requests.post(f"{API}/chat/stream",
                          headers=admin_headers,
                          json={"content": "Can you generate an image for me?"},
                          timeout=60, stream=True)
        assert r.status_code == 200, r.text
        # SSE stream — collect text
        text = ""
        for chunk in r.iter_content(chunk_size=None, decode_unicode=True):
            if chunk:
                text += chunk
            if len(text) > 8000:
                break
        text_l = text.lower()
        # Should recommend AI Studio
        assert ("studio" in text_l) or ("/studio" in text_l), f"missing studio recommendation. Sample: {text_l[:600]}"
        # Should NOT mention external tools
        assert "dall-e" not in text_l and "dall e" not in text_l, "external tool mentioned"
        assert "midjourney" not in text_l, "external tool mentioned"
        assert "chatgpt" not in text_l, "external tool mentioned"


# ============ Spend() flow regression ============
class TestSpendFlow:
    def test_wallet_get(self, admin_headers):
        r = requests.get(f"{API}/wallet/", headers=admin_headers)
        assert r.status_code in (200, 307)
        # /wallet or /wallet/ — accept either
        if r.status_code == 307:
            r = requests.get(f"{API}/wallet", headers=admin_headers)
        assert r.status_code == 200
        body = r.json()
        assert "total" in body

    def test_studio_summarize_credits_field(self, admin_headers):
        text = ("Batch B regression test. " * 20) + " Explain briefly the concept of pricing engine."
        r = requests.post(f"{API}/studio/summarize", headers=admin_headers,
                          json={"text": text})
        assert r.status_code == 200, r.text
        body = r.json()
        # credits_used or balance should exist somewhere in the flow
        # Just ensure endpoint doesn't crash and returns a summary
        assert "summary" in body or "source" in body or "credits_used" in body


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
