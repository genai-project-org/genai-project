"""Unit tests for services/pricing_engine.py — cost resolution, rolling usage
windows, the central `spend()` charge path, and plan CRUD guardrails.
"""
import datetime as dt

import pytest
from fastapi import HTTPException

from db import wallets_col, users_col
from services import credit_service, pricing_engine

pytestmark = pytest.mark.anyio


async def _seed_pricing(service_key="widget_use", cost=10, provider="anthropic"):
    await pricing_engine.pricing_col.update_one(
        {"_id": service_key},
        {"$set": {"credit_cost": cost, "provider": provider, "category": "test",
                   "description": "test service"}},
        upsert=True,
    )


async def _seed_plan(plan_id="free", **overrides):
    doc = {
        "_id": plan_id, "name": plan_id.title(), "monthly_credits": 25,
        "window_hours": 4, "window_credits": 15, "is_free": plan_id == "free",
        "one_time": True, "priority": 1,
    }
    doc.update(overrides)
    await pricing_engine.plans_col.update_one({"_id": plan_id}, {"$set": doc}, upsert=True)


async def _make_user(plan="free"):
    result = await users_col.insert_one({"email": f"{plan}-user@example.com", "plan": plan})
    return str(result.inserted_id)


# ------------------------------ resolve_cost / pricing CRUD ------------------------------

async def test_resolve_cost_returns_zero_for_unknown_service():
    result = await pricing_engine.resolve_cost("nonexistent_service_key")
    assert result == {"credit_cost": 0, "provider": "unknown", "service_key": "nonexistent_service_key"}


async def test_resolve_cost_returns_seeded_price():
    await _seed_pricing("widget_use", cost=12.5, provider="openai")
    result = await pricing_engine.resolve_cost("widget_use")
    assert result["credit_cost"] == 12.5
    assert result["provider"] == "openai"


async def test_set_price_upserts_and_list_pricing_reflects_it():
    await pricing_engine.set_price("brand_new_key", 3, provider="anthropic")
    items = await pricing_engine.list_pricing()
    keys = {i["service_key"]: i for i in items}
    assert keys["brand_new_key"]["credit_cost"] == 3


# ------------------------------ plans ------------------------------

async def test_create_plan_rejects_duplicate():
    await pricing_engine.create_plan("gold", {"name": "Gold"})
    with pytest.raises(ValueError):
        await pricing_engine.create_plan("gold", {"name": "Gold Again"})


async def test_create_plan_normalizes_id():
    doc = await pricing_engine.create_plan("  My Plan ", {"name": "My Plan"})
    assert doc["_id"] == "my_plan"


async def test_delete_plan_refuses_to_delete_free():
    await _seed_plan("free")
    assert await pricing_engine.delete_plan("free") is False
    assert await pricing_engine.plans_col.find_one({"_id": "free"}) is not None


async def test_delete_plan_deletes_non_free():
    await pricing_engine.create_plan("silver", {"name": "Silver"})
    assert await pricing_engine.delete_plan("silver") is True
    assert await pricing_engine.plans_col.find_one({"_id": "silver"}) is None


async def test_set_plan_ignores_price_and_billing_period_fields():
    """price_usd/price_inr/billing_period are documented as locked after
    creation — admin PATCH must silently drop them, not apply them."""
    await _seed_plan("pro", price_usd=19.99, billing_period="monthly")
    await pricing_engine.set_plan("pro", {
        "name": "Pro Renamed", "price_usd": 999.0, "billing_period": "annual",
    })
    doc = await pricing_engine.plans_col.find_one({"_id": "pro"})
    assert doc["name"] == "Pro Renamed"
    assert doc["price_usd"] == 19.99
    assert doc["billing_period"] == "monthly"


# ------------------------------ window enforcement ------------------------------

async def test_check_window_ok_when_under_cap():
    await _seed_plan("free", window_hours=4, window_credits=15)
    user_id = await _make_user("free")
    result = await pricing_engine.check_window(user_id, 5)
    assert result["ok"] is True
    assert result["remaining"] == 15


async def test_check_window_blocks_when_over_cap():
    await _seed_plan("free", window_hours=4, window_credits=15)
    user_id = await _make_user("free")
    result = await pricing_engine.check_window(user_id, 16)
    assert result["ok"] is False


async def test_window_resets_after_expiry():
    await _seed_plan("free", window_hours=4, window_credits=15)
    user_id = await _make_user("free")
    # Force a window that started 5 hours ago (> the 4h cap) with usage
    # already at the limit -- should reset to a fresh, unused window.
    stale_start = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=5)).isoformat()
    await wallets_col.update_one(
        {"user_id": user_id},
        {"$set": {"window_start_at": stale_start, "window_used": 15}},
        upsert=True,
    )
    result = await pricing_engine.check_window(user_id, 5)
    assert result["ok"] is True
    assert result["used"] == 0


async def test_window_does_not_reset_within_the_same_window():
    await _seed_plan("free", window_hours=4, window_credits=15)
    user_id = await _make_user("free")
    recent_start = dt.datetime.now(dt.timezone.utc).isoformat()
    await wallets_col.update_one(
        {"user_id": user_id},
        {"$set": {"window_start_at": recent_start, "window_used": 10}},
        upsert=True,
    )
    result = await pricing_engine.check_window(user_id, 4)
    assert result["ok"] is True
    assert result["used"] == 10
    assert result["remaining"] == 5


# ------------------------------ spend() ------------------------------

async def test_spend_deducts_wallet_and_advances_window():
    await _seed_pricing("widget_use", cost=10, provider="anthropic")
    await _seed_plan("free", window_hours=4, window_credits=100)
    user_id = await _make_user("free")
    await credit_service.get_or_create_wallet(user_id)  # welcome+daily credits

    result = await pricing_engine.spend(user_id, "widget_use")
    assert result["credits_used"] == 10
    assert result["provider"] == "anthropic"

    wallet = await wallets_col.find_one({"user_id": user_id})
    assert wallet["window_used"] == 10

    usage_doc = await pricing_engine.usage_col.find_one({"user_id": user_id, "service_key": "widget_use"})
    assert usage_doc is not None
    assert usage_doc["credits"] == 10


async def test_spend_raises_402_when_wallet_balance_insufficient():
    await _seed_pricing("expensive_thing", cost=100_000, provider="anthropic")
    await _seed_plan("free", window_hours=4, window_credits=1_000_000)
    user_id = await _make_user("free")
    await credit_service.get_or_create_wallet(user_id)

    with pytest.raises(HTTPException) as exc_info:
        await pricing_engine.spend(user_id, "expensive_thing")
    assert exc_info.value.status_code == 402


async def test_spend_raises_429_when_window_exhausted():
    await _seed_pricing("widget_use", cost=10, provider="anthropic")
    await _seed_plan("free", window_hours=4, window_credits=5)  # cap below cost
    user_id = await _make_user("free")
    await credit_service.get_or_create_wallet(user_id)

    with pytest.raises(HTTPException) as exc_info:
        await pricing_engine.spend(user_id, "widget_use")
    assert exc_info.value.status_code == 429


async def test_spend_skip_charge_records_zero_cost_usage_without_touching_wallet():
    await _seed_pricing("kb_hit_service", cost=10, provider="anthropic")
    await _seed_plan("free", window_hours=4, window_credits=100)
    user_id = await _make_user("free")
    wallet_before = await credit_service.get_or_create_wallet(user_id)

    result = await pricing_engine.spend(user_id, "kb_hit_service", skip_charge=True)
    assert result["credits_used"] == 0
    assert result["provider"] == "kb"
    assert result["balance"] is None

    wallet_after = await wallets_col.find_one({"user_id": user_id})
    assert wallet_after["welcome_credits"] == wallet_before.welcome_credits

    usage_doc = await pricing_engine.usage_col.find_one({"user_id": user_id, "service_key": "kb_hit_service"})
    assert usage_doc["kb_hit"] is True
    assert usage_doc["credits"] == 0


async def test_spend_free_service_records_usage_without_guard():
    """credit_cost=0 services (e.g. career_job_search) must never trip the
    window/balance guard, even for a brand-new user with an empty wallet."""
    await _seed_pricing("free_service", cost=0, provider="adzuna")
    user_id = await _make_user("free")
    result = await pricing_engine.spend(user_id, "free_service")
    assert result["credits_used"] == 0
    assert result["balance"] is None


async def test_precheck_raises_without_deducting():
    await _seed_pricing("widget_use", cost=10, provider="anthropic")
    await _seed_plan("free", window_hours=4, window_credits=5)
    user_id = await _make_user("free")
    await credit_service.get_or_create_wallet(user_id)

    with pytest.raises(HTTPException):
        await pricing_engine.precheck(user_id, "widget_use")
    # Nothing should have been deducted or logged as usage.
    assert await pricing_engine.usage_col.count_documents({"user_id": user_id}) == 0


async def test_precheck_is_a_noop_for_free_services():
    await _seed_pricing("free_service", cost=0, provider="adzuna")
    user_id = await _make_user("free")
    await pricing_engine.precheck(user_id, "free_service")  # must not raise


# ------------------------------ assign_plan ------------------------------

async def test_assign_plan_with_monthly_credits_currently_raises_on_transaction_log():
    """Documents a real production bug: `assign_plan()` -> `add_credits(...,
    kind="plan_credit")`, but `CreditTransaction.kind` only allows
    {signup_bonus, daily_refill, ai_usage, purchase, refund, admin_adjust,
    referral, promo} — "plan_credit" isn't one of them. Every real caller of
    `assign_plan` with `monthly_credits > 0` (Razorpay/Apple/Google IAP
    webhooks, RevenueCat, admin plan assignment) hits this today. The user's
    `plan` field IS updated (that write happens first), but the credit grant
    then crashes before the wallet/transaction log is written — so the user
    ends up "upgraded" without receiving their monthly credits.
    If `add_credits`/`CreditTransaction.kind` is ever fixed to accept
    "plan_credit", this test should be updated to assert success instead."""
    await _seed_plan("pro", monthly_credits=1500)
    user_id = await _make_user("free")
    await credit_service.get_or_create_wallet(user_id)

    with pytest.raises(Exception):
        await pricing_engine.assign_plan(user_id, "pro")

    user_doc = await users_col.find_one({"_id": __import__("bson").ObjectId(user_id)})
    assert user_doc["plan"] == "pro"  # plan flip already happened before the crash


async def test_assign_plan_with_no_monthly_credits_succeeds():
    """`add_monthly_credits` short-circuits when the plan grants 0 monthly
    credits, so the `add_credits("plan_credit")` bug above never fires here."""
    await _seed_plan("free", monthly_credits=0)
    user_id = await _make_user("pro")
    await pricing_engine.assign_plan(user_id, "free")
    user_doc = await users_col.find_one({"_id": __import__("bson").ObjectId(user_id)})
    assert user_doc["plan"] == "free"


async def test_assign_plan_unknown_plan_does_not_actually_raise():
    """Documents a real bug: `get_plan()` always returns a *non-empty* dict
    (`{"plan_id": plan_id}`) even when no such plan exists in `plans_col`,
    because it unconditionally does `doc["plan_id"] = doc.pop("_id",
    plan_id)` on the (possibly empty) result. That means `assign_plan`'s
    `if not plan: raise ValueError(...)` guard is dead code — it can never
    trigger — so assigning a bogus/typo'd plan_id silently sets the user's
    `plan` field to that garbage value instead of raising, and simply skips
    the credit grant (since `plan.get("monthly_credits", 0) > 0` is False for
    the synthesized dict). If `get_plan`/`assign_plan` is ever fixed to
    detect a missing plan, this test should assert `pytest.raises(ValueError)`
    instead."""
    user_id = await _make_user("free")
    await pricing_engine.assign_plan(user_id, "does-not-exist")  # does NOT raise today
    user_doc = await users_col.find_one({"_id": __import__("bson").ObjectId(user_id)})
    assert user_doc["plan"] == "does-not-exist"
