"""Smoke tests validating the test harness itself: app import, mongomock DB,
and a trivial round trip through TestClient. If these fail, something is
wrong with conftest.py's plumbing rather than with app logic.
"""
import pytest

pytestmark = pytest.mark.integration


def test_health_endpoint(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "healthy"}


def test_root_endpoint(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_register_creates_a_real_mongomock_user(client):
    resp = client.post("/api/auth/register", json={
        "email": "smoke@example.com", "password": "Test@12345", "name": "Smoke Test",
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user"]["email"] == "smoke@example.com"
    assert "access_token" in body["tokens"]
