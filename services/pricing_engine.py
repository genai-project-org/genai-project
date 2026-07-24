"""Pricing Engine — dynamic cost resolution, plan-based rate limiting, provider tracking.

Central concepts:
- `pricing_col`  → {_id: service_key, credit_cost, provider, category, description}
- `plans_col`    → {_id: 'free'|'pro'|'team', name, monthly_credits, window_hours, window_credits, price_inr, is_free, one_time}
- `usage_col`    → per-call provider usage record (drives Admin financial dashboard)
- Window enforcement: rolling window per user tracked in-place on the wallet.
"""
import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple
from fastapi import HTTPException, status
from db import db, wallets_col, now_iso, now_utc
from services.credit_service import get_or_create_wallet, deduct_credits, add_credits

logger = logging.getLogger(__name__)

pricing_col = db["pricing"]
plans_col = db["plans"]
usage_col = db["ai_usage"]  # per-call spend records for admin analytics
users_col = db["users"]


# Default pricing — inserted on startup if missing. Admin can edit via /admin/pricing.
DEFAULT_PRICING = [
    {"_id": "chat_message",           "credit_cost": 1,  "provider": "anthropic", "category": "chat",       "description": "AI Workspace text message"},
    {"_id": "chat_message_image",     "credit_cost": 3,  "provider": "anthropic", "category": "chat",       "description": "AI Workspace vision image"},
    {"_id": "studio_summarize",       "credit_cost": 2,  "provider": "anthropic", "category": "studio",     "description": "Studio text summary"},
    {"_id": "studio_image_low",       "credit_cost": 10, "provider": "openai",    "category": "studio",     "description": "Studio image generation (low)"},
    {"_id": "studio_image_medium",    "credit_cost": 20, "provider": "openai",    "category": "studio",     "description": "Studio image generation (medium)"},
    {"_id": "studio_image_high",      "credit_cost": 40, "provider": "openai",    "category": "studio",     "description": "Studio image generation (high)"},
    # Sora 2 video generation — priced per-duration; pro tier costs 3× standard.
    {"_id": "studio_video_std_4s",    "credit_cost": 60,  "provider": "openai",   "category": "studio",     "description": "Sora 2 video (4s)"},
    {"_id": "studio_video_std_8s",    "credit_cost": 120, "provider": "openai",   "category": "studio",     "description": "Sora 2 video (8s)"},
    {"_id": "studio_video_std_12s",   "credit_cost": 180, "provider": "openai",   "category": "studio",     "description": "Sora 2 video (12s)"},
    {"_id": "studio_video_pro_4s",    "credit_cost": 180, "provider": "openai",   "category": "studio",     "description": "Sora 2 Pro video (4s)"},
    {"_id": "studio_video_pro_8s",    "credit_cost": 360, "provider": "openai",   "category": "studio",     "description": "Sora 2 Pro video (8s)"},
    {"_id": "studio_video_pro_12s",   "credit_cost": 540, "provider": "openai",   "category": "studio",     "description": "Sora 2 Pro video (12s)"},
    {"_id": "career_job_search",      "credit_cost": 0,  "provider": "adzuna",    "category": "career",     "description": "Job search (Adzuna)"},
    {"_id": "career_learning_path",   "credit_cost": 5,  "provider": "anthropic", "category": "career",     "description": "Career learning roadmap"},
    {"_id": "counseling_career",      "credit_cost": 3,  "provider": "anthropic", "category": "counseling", "description": "Career counseling"},
    {"_id": "counseling_psychology",  "credit_cost": 3,  "provider": "anthropic", "category": "counseling", "description": "Wellness counseling"},
    {"_id": "counseling_academic",    "credit_cost": 3,  "provider": "anthropic", "category": "counseling", "description": "Academic counseling"},
    {"_id": "builder_create",         "credit_cost": 15, "provider": "anthropic", "category": "builder",    "description": "Code Builder project generation"},
    {"_id": "builder_refine",         "credit_cost": 8,  "provider": "anthropic", "category": "builder",    "description": "Code Builder refine"},
]

# Default plans. Free is ONE-TIME (no monthly refill). USD pricing.
DEFAULT_PLANS = [
    {"_id": "free",       "name": "Free",              "monthly_credits": 25,   "window_hours": 4,  "window_credits": 15,  "price_usd": 0.0,    "billing_period": "one_time", "is_free": True,  "one_time": True,  "priority": 1},
    {"_id": "pro",        "name": "Pro",               "monthly_credits": 1500, "window_hours": 5,  "window_credits": 200, "price_usd": 19.99,  "billing_period": "monthly",  "is_free": False, "one_time": False, "priority": 2},
    {"_id": "pro_annual", "name": "Pro (Annual)",      "monthly_credits": 1500, "window_hours": 5,  "window_credits": 200, "price_usd": 199.99, "billing_period": "annual",   "is_free": False, "one_time": False, "priority": 3},
    {"_id": "team",       "name": "Team",              "monthly_credits": 5000, "window_hours": 6,  "window_credits": 500, "price_usd": 49.99,  "billing_period": "monthly",  "is_free": False, "one_time": False, "priority": 4},
    {"_id": "team_annual","name": "Team (Annual)",     "monthly_credits": 5000, "window_hours": 6,  "window_credits": 500, "price_usd": 499.99, "billing_period": "annual",   "is_free": False, "one_time": False, "priority": 5},
]

# Very rough $ estimates per credit per provider (for admin financial dashboard).
# Assumes 1 credit ≈ 300 output tokens.
PROVIDER_COST_USD_PER_CREDIT = {
    "anthropic": 0.0015,   # Claude Haiku 4.5
    "openai":    0.005,    # GPT-Image-1 low
    "emergent":  0.001,
    "adzuna":    0.0,      # free
    "s3":        0.00005,
}


# ------------------------ setup ------------------------
async def seed_defaults():
    for entry in DEFAULT_PRICING:
        await pricing_col.update_one(
            {"_id": entry["_id"]},
            {"$setOnInsert": {**entry, "updated_at": now_iso()}},
            upsert=True,
        )
    for plan in DEFAULT_PLANS:
        # For pre-existing plans we ONLY set on insert to preserve admin edits.
        # However price_usd/billing_period are new fields — merge them if missing.
        existing = await plans_col.find_one({"_id": plan["_id"]})
        if existing:
            add = {k: v for k, v in plan.items()
                   if k not in ("_id",) and existing.get(k) is None}
            if add:
                await plans_col.update_one({"_id": plan["_id"]}, {"$set": add})
        else:
            await plans_col.insert_one({**plan, "updated_at": now_iso()})


async def ensure_indexes():
    await usage_col.create_index([("user_id", 1), ("created_at", -1)])
    await usage_col.create_index([("provider", 1), ("created_at", -1)])
    await usage_col.create_index([("service_key", 1), ("created_at", -1)])


# ------------------------ pricing ------------------------
async def resolve_cost(service_key: str) -> Dict[str, Any]:
    doc = await pricing_col.find_one({"_id": service_key})
    if not doc:
        return {"credit_cost": 0, "provider": "unknown", "service_key": service_key}
    return {
        "credit_cost": float(doc.get("credit_cost", 0)),
        "provider": doc.get("provider", "unknown"),
        "service_key": service_key,
        "description": doc.get("description", ""),
    }


async def list_pricing() -> list:
    items = []
    async for d in pricing_col.find({}).sort("_id", 1):
        d["service_key"] = d.pop("_id")
        items.append(d)
    return items


async def set_price(service_key: str, credit_cost: float, provider: Optional[str] = None) -> None:
    update = {"credit_cost": float(credit_cost), "updated_at": now_iso()}
    if provider:
        update["provider"] = provider
    await pricing_col.update_one({"_id": service_key}, {"$set": update}, upsert=True)


# ------------------------ plans ------------------------
async def get_plan(plan_id: str) -> Dict[str, Any]:
    doc = await plans_col.find_one({"_id": plan_id}) or {}
    doc["plan_id"] = doc.pop("_id", plan_id)
    return doc


async def list_plans() -> list:
    items = []
    async for d in plans_col.find({}).sort("priority", 1):
        d["plan_id"] = d.pop("_id")
        items.append(d)
    return items


async def set_plan(plan_id: str, updates: Dict[str, Any]) -> None:
    allowed = {"name", "monthly_credits", "window_hours", "window_credits",
               "price_usd", "price_inr", "billing_period", "is_free", "one_time", "priority"}
    clean = {k: v for k, v in updates.items() if k in allowed}
    clean["updated_at"] = now_iso()
    await plans_col.update_one({"_id": plan_id}, {"$set": clean}, upsert=True)


async def create_plan(plan_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    plan_id = plan_id.strip().lower().replace(" ", "_")
    if not plan_id:
        raise ValueError("plan_id required")
    existing = await plans_col.find_one({"_id": plan_id})
    if existing:
        raise ValueError(f"Plan `{plan_id}` already exists")
    doc = {
        "_id": plan_id,
        "name": data.get("name", plan_id.title()),
        "monthly_credits": float(data.get("monthly_credits", 0)),
        "window_hours": int(data.get("window_hours", 5)),
        "window_credits": float(data.get("window_credits", 100)),
        "price_usd": float(data.get("price_usd", 0)),
        "billing_period": data.get("billing_period", "monthly"),
        "is_free": bool(data.get("is_free", False)),
        "one_time": bool(data.get("one_time", False)),
        "priority": int(data.get("priority", 99)),
        "created_at": now_iso(),
    }
    await plans_col.insert_one(doc)
    return doc


async def delete_plan(plan_id: str) -> bool:
    if plan_id == "free":
        return False  # Never delete free
    res = await plans_col.delete_one({"_id": plan_id})
    return res.deleted_count > 0


async def get_user_plan(user_id: str) -> Dict[str, Any]:
    from bson import ObjectId
    u = await users_col.find_one({"_id": ObjectId(user_id)}, {"plan": 1})
    plan_id = (u or {}).get("plan") or "free"
    return await get_plan(plan_id)


# ------------------------ window enforcement ------------------------
async def _window_status(wallet_doc: Dict[str, Any], plan: Dict[str, Any]) -> Dict[str, Any]:
    """Returns {used, cap, resets_at}. Auto-resets in-place if window expired."""
    now = now_utc()
    hours = int(plan.get("window_hours", 5))
    cap = float(plan.get("window_credits", 80))
    window_start_raw = wallet_doc.get("window_start_at")
    used = float(wallet_doc.get("window_used", 0))
    start = None
    if window_start_raw:
        try:
            start = datetime.fromisoformat(window_start_raw)
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
        except Exception:
            start = None
    if not start or (now - start) >= timedelta(hours=hours):
        # Fresh window
        start = now
        used = 0.0
        await wallets_col.update_one(
            {"user_id": wallet_doc["user_id"]},
            {"$set": {"window_start_at": start.isoformat(), "window_used": 0.0}},
        )
    resets_at = (start + timedelta(hours=hours)).isoformat()
    return {"used": used, "cap": cap, "resets_at": resets_at, "window_hours": hours, "start_at": start.isoformat()}


async def check_window(user_id: str, needed: float) -> Dict[str, Any]:
    wallet = await get_or_create_wallet(user_id)
    wdoc = await wallets_col.find_one({"user_id": user_id}) or {"user_id": user_id}
    plan = await get_user_plan(user_id)
    status = await _window_status(wdoc, plan)
    remaining = max(0.0, status["cap"] - status["used"])
    ok = needed <= remaining
    return {"ok": ok, "remaining": remaining, **status}


# ------------------------ central spend ------------------------
async def spend(
    user_id: str,
    service_key: str,
    provider_override: Optional[str] = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    description: str = "",
    ref_id: Optional[str] = None,
    skip_charge: bool = False,
) -> Dict[str, Any]:
    """Atomic: resolve price → enforce plan window → deduct → log usage.

    Set `skip_charge=True` on KB hits so the call still records provider=`kb` usage
    but no credits are deducted or window consumed.
    """
    pricing = await resolve_cost(service_key)
    cost = 0.0 if skip_charge else float(pricing["credit_cost"])
    provider = provider_override or ("kb" if skip_charge else pricing["provider"])

    balance = None
    window = None

    if cost > 0:
        # Window check
        window = await check_window(user_id, cost)
        if not window["ok"]:
            hrs_left_ms = _ms_until(window["resets_at"])
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "message": "Usage window exhausted",
                    "resets_at": window["resets_at"],
                    "window_hours": window["window_hours"],
                    "used": window["used"],
                    "cap": window["cap"],
                    "resets_in_ms": hrs_left_ms,
                },
            )
        # Wallet balance
        wallet = await get_or_create_wallet(user_id)
        if wallet.total < cost:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail={
                    "message": "Insufficient credits — please subscribe or top-up",
                    "balance": wallet.total,
                    "needed": cost,
                },
            )
        # Deduct
        wallet = await deduct_credits(user_id, cost, "ai_usage", description or pricing.get("description", service_key), ref_id)
        # Advance window usage
        await wallets_col.update_one(
            {"user_id": user_id},
            {"$inc": {"window_used": cost}},
        )
        balance = wallet.total

    # Always record usage (drives admin dashboards, even for KB hits)
    usd = cost * float(PROVIDER_COST_USD_PER_CREDIT.get(provider, 0.001))
    await usage_col.insert_one({
        "user_id": user_id,
        "service_key": service_key,
        "provider": provider,
        "credits": cost,
        "tokens_in": int(tokens_in or 0),
        "tokens_out": int(tokens_out or 0),
        "cost_usd_estimate": round(usd, 6),
        "kb_hit": skip_charge,
        "ref_id": ref_id,
        "created_at": now_iso(),
    })

    return {
        "credits_used": cost,
        "provider": provider,
        "balance": balance,
        "window": window,
    }


def _ms_until(iso: str) -> int:
    try:
        t = datetime.fromisoformat(iso)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        delta = t - now_utc()
        return max(0, int(delta.total_seconds() * 1000))
    except Exception:
        return 0


# ------------------------ plan assignment ------------------------
async def assign_plan(user_id: str, plan_id: str, add_monthly_credits: bool = True) -> None:
    from bson import ObjectId
    plan = await get_plan(plan_id)
    if not plan:
        raise ValueError(f"Unknown plan {plan_id}")
    await users_col.update_one({"_id": ObjectId(user_id)}, {"$set": {"plan": plan_id, "plan_since": now_iso()}})
    if add_monthly_credits and plan.get("monthly_credits", 0) > 0:
        await add_credits(user_id, float(plan["monthly_credits"]),
                          bucket="bonus", kind="plan_credit",
                          description=f"{plan.get('name','plan')} monthly credits")
