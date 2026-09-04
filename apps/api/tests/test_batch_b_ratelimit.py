"""Batch B — Rate limit 429 window test (isolated, must reset pricing after)."""
import os
import uuid
import requests

BASE_URL = (os.environ.get("REACT_APP_BACKEND_URL")
            or open("/app/frontend/.env").read().split("REACT_APP_BACKEND_URL=")[1].split("\n")[0]).rstrip("/")
API = f"{BASE_URL}/api"
ADMIN_EMAIL = "siddharth.bose@iemlabs.com"
ADMIN_PASSWORD = "Admin@12345"


def _admin_hdrs():
    r = requests.post(f"{API}/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    return {"Authorization": f"Bearer {r.json()['tokens']['access_token']}"}


def _new_user_hdrs():
    email = f"testuser_ratelimit_{uuid.uuid4().hex[:8]}@example.com"
    r = requests.post(f"{API}/auth/register",
                      json={"email": email, "name": "RateLimit Tester", "password": "Test@1234"})
    tok = r.json()["tokens"]["access_token"]
    # Top up wallet so credit balance is not the bottleneck — window is
    return {"Authorization": f"Bearer {tok}"}, email


def test_rate_limit_429():
    admin_hdrs = _admin_hdrs()
    user_hdrs, email = _new_user_hdrs()
    print(f"Fresh user: {email}")

    # Wallet total check
    w = requests.get(f"{API}/wallet", headers=user_hdrs).json()
    print(f"Wallet: {w.get('total')}")

    # 1) Set counseling_academic pricing to 12 credits (high value)
    r = requests.patch(f"{API}/admin/pricing/counseling_academic",
                       headers=admin_hdrs, json={"credit_cost": 12})
    assert r.status_code == 200, r.text
    print("Pricing set to 12 credits/call")

    try:
        # Free plan: window cap=15 credits over 4 hours.
        # First academic call = 12 credits → OK (12/15 used)
        r1 = requests.post(f"{API}/counseling",
                           headers=user_hdrs,
                           json={"message": "Study plan for GATE exam prep — unique batch B test", "mode": "academic"})
        print(f"1st call: {r1.status_code}")
        assert r1.status_code == 200, r1.text

        # Second call = 12 credits → 12+12=24 > 15 → 429
        r2 = requests.post(f"{API}/counseling",
                           headers=user_hdrs,
                           json={"message": "Different unique study plan question — batch B v2", "mode": "academic"})
        print(f"2nd call: {r2.status_code} body: {r2.text[:400]}")
        assert r2.status_code == 429, f"Expected 429 got {r2.status_code}"
        body = r2.json()
        detail = body.get("detail", {})
        assert isinstance(detail, dict), f"detail not a dict: {detail}"
        assert detail.get("message") == "Usage window exhausted"
        assert "resets_at" in detail
        assert "cap" in detail
        assert "used" in detail
        assert "resets_in_ms" in detail
        assert float(detail["cap"]) == 15.0
        print(f"429 body: {detail}")
        print("PASS: rate limit properly returns 429 with correct body")
    finally:
        # RESET pricing back
        rr = requests.patch(f"{API}/admin/pricing/counseling_academic",
                            headers=admin_hdrs, json={"credit_cost": 3})
        assert rr.status_code == 200
        print("Reset pricing to 3")


if __name__ == "__main__":
    test_rate_limit_429()
    print("ALL OK")
