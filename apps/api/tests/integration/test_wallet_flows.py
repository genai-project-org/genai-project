"""Integration tests for routers/wallet_routes.py — the wallet balance,
transaction history and rolling usage window endpoints, all reached through
the real `GET /api/wallet/*` HTTP surface with a real registered+authenticated
user (no DB/auth dependency overrides needed; mongomock + real JWTs already
give a hermetic end-to-end path).
"""
import pytest

from services import credit_service, pricing_engine

pytestmark = pytest.mark.integration


def test_get_wallet_requires_auth(client):
    resp = client.get("/api/wallet/")
    assert resp.status_code == 401


def test_get_wallet_returns_welcome_and_daily_credits(client, auth_user):
    _user, _tokens, headers = auth_user
    resp = client.get("/api/wallet/", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["welcome_credits"] == credit_service.WELCOME_CREDITS
    assert body["daily_credits"] == credit_service.DAILY_CREDITS
    assert body["total"] == credit_service.WELCOME_CREDITS + credit_service.DAILY_CREDITS


def test_transactions_lists_signup_and_daily_refill(client, auth_user):
    _user, _tokens, headers = auth_user
    resp = client.get("/api/wallet/transactions", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    kinds = {tx["kind"] for tx in body["items"]}
    assert "signup_bonus" in kinds
    assert "daily_refill" in kinds
    assert body["count"] == len(body["items"])


def test_transactions_only_shows_the_caller_own_history(client, register_user):
    user_a, _tokens_a, headers_a = register_user()
    user_b, _tokens_b, headers_b = register_user()

    resp_a = client.get("/api/wallet/transactions", headers=headers_a)
    resp_b = client.get("/api/wallet/transactions", headers=headers_b)
    assert resp_a.status_code == 200 and resp_b.status_code == 200

    ids_a = {tx["user_id"] for tx in resp_a.json()["items"]}
    ids_b = {tx["user_id"] for tx in resp_b.json()["items"]}
    assert ids_a == {user_a["id"]}
    assert ids_b == {user_b["id"]}


def test_transactions_respects_limit(client, auth_user):
    _user, _tokens, headers = auth_user
    resp = client.get("/api/wallet/transactions", params={"limit": 1}, headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 1


def test_window_endpoint_returns_plan_and_usage_window(client, auth_user):
    user, _tokens, headers = auth_user
    import asyncio
    asyncio.run(pricing_engine.plans_col.update_one(
        {"_id": "free"},
        {"$set": {"name": "Free", "window_hours": 4, "window_credits": 15, "is_free": True}},
        upsert=True,
    ))
    resp = client.get("/api/wallet/window", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["plan"]["plan_id"] == "free"
    assert body["window"]["ok"] is True
    assert body["window"]["remaining"] == 15
