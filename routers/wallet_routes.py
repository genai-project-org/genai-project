"""Wallet routes."""
from fastapi import APIRouter, Depends, Query
from typing import List
from bson import ObjectId
from auth import get_current_user
from db import wallets_col, transactions_col
from models import User
from services.credit_service import get_or_create_wallet

router = APIRouter(prefix="/wallet", tags=["wallet"])


@router.get("/")
async def get_wallet(user: User = Depends(get_current_user)):
    wallet = await get_or_create_wallet(user.id)
    return {
        "user_id": user.id,
        "welcome_credits": wallet.welcome_credits,
        "daily_credits": wallet.daily_credits,
        "bonus_credits": wallet.bonus_credits,
        "referral_credits": wallet.referral_credits,
        "promotional_credits": wallet.promotional_credits,
        "purchased_credits": wallet.purchased_credits,
        "total": wallet.total,
        "last_daily_refill_at": wallet.last_daily_refill_at,
    }


@router.get("/transactions")
async def list_transactions(user: User = Depends(get_current_user), limit: int = Query(50, le=200), skip: int = 0):
    cursor = transactions_col.find({"user_id": user.id}).sort("created_at", -1).skip(skip).limit(limit)
    txs = []
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        txs.append(doc)
    return {"items": txs, "count": len(txs)}



@router.get("/window")
async def get_window(user: User = Depends(get_current_user)):
    """Current rolling usage window + plan info (drives usage bar UI)."""
    from services.pricing_engine import check_window, get_user_plan
    plan = await get_user_plan(user.id)
    w = await check_window(user.id, 0)
    return {"plan": plan, "window": w}
