"""Unit tests for services/credit_service.py — wallet creation, priority-based
deduction across buckets, daily refill, and transaction logging.

No network calls, no real Mongo — the mongomock database is wired up by the
top-level conftest.py (autouse `_reset_db` fixture wipes it between tests).
"""
import datetime as dt

import pytest

from db import wallets_col, transactions_col
from services import credit_service

pytestmark = pytest.mark.anyio


async def test_get_or_create_wallet_grants_welcome_and_daily_credits():
    wallet = await credit_service.get_or_create_wallet("user-1")
    assert wallet.welcome_credits == credit_service.WELCOME_CREDITS
    assert wallet.daily_credits == credit_service.DAILY_CREDITS
    assert wallet.total == credit_service.WELCOME_CREDITS + credit_service.DAILY_CREDITS

    # Persisted, and a second call returns the same wallet rather than
    # re-granting welcome credits.
    again = await credit_service.get_or_create_wallet("user-1")
    assert again.welcome_credits == credit_service.WELCOME_CREDITS
    assert await wallets_col.count_documents({"user_id": "user-1"}) == 1


async def test_get_or_create_wallet_logs_signup_and_daily_transactions():
    await credit_service.get_or_create_wallet("user-2")
    txs = [doc async for doc in transactions_col.find({"user_id": "user-2"})]
    kinds = {t["kind"] for t in txs}
    assert "signup_bonus" in kinds
    assert "daily_refill" in kinds


async def test_has_credits_reflects_wallet_total():
    await credit_service.get_or_create_wallet("user-3")
    assert await credit_service.has_credits("user-3", amount=1)
    total = credit_service.WELCOME_CREDITS + credit_service.DAILY_CREDITS
    assert await credit_service.has_credits("user-3", amount=total)
    assert not await credit_service.has_credits("user-3", amount=total + 0.01)


async def test_deduct_credits_follows_priority_order():
    """welcome -> daily -> bonus -> referral -> promotional -> purchased"""
    wallet = await credit_service.get_or_create_wallet("user-4")
    # Top up every bucket so we can prove deduction order, not just totals.
    await credit_service.add_credits("user-4", 10, bucket="bonus", kind="admin_adjust")
    await credit_service.add_credits("user-4", 10, bucket="referral", kind="referral")
    await credit_service.add_credits("user-4", 10, bucket="promotional", kind="promo")
    await credit_service.add_credits("user-4", 10, bucket="purchased", kind="purchase")

    before = await wallets_col.find_one({"user_id": "user-4"})
    welcome, daily = before["welcome_credits"], before["daily_credits"]
    assert welcome > 0 and daily > 0

    # Deduct exactly the welcome+daily amount — only those two buckets should
    # move, everything added above must be untouched.
    await credit_service.deduct_credits("user-4", welcome + daily, kind="ai_usage")

    after = await wallets_col.find_one({"user_id": "user-4"})
    assert after["welcome_credits"] == 0
    assert after["daily_credits"] == 0
    assert after["bonus_credits"] == 10
    assert after["referral_credits"] == 10
    assert after["promotional_credits"] == 10
    assert after["purchased_credits"] == 10


async def test_deduct_credits_spills_into_next_bucket_when_one_is_insufficient():
    await credit_service.get_or_create_wallet("user-5")
    # welcome=100, daily=20 by default env. Deduct 105 -> drains welcome (100)
    # then takes 5 from daily, leaving 15 in daily.
    await credit_service.deduct_credits("user-5", credit_service.WELCOME_CREDITS + 5, kind="ai_usage")
    doc = await wallets_col.find_one({"user_id": "user-5"})
    assert doc["welcome_credits"] == 0
    assert doc["daily_credits"] == credit_service.DAILY_CREDITS - 5


async def test_deduct_credits_raises_on_insufficient_balance():
    await credit_service.get_or_create_wallet("user-6")
    huge = credit_service.WELCOME_CREDITS + credit_service.DAILY_CREDITS + 1
    with pytest.raises(ValueError):
        await credit_service.deduct_credits("user-6", huge, kind="ai_usage")


async def test_deduct_credits_logs_negative_transaction():
    await credit_service.get_or_create_wallet("user-7")
    await credit_service.deduct_credits("user-7", 5, kind="ai_usage", description="test spend")
    tx = await transactions_col.find_one({"user_id": "user-7", "kind": "ai_usage"})
    assert tx is not None
    assert tx["amount"] == -5
    assert tx["description"] == "test spend"


async def test_add_credits_unknown_bucket_updates_wallet_but_then_raises():
    """Documents a real edge-case bug in `add_credits`: an unrecognized
    `bucket` value IS mapped to `bonus_credits` for the wallet field update
    (via `field_map.get(bucket, "bonus_credits")`), but the raw, unmapped
    string is then passed straight through to `CreditTransaction.bucket`,
    whose pydantic model only allows a fixed Literal set — so the call
    crashes with a ValidationError *after* the wallet has already been
    mutated. This test pins the current (buggy) behavior rather than the
    ideal one; if `add_credits` is ever fixed to map/validate `bucket`
    consistently, this test should be updated to assert success instead."""
    await credit_service.get_or_create_wallet("user-8")
    with pytest.raises(Exception):
        await credit_service.add_credits("user-8", 7, bucket="not-a-real-bucket", kind="admin_adjust")
    # The wallet field was already incremented before the crash.
    doc = await wallets_col.find_one({"user_id": "user-8"})
    assert doc["bonus_credits"] == 7


async def test_daily_refill_resets_when_last_refill_was_a_previous_day():
    wallet = await credit_service.get_or_create_wallet("user-9")
    # Simulate a stale wallet: yesterday's refill timestamp, and spend down
    # today's daily allotment (as if the day had gone by after usage).
    yesterday = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat()
    await wallets_col.update_one(
        {"user_id": "user-9"},
        {"$set": {"daily_credits": 0, "last_daily_refill_at": yesterday}},
    )
    refreshed = await credit_service.get_or_create_wallet("user-9")
    assert refreshed.daily_credits == credit_service.DAILY_CREDITS
    # And a same-day fetch afterwards must NOT re-refill/duplicate it.
    again = await credit_service.get_or_create_wallet("user-9")
    assert again.daily_credits == credit_service.DAILY_CREDITS


async def test_daily_refill_does_not_accumulate_within_the_same_day():
    await credit_service.get_or_create_wallet("user-10")
    await wallets_col.update_one({"user_id": "user-10"}, {"$set": {"daily_credits": 3}})
    refreshed = await credit_service.get_or_create_wallet("user-10")
    # Same UTC day as last_daily_refill_at (set moments ago) -> no refill,
    # the manually-lowered value must be preserved rather than reset upward.
    assert refreshed.daily_credits == 3
