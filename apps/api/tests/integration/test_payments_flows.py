"""Integration tests for routers/payments_routes.py.

Razorpay is "configured" in this test environment (conftest.py sets a fake
RAZORPAY_KEY_ID so the real, non-501 code paths run) but every call that
would actually leave the process — `_razorpay_client.payment_link.*`,
`.utility.verify_payment_signature`, the live FX-rate lookup — is monkeypatched
at the call site. Nothing here makes a real network call.
"""
import pytest

import routers.payments_routes as payments_routes
from db import credit_packs_col, payment_transactions_col
from models import PaymentTransaction
from services import discount_service, pricing_engine

pytestmark = pytest.mark.integration


async def _seed_pack(slug="pro-usd", price=39.0, credits=5000, bonus=750, currency="usd"):
    await credit_packs_col.insert_one({
        "name": "Pro", "slug": slug, "description": "Power users", "price": price,
        "currency": currency, "credits": credits, "bonus_credits": bonus,
        "is_popular": False, "sort_order": 1, "is_visible": True,
    })


@pytest.fixture(autouse=True)
def _fake_fx_rate(monkeypatch):
    """Every test in this module gets a deterministic USD->INR rate instead of
    hitting the live open.er-api.com lookup that `get_usd_to_inr()` performs."""
    async def _fake_rate():
        return 85.0
    monkeypatch.setattr(payments_routes, "get_usd_to_inr", _fake_rate)
    yield


# ------------------------------ fx-rate ------------------------------

def test_fx_rate_endpoint_returns_the_mocked_rate(client):
    resp = client.get("/api/payments/fx-rate")
    assert resp.status_code == 200
    assert resp.json() == {"rate": 85.0, "currency": "INR"}


# ------------------------------ discount validate ------------------------------

def test_discount_validate_unknown_code(client, auth_user):
    import asyncio
    asyncio.run(_seed_pack())
    _user, _tokens, headers = auth_user
    resp = client.post("/api/payments/discount/validate", headers=headers,
                        json={"code": "NOPE", "pack_slug": "pro-usd"})
    assert resp.status_code == 200
    assert resp.json()["ok"] is False


def test_discount_validate_applies_percent_off(client, auth_user):
    import asyncio
    asyncio.run(_seed_pack())
    asyncio.run(discount_service.create_discount({
        "code": "SAVE10", "percent_off": 10, "applies_to": "any", "max_uses": 0,
    }))
    _user, _tokens, headers = auth_user
    resp = client.post("/api/payments/discount/validate", headers=headers,
                        json={"code": "save10", "pack_slug": "pro-usd"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["final_usd"] == pytest.approx(35.1)
    assert body["final_inr"] > 0


def test_discount_validate_requires_auth(client):
    resp = client.post("/api/payments/discount/validate", json={"code": "X", "pack_slug": "pro-usd"})
    assert resp.status_code == 401


# ------------------------------ public plans ------------------------------

def test_list_public_plans_excludes_free_plan(client):
    import asyncio

    async def _seed():
        await pricing_engine.plans_col.update_one(
            {"_id": "free"}, {"$set": {"name": "Free", "is_free": True}}, upsert=True)
        await pricing_engine.plans_col.update_one(
            {"_id": "pro"}, {"$set": {"name": "Pro", "is_free": False, "price_usd": 19}}, upsert=True)

    asyncio.run(_seed())
    resp = client.get("/api/payments/plans")
    assert resp.status_code == 200
    items = resp.json()["items"]
    plan_ids = {p["plan_id"] for p in items}
    names = {p["name"] for p in items}
    assert "pro" in plan_ids
    assert "free" not in plan_ids
    assert "Pro" in names
    assert "Free" not in names


# ------------------------------ payment history ------------------------------

def test_payment_history_empty_for_new_user(client, auth_user):
    _user, _tokens, headers = auth_user
    resp = client.get("/api/payments/history", headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"items": []}


def test_payment_history_lists_seeded_transaction(client, auth_user):
    user, _tokens, headers = auth_user
    import asyncio
    tx = PaymentTransaction(
        user_id=user["id"], provider="razorpay", pack_slug="pro-usd",
        amount=39.0, currency="usd", credits=5750, order_id="plink_test123",
        status="paid", credited=True,
    )
    asyncio.run(payment_transactions_col.insert_one(tx.to_mongo()))
    resp = client.get("/api/payments/history", headers=headers)
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["order_id"] == "plink_test123"


# ------------------------------ razorpay order / link status (mocked client) ------------------------------

def test_razorpay_order_requires_auth(client):
    resp = client.post("/api/payments/razorpay/order", json={"pack_slug": "pro-usd"})
    assert resp.status_code == 401


def test_razorpay_order_creates_a_payment_link(client, auth_user, monkeypatch):
    import asyncio
    asyncio.run(_seed_pack())

    created = {}

    def _fake_create(payload):
        created.update(payload)
        return {"id": "plink_fake001", "short_url": "https://rzp.io/i/fake001"}

    monkeypatch.setattr(payments_routes._razorpay_client.payment_link, "create", _fake_create)

    _user, _tokens, headers = auth_user
    resp = client.post("/api/payments/razorpay/order", headers=headers, json={"pack_slug": "pro-usd"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["payment_link_id"] == "plink_fake001"
    assert body["credits"] == 5750
    assert created["currency"] == "INR"
    # 39 USD * 85.0 (mocked FX) = 3315, rounded up to nearest 100 -> 3400, in paise.
    assert created["amount"] == 340000


def test_razorpay_order_404s_for_unknown_pack(client, auth_user):
    _user, _tokens, headers = auth_user
    resp = client.post("/api/payments/razorpay/order", headers=headers, json={"pack_slug": "does-not-exist"})
    assert resp.status_code == 404


def test_razorpay_link_status_credits_wallet_exactly_once(client, auth_user, monkeypatch):
    user, _tokens, headers = auth_user
    import asyncio
    tx = PaymentTransaction(
        user_id=user["id"], provider="razorpay", pack_slug="pro-usd",
        amount=39.0, currency="usd", credits=100, order_id="plink_status1",
        status="initiated", credited=False,
    )
    asyncio.run(payment_transactions_col.insert_one(tx.to_mongo()))

    monkeypatch.setattr(
        payments_routes._razorpay_client.payment_link, "fetch",
        lambda link_id: {"status": "paid", "short_url": "https://rzp.io/i/status1"},
    )

    resp = client.get("/api/payments/razorpay/link-status/plink_status1", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "paid"
    assert body["credited"] is True
    assert body["balance"] is not None

    wallet_resp = client.get("/api/wallet/", headers=headers)
    balance_after_first = wallet_resp.json()["total"]

    # Polling again after it's already credited must NOT double-credit.
    resp2 = client.get("/api/payments/razorpay/link-status/plink_status1", headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["balance"] is None  # nothing new was credited this call

    wallet_resp2 = client.get("/api/wallet/", headers=headers)
    assert wallet_resp2.json()["total"] == balance_after_first


def test_razorpay_verify_rejects_bad_signature(client, auth_user, monkeypatch):
    def _raise(*_a, **_k):
        raise Exception("bad signature")

    monkeypatch.setattr(payments_routes._razorpay_client.utility, "verify_payment_signature", _raise)
    _user, _tokens, headers = auth_user
    resp = client.post("/api/payments/razorpay/verify", headers=headers, json={
        "razorpay_order_id": "order_x", "razorpay_payment_id": "pay_x", "razorpay_signature": "sig_x",
    })
    assert resp.status_code == 400


# ------------------------------ IAP (mocked service functions) ------------------------------

def test_iap_apple_verify_rejects_invalid_receipt(client, auth_user, monkeypatch):
    async def _fake_verify(_user_id, _receipt, _mapping):
        return {"ok": False, "error": "Apple receipt invalid"}

    monkeypatch.setattr(payments_routes, "_apple_verify", _fake_verify)
    _user, _tokens, headers = auth_user
    resp = client.post("/api/payments/iap/apple/verify", headers=headers, json={"receipt": "ZmFrZQ=="})
    assert resp.status_code == 400


def test_iap_google_verify_rejects_invalid_receipt(client, auth_user, monkeypatch):
    async def _fake_verify(_user_id, _product_id, _token, _is_sub, _mapping):
        return {"ok": False, "error": "purchase state=2"}

    monkeypatch.setattr(payments_routes, "_google_verify", _fake_verify)
    _user, _tokens, headers = auth_user
    resp = client.post("/api/payments/iap/google/verify", headers=headers, json={
        "product_id": "iema.pro.monthly", "purchase_token": "tok", "is_subscription": True,
    })
    assert resp.status_code == 400
