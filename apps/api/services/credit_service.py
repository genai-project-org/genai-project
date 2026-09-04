"""Credit wallet management with priority-based deduction."""
import os
from datetime import datetime, timezone
from typing import Optional
from bson import ObjectId
from db import wallets_col, transactions_col, now_iso, now_utc
from models import Wallet, CreditTransaction

WELCOME_CREDITS = float(os.environ.get("WELCOME_CREDITS", "100"))
DAILY_CREDITS = float(os.environ.get("DAILY_CREDITS", "20"))

# priority: welcome -> daily -> bonus -> referral -> promotional -> purchased
DEDUCT_PRIORITY = ["welcome_credits", "daily_credits", "bonus_credits", "referral_credits", "promotional_credits", "purchased_credits"]


async def get_or_create_wallet(user_id: str) -> Wallet:
    doc = await wallets_col.find_one({"user_id": user_id})
    if doc:
        wallet = Wallet.from_mongo(doc)
        # Refill daily credits if new day
        wallet = await _maybe_refill_daily(wallet)
        return wallet
    # New wallet with welcome credits
    wallet = Wallet(
        user_id=user_id,
        welcome_credits=WELCOME_CREDITS,
        daily_credits=DAILY_CREDITS,
        last_daily_refill_at=now_iso(),
    )
    data = wallet.to_mongo()
    result = await wallets_col.insert_one(data)
    wallet.id = str(result.inserted_id)
    # Log signup bonus
    await _log_transaction(user_id, WELCOME_CREDITS, wallet.total, "welcome", "signup_bonus", "Welcome bonus")
    await _log_transaction(user_id, DAILY_CREDITS, wallet.total, "daily", "daily_refill", "Daily credit refill")
    return wallet


async def _maybe_refill_daily(wallet: Wallet) -> Wallet:
    """Refill daily credits if last refill was on a previous UTC day."""
    now = now_utc()
    should_refill = True
    if wallet.last_daily_refill_at:
        try:
            last = datetime.fromisoformat(wallet.last_daily_refill_at)
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if last.date() == now.date():
                should_refill = False
        except Exception:
            pass
    if should_refill:
        wallet.daily_credits = DAILY_CREDITS  # reset to daily amount (not accumulate)
        wallet.last_daily_refill_at = now.isoformat()
        wallet.updated_at = now.isoformat()
        await wallets_col.update_one(
            {"user_id": wallet.user_id},
            {"$set": {
                "daily_credits": wallet.daily_credits,
                "last_daily_refill_at": wallet.last_daily_refill_at,
                "updated_at": wallet.updated_at,
            }},
        )
        await _log_transaction(wallet.user_id, DAILY_CREDITS, wallet.total, "daily", "daily_refill", "Daily credit refill")
    return wallet


async def has_credits(user_id: str, amount: float = 1) -> bool:
    wallet = await get_or_create_wallet(user_id)
    return wallet.total >= amount


async def deduct_credits(user_id: str, amount: float, kind: str = "ai_usage", description: str = "", ref_id: Optional[str] = None) -> Wallet:
    wallet = await get_or_create_wallet(user_id)
    if wallet.total < amount:
        raise ValueError("Insufficient credits")
    remaining = amount
    updates = {}
    for bucket in DEDUCT_PRIORITY:
        if remaining <= 0:
            break
        current = getattr(wallet, bucket)
        take = min(current, remaining)
        if take > 0:
            new_val = current - take
            setattr(wallet, bucket, new_val)
            updates[bucket] = new_val
            remaining -= take
    updates["updated_at"] = now_iso()
    await wallets_col.update_one({"user_id": user_id}, {"$set": updates})
    await _log_transaction(user_id, -amount, wallet.total, "mixed", kind, description, ref_id)
    return wallet


async def add_credits(user_id: str, amount: float, bucket: str = "purchased", kind: str = "purchase", description: str = "", ref_id: Optional[str] = None) -> Wallet:
    wallet = await get_or_create_wallet(user_id)
    field_map = {
        "welcome": "welcome_credits",
        "daily": "daily_credits",
        "bonus": "bonus_credits",
        "referral": "referral_credits",
        "promotional": "promotional_credits",
        "purchased": "purchased_credits",
    }
    field = field_map.get(bucket, "bonus_credits")
    new_val = getattr(wallet, field) + amount
    setattr(wallet, field, new_val)
    await wallets_col.update_one(
        {"user_id": user_id},
        {"$set": {field: new_val, "updated_at": now_iso()}},
    )
    await _log_transaction(user_id, amount, wallet.total, bucket, kind, description, ref_id)
    return wallet


async def _log_transaction(user_id: str, amount: float, balance_after: float, bucket: str, kind: str, description: str = "", ref_id: Optional[str] = None):
    tx = CreditTransaction(
        user_id=user_id,
        amount=amount,
        balance_after=balance_after,
        bucket=bucket,
        kind=kind,
        description=description,
        ref_id=ref_id,
    )
    await transactions_col.insert_one(tx.to_mongo())
