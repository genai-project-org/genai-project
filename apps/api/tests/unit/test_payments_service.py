"""Unit tests for services/payments_service.py — FX rate caching/fallback,
INR rounding, and the shared plan-crediting/-revoking helpers used by every
payment provider (Razorpay, Apple IAP, Google IAP, RevenueCat).

No real HTTP calls: `get_usd_to_inr()`'s live lookup is monkeypatched at the
`httpx.AsyncClient` call site. No real Razorpay calls: the webhook helpers
only need `_rzp.utility.verify_webhook_signature`, which is monkeypatched
per-test on the module-level client instance.
"""
import json

import pytest
from bson import ObjectId

from db import users_col
from services import payments_service as ps
from services import pricing_engine

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _reset_fx_cache():
    """The FX cache is a module-level dict, so it must not leak between tests."""
    ps._fx_cache.update(rate=None, at=None)
    yield
    ps._fx_cache.update(rate=None, at=None)


async def _make_user(plan="free"):
    result = await users_col.insert_one({"email": f"{plan}-pay@example.com", "plan": plan})
    return str(result.inserted_id)


# ------------------------------ round_up_inr ------------------------------

def test_round_up_inr_rounds_up_to_nearest_hundred():
    assert ps.round_up_inr(1968) == 2000


def test_round_up_inr_leaves_exact_hundreds_alone():
    assert ps.round_up_inr(2000) == 2000


def test_round_up_inr_rounds_up_a_small_remainder():
    assert ps.round_up_inr(2001) == 2100


# ------------------------------ get_usd_to_inr ------------------------------

class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, payload=None, exc=None, **_kwargs):
        self._payload = payload
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False

    async def get(self, _url):
        if self._exc:
            raise self._exc
        return _FakeResponse(self._payload)


async def test_get_usd_to_inr_uses_live_rate_with_padding(monkeypatch):
    payload = {"result": "success", "rates": {"INR": 85.0}}
    monkeypatch.setattr(ps.httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(payload=payload))
    rate = await ps.get_usd_to_inr()
    assert rate == round(85.0 * ps.FX_PAD, 2)


async def test_get_usd_to_inr_falls_back_on_failure(monkeypatch):
    monkeypatch.setattr(ps.httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(exc=RuntimeError("network down")))
    rate = await ps.get_usd_to_inr()
    assert rate == ps.FX_FALLBACK


async def test_get_usd_to_inr_falls_back_on_bad_payload(monkeypatch):
    monkeypatch.setattr(ps.httpx, "AsyncClient", lambda **kw: _FakeAsyncClient(payload={"result": "error"}))
    rate = await ps.get_usd_to_inr()
    assert rate == ps.FX_FALLBACK


async def test_get_usd_to_inr_uses_cache_within_ttl(monkeypatch):
    calls = {"n": 0}

    def _client_factory(**kw):
        calls["n"] += 1
        return _FakeAsyncClient(payload={"result": "success", "rates": {"INR": 90.0}})

    monkeypatch.setattr(ps.httpx, "AsyncClient", _client_factory)
    first = await ps.get_usd_to_inr()
    second = await ps.get_usd_to_inr()
    assert first == second
    assert calls["n"] == 1  # second call served from cache, no new HTTP call


# ------------------------------ _credit_plan / _revoke_plan ------------------------------

async def test_credit_plan_assigns_plan_and_logs_subscription():
    await pricing_engine.plans_col.update_one(
        {"_id": "pro"}, {"$set": {"name": "Pro", "monthly_credits": 0, "is_free": False}}, upsert=True)
    user_id = await _make_user("free")

    await ps._credit_plan(user_id, "pro", "razorpay", "sub_123")

    user_doc = await users_col.find_one({"_id": ObjectId(user_id)})
    assert user_doc["plan"] == "pro"

    sub = await ps.subscriptions_col.find_one({"user_id": user_id, "source": "razorpay", "ref_id": "sub_123"})
    assert sub is not None
    assert sub["status"] == "active"


async def test_credit_plan_is_idempotent_per_ref_id():
    await pricing_engine.plans_col.update_one(
        {"_id": "pro"}, {"$set": {"name": "Pro", "monthly_credits": 0, "is_free": False}}, upsert=True)
    user_id = await _make_user("free")
    await ps._credit_plan(user_id, "pro", "apple", "txn_1")
    await ps._credit_plan(user_id, "pro", "apple", "txn_1")
    count = await ps.subscriptions_col.count_documents(
        {"user_id": user_id, "source": "apple", "ref_id": "txn_1"})
    assert count == 1


async def test_credit_plan_unknown_plan_does_not_actually_skip():
    """Documents a real bug shared with `pricing_engine.get_plan`/`assign_plan`
    (see test_pricing_engine.py::test_assign_plan_unknown_plan_does_not_actually_raise):
    `get_plan()` always returns a *non-empty* dict (`{"plan_id": plan_id}`) even
    for a plan that doesn't exist, so `_credit_plan`'s
    `if not plan or not plan.get("plan_id"): return` guard is dead code and
    never actually skips anything — it silently sets the user's `plan` field
    to the bogus plan_id (no credits are granted since the synthesized dict
    has no `monthly_credits`). If `get_plan` is ever fixed to signal "not
    found", this test should assert the plan field stays untouched instead."""
    user_id = await _make_user("free")
    await ps._credit_plan(user_id, "does-not-exist", "apple", "txn_2")  # must not raise
    user_doc = await users_col.find_one({"_id": ObjectId(user_id)})
    assert user_doc["plan"] == "does-not-exist"  # the bug: silently overwritten, not skipped


async def test_revoke_plan_downgrades_to_free_and_marks_cancelled():
    user_id = await _make_user("pro")
    await ps.subscriptions_col.insert_one({
        "user_id": user_id, "plan_id": "pro", "source": "revenuecat", "ref_id": "orig_ref", "status": "active",
    })
    await ps._revoke_plan(user_id, "revenuecat", "cancel_ref")
    user_doc = await users_col.find_one({"_id": ObjectId(user_id)})
    assert user_doc["plan"] == "free"
    sub = await ps.subscriptions_col.find_one({"user_id": user_id, "source": "revenuecat"})
    assert sub["status"] == "cancelled"


# ------------------------------ handle_razorpay_webhook ------------------------------

async def test_handle_razorpay_webhook_credits_plan_on_subscription_charged(monkeypatch):
    await pricing_engine.plans_col.update_one(
        {"_id": "pro"}, {"$set": {"name": "Pro", "monthly_credits": 0, "is_free": False}}, upsert=True)
    user_id = await _make_user("free")
    monkeypatch.setattr(ps, "_rzp", _StubRazorpay())

    body = json.dumps({
        "event": "subscription.charged",
        "payload": {"subscription": {"entity": {
            "id": "sub_xyz", "notes": {"user_id": user_id, "iema_plan": "pro"},
        }}},
    }).encode()

    result = await ps.handle_razorpay_webhook(body, "sig")
    assert result["ok"] is True
    user_doc = await users_col.find_one({"_id": ObjectId(user_id)})
    assert user_doc["plan"] == "pro"


async def test_handle_razorpay_webhook_rejects_bad_signature(monkeypatch):
    monkeypatch.setattr(ps, "_rzp", _StubRazorpay(raise_on_verify=True))
    result = await ps.handle_razorpay_webhook(b"{}", "bad-sig")
    assert result["ok"] is False
    assert result["reason"] == "bad signature"


async def test_handle_razorpay_webhook_not_configured_without_client(monkeypatch):
    monkeypatch.setattr(ps, "_rzp", None)
    result = await ps.handle_razorpay_webhook(b"{}", "sig")
    assert result["ok"] is False


class _StubUtility:
    def __init__(self, raise_on_verify=False):
        self._raise = raise_on_verify

    def verify_webhook_signature(self, *_args):
        if self._raise:
            raise Exception("signature mismatch")


class _StubRazorpay:
    def __init__(self, raise_on_verify=False):
        self.utility = _StubUtility(raise_on_verify)


# ------------------------------ handle_revenuecat_webhook ------------------------------

async def test_revenuecat_webhook_rejects_bad_auth(monkeypatch):
    monkeypatch.setattr(ps, "REVENUECAT_WEBHOOK_AUTH", "expected-secret")
    result = await ps.handle_revenuecat_webhook({"event": {}}, "wrong-secret")
    assert result["ok"] is False


async def test_revenuecat_webhook_grants_plan_on_initial_purchase(monkeypatch):
    monkeypatch.setattr(ps, "REVENUECAT_WEBHOOK_AUTH", "expected-secret")
    await pricing_engine.plans_col.update_one(
        {"_id": "pro"}, {"$set": {"name": "Pro", "monthly_credits": 0, "is_free": False}}, upsert=True)
    user_id = await _make_user("free")
    body = {
        "event": {
            "type": "INITIAL_PURCHASE",
            "app_user_id": user_id,
            "product_id": "iema.pro.monthly",
            "id": "evt_1",
        }
    }
    result = await ps.handle_revenuecat_webhook(body, "expected-secret")
    assert result["ok"] is True
    user_doc = await users_col.find_one({"_id": ObjectId(user_id)})
    assert user_doc["plan"] == "pro"


async def test_revenuecat_webhook_revokes_plan_on_cancellation(monkeypatch):
    monkeypatch.setattr(ps, "REVENUECAT_WEBHOOK_AUTH", "expected-secret")
    user_id = await _make_user("pro")
    body = {
        "event": {
            "type": "CANCELLATION",
            "app_user_id": user_id,
            "product_id": "iema.pro.monthly",
            "id": "evt_2",
        }
    }
    result = await ps.handle_revenuecat_webhook(body, "expected-secret")
    assert result["ok"] is True
    user_doc = await users_col.find_one({"_id": ObjectId(user_id)})
    assert user_doc["plan"] == "free"


async def test_revenuecat_webhook_skips_non_account_user_id(monkeypatch):
    monkeypatch.setattr(ps, "REVENUECAT_WEBHOOK_AUTH", "expected-secret")
    body = {"event": {"type": "INITIAL_PURCHASE", "app_user_id": "not-a-mongo-id", "product_id": "x"}}
    result = await ps.handle_revenuecat_webhook(body, "expected-secret")
    assert result["ok"] is True
    assert result.get("skipped") == "no matching account"
