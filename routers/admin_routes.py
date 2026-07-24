"""Admin routes."""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from bson import ObjectId
from auth import require_admin
from db import (
    users_col, wallets_col, payment_transactions_col, transactions_col,
    ai_requests_col, conversations_col, messages_col, credit_packs_col, now_iso
)
from models import User, AdminUpdateWalletRequest
from services.credit_service import add_credits, get_or_create_wallet
from services.notification_service import notify

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats")
async def stats(admin: User = Depends(require_admin)):
    total_users = await users_col.count_documents({})
    total_convs = await conversations_col.count_documents({})
    total_msgs = await messages_col.count_documents({})
    total_ai = await ai_requests_col.count_documents({})
    total_paid_docs = await payment_transactions_col.aggregate([
        {"$match": {"status": "paid"}},
        {"$group": {"_id": "$currency", "total": {"$sum": "$amount"}, "count": {"$sum": 1}}},
    ]).to_list(10)
    return {
        "total_users": total_users,
        "total_conversations": total_convs,
        "total_messages": total_msgs,
        "total_ai_requests": total_ai,
        "revenue": total_paid_docs,
    }


@router.get("/users")
async def list_users(admin: User = Depends(require_admin), limit: int = 100, skip: int = 0, q: str = ""):
    query = {}
    if q:
        query = {"$or": [{"email": {"$regex": q, "$options": "i"}}, {"name": {"$regex": q, "$options": "i"}}]}
    cursor = users_col.find(query).sort("created_at", -1).skip(skip).limit(limit)
    items = []
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        doc.pop("password_hash", None)
        # attach wallet total
        wallet = await wallets_col.find_one({"user_id": doc["id"]})
        if wallet:
            doc["credits_total"] = (
                wallet.get("welcome_credits", 0) + wallet.get("daily_credits", 0)
                + wallet.get("bonus_credits", 0) + wallet.get("referral_credits", 0)
                + wallet.get("promotional_credits", 0) + wallet.get("purchased_credits", 0)
            )
        else:
            doc["credits_total"] = 0
        items.append(doc)
    total = await users_col.count_documents(query)
    return {"items": items, "total": total}


@router.post("/users/{user_id}/toggle-active")
async def toggle_active(user_id: str, admin: User = Depends(require_admin)):
    doc = await users_col.find_one({"_id": ObjectId(user_id)})
    if not doc:
        raise HTTPException(404, "Not found")
    new_active = not doc.get("is_active", True)
    await users_col.update_one({"_id": ObjectId(user_id)}, {"$set": {"is_active": new_active, "updated_at": now_iso()}})
    return {"is_active": new_active}


@router.post("/users/{user_id}/promote")
async def toggle_admin(user_id: str, admin: User = Depends(require_admin)):
    doc = await users_col.find_one({"_id": ObjectId(user_id)})
    if not doc:
        raise HTTPException(404, "Not found")
    new_role = "admin" if doc.get("role") != "admin" else "user"
    await users_col.update_one({"_id": ObjectId(user_id)}, {"$set": {"role": new_role, "updated_at": now_iso()}})
    return {"role": new_role}


@router.post("/wallet/adjust")
async def adjust_wallet(req: AdminUpdateWalletRequest, admin: User = Depends(require_admin)):
    await get_or_create_wallet(req.user_id)
    await add_credits(req.user_id, req.amount, bucket=req.bucket, kind="admin_adjust", description=req.description)
    await notify(req.user_id, "Wallet updated by admin", f"{int(req.amount)} {req.bucket} credits added.", kind="info")
    return {"ok": True}


@router.get("/transactions")
async def list_transactions(admin: User = Depends(require_admin), limit: int = 100, skip: int = 0):
    cursor = payment_transactions_col.find({}).sort("created_at", -1).skip(skip).limit(limit)
    items = []
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        items.append(doc)
    return {"items": items}


# --- Knowledge Bank + Settings ---
from services.knowledge_retriever import stats as kb_stats_fn
from services.settings_service import all_settings, set_setting, get_setting, DEFAULTS


class SettingUpdate(BaseModel):
    key: str
    value: object


@router.get("/kb/stats")
async def kb_stats(admin: User = Depends(require_admin)):
    return await kb_stats_fn()


@router.get("/settings")
async def get_settings(admin: User = Depends(require_admin)):
    current = await all_settings()
    return {"settings": current, "defaults": DEFAULTS}


@router.post("/settings")
async def update_setting(req: SettingUpdate, admin: User = Depends(require_admin)):
    if req.key not in DEFAULTS:
        raise HTTPException(400, f"Unknown setting `{req.key}`")
    # Type-coerce
    default_val = DEFAULTS[req.key]
    value = req.value
    if isinstance(default_val, bool):
        value = bool(value)
    elif isinstance(default_val, float):
        try:
            value = float(value)
        except Exception:
            raise HTTPException(400, "value must be a number")
        if req.key == "kb_similarity_threshold" and not (0.0 <= value <= 1.0):
            raise HTTPException(400, "threshold must be between 0 and 1")
    prev = await get_setting(req.key)
    await set_setting(req.key, value)
    from services.data_lake import log_event
    await log_event(
        "admin_setting_updated",
        user_id=admin.id,
        payload={"key": req.key, "prev": prev, "new": value},
    )
    return {"ok": True, "key": req.key, "value": value}



# --- Admin v2: pricing / plans / provider analytics / query log / user details ---
from services.pricing_engine import (
    list_pricing, set_price, list_plans, set_plan, usage_col, PROVIDER_COST_USD_PER_CREDIT
)
from services.data_lake import events_col
from db import transactions_col, wallets_col
from datetime import datetime as _dt, timedelta as _td, timezone as _tz


class PricingUpdate(BaseModel):
    credit_cost: float
    provider: Optional[str] = None


class PlanUpdate(BaseModel):
    name: Optional[str] = None
    monthly_credits: Optional[float] = None
    window_hours: Optional[int] = None
    window_credits: Optional[float] = None
    price_inr: Optional[float] = None
    price_usd: Optional[float] = None
    billing_period: Optional[str] = None
    is_free: Optional[bool] = None
    one_time: Optional[bool] = None
    name: Optional[str] = None
    monthly_credits: Optional[float] = None
    window_hours: Optional[int] = None
    window_credits: Optional[float] = None
    price_inr: Optional[float] = None
    is_free: Optional[bool] = None
    one_time: Optional[bool] = None


@router.get("/pricing")
async def admin_list_pricing(admin: User = Depends(require_admin)):
    return {"items": await list_pricing()}


@router.patch("/pricing/{service_key}")
async def admin_update_pricing(service_key: str, req: PricingUpdate, admin: User = Depends(require_admin)):
    if req.credit_cost < 0 or req.credit_cost > 10000:
        raise HTTPException(400, "credit_cost out of range")
    await set_price(service_key, req.credit_cost, req.provider)
    from services.data_lake import log_event
    await log_event("admin_pricing_updated", user_id=admin.id,
                    payload={"service_key": service_key, "credit_cost": req.credit_cost, "provider": req.provider})
    return {"ok": True}


@router.get("/plans")
async def admin_list_plans(admin: User = Depends(require_admin)):
    return {"items": await list_plans()}


@router.patch("/plans/{plan_id}")
async def admin_update_plan(plan_id: str, req: PlanUpdate, admin: User = Depends(require_admin)):
    updates = {k: v for k, v in req.dict().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    await set_plan(plan_id, updates)
    from services.data_lake import log_event
    await log_event("admin_plan_updated", user_id=admin.id, payload={"plan_id": plan_id, "updates": updates})
    return {"ok": True}


def _now_utc():
    return _dt.now(_tz.utc)


def _period_start(period: str) -> _dt:
    n = _now_utc()
    if period == "24h": return n - _td(hours=24)
    if period == "7d":  return n - _td(days=7)
    if period == "30d": return n - _td(days=30)
    if period == "90d": return n - _td(days=90)
    return n - _td(days=7)


@router.get("/analytics/provider-usage")
async def analytics_provider_usage(period: str = "7d", admin: User = Depends(require_admin)):
    since = _period_start(period).isoformat()
    pipeline = [
        {"$match": {"created_at": {"$gte": since}}},
        {"$group": {
            "_id": "$provider",
            "credits": {"$sum": "$credits"},
            "cost_usd": {"$sum": "$cost_usd_estimate"},
            "calls": {"$sum": 1},
            "kb_hits": {"$sum": {"$cond": ["$kb_hit", 1, 0]}},
            "tokens_in": {"$sum": "$tokens_in"},
            "tokens_out": {"$sum": "$tokens_out"},
        }},
        {"$sort": {"credits": -1}},
    ]
    items = []
    async for row in usage_col.aggregate(pipeline):
        row["provider"] = row.pop("_id")
        items.append(row)
    return {"period": period, "since": since, "items": items}


@router.get("/analytics/timeseries")
async def analytics_timeseries(period: str = "7d", admin: User = Depends(require_admin)):
    since = _period_start(period).isoformat()
    granularity = "hour" if period == "24h" else "day"
    fmt = "%Y-%m-%dT%H" if granularity == "hour" else "%Y-%m-%d"
    pipeline = [
        {"$match": {"created_at": {"$gte": since}}},
        {"$group": {
            "_id": {"bucket": {"$dateToString": {"format": fmt, "date": {"$toDate": "$created_at"}}}, "provider": "$provider"},
            "credits": {"$sum": "$credits"},
            "cost_usd": {"$sum": "$cost_usd_estimate"},
        }},
        {"$sort": {"_id.bucket": 1}},
    ]
    items = []
    async for row in usage_col.aggregate(pipeline):
        items.append({"bucket": row["_id"]["bucket"], "provider": row["_id"]["provider"],
                      "credits": row["credits"], "cost_usd": row["cost_usd"]})
    return {"period": period, "granularity": granularity, "items": items}


@router.get("/analytics/finance")
async def analytics_finance(period: str = "30d", admin: User = Depends(require_admin)):
    since = _period_start(period).isoformat()
    # Expense: sum cost_usd from ai_usage
    expense_pipeline = [
        {"$match": {"created_at": {"$gte": since}}},
        {"$group": {"_id": None, "cost_usd": {"$sum": "$cost_usd_estimate"}, "credits": {"$sum": "$credits"}}},
    ]
    exp_row = None
    async for r in usage_col.aggregate(expense_pipeline):
        exp_row = r
    expense_usd = float((exp_row or {}).get("cost_usd", 0) or 0)
    # Income: sum positive purchase-kind transactions
    income_pipeline = [
        {"$match": {"created_at": {"$gte": since}, "kind": {"$in": ["purchase", "topup", "subscription"]}, "amount": {"$gt": 0}}},
        {"$group": {"_id": None, "credits_added": {"$sum": "$amount"}, "count": {"$sum": 1}}},
    ]
    inc_row = None
    async for r in transactions_col.aggregate(income_pipeline):
        inc_row = r
    credits_added = float((inc_row or {}).get("credits_added", 0) or 0)
    # ~ estimate income at ₹0.6/credit avg (admin can override later)
    inr_per_credit = 0.6
    income_inr = credits_added * inr_per_credit
    income_usd = income_inr / 84.0
    margin_usd = income_usd - expense_usd
    return {
        "period": period, "since": since,
        "expense_usd": round(expense_usd, 6),
        "income_credits": credits_added,
        "income_inr_estimate": round(income_inr, 4),
        "income_usd_estimate": round(income_usd, 4),
        "margin_usd_estimate": round(margin_usd, 4),
    }


@router.get("/queries")
async def query_log(
    q: Optional[str] = None,
    kind: Optional[str] = None,
    user_id: Optional[str] = None,
    limit: int = 50, skip: int = 0,
    admin: User = Depends(require_admin),
):
    filt = {"event_type": {"$regex": r"^(counseling_|studio_|career_|builder_|chat_)"}}
    if kind: filt["event_type"] = kind
    if user_id: filt["user_id"] = user_id
    if q: filt["$or"] = [
        {"payload.prompt": {"$regex": q, "$options": "i"}},
        {"payload.message": {"$regex": q, "$options": "i"}},
        {"payload.q": {"$regex": q, "$options": "i"}},
    ]
    cursor = events_col.find(filt).sort("created_at", -1).skip(skip).limit(min(limit, 200))
    items = []
    async for d in cursor:
        d["id"] = str(d.pop("_id"))
        items.append(d)
    total = await events_col.count_documents(filt)
    return {"items": items, "total": total, "limit": limit, "skip": skip}


@router.get("/users/{user_id}/details")
async def user_details(user_id: str, admin: User = Depends(require_admin)):
    try:
        u = await users_col.find_one({"_id": ObjectId(user_id)})
    except Exception:
        raise HTTPException(400, "Invalid user id")
    if not u:
        raise HTTPException(404, "User not found")
    u["id"] = str(u.pop("_id"))
    u.pop("password_hash", None)
    u.pop("github_pat", None)
    wallet = await wallets_col.find_one({"user_id": user_id}) or {}
    wallet.pop("_id", None)
    # Last 30d aggregate spend
    since = (_now_utc() - _td(days=30)).isoformat()
    spend_pipeline = [
        {"$match": {"user_id": user_id, "created_at": {"$gte": since}}},
        {"$group": {"_id": "$service_key", "credits": {"$sum": "$credits"}, "calls": {"$sum": 1}}},
        {"$sort": {"credits": -1}},
    ]
    top_services = []
    async for row in usage_col.aggregate(spend_pipeline):
        row["service_key"] = row.pop("_id")
        top_services.append(row)
    # Recent queries
    recent = []
    async for d in events_col.find(
        {"user_id": user_id, "event_type": {"$regex": r"^(counseling_|studio_|career_|builder_|chat_)"}}
    ).sort("created_at", -1).limit(20):
        d["id"] = str(d.pop("_id"))
        recent.append(d)
    return {"user": u, "wallet": wallet, "top_services": top_services, "recent_queries": recent}


# --- Knowledge Engine controls ---
from services.knowledge_engine import status as kb_engine_status, enrich_once as kb_engine_run


@router.get("/kb/engine/status")
async def get_kb_engine_status(admin: User = Depends(require_admin)):
    return await kb_engine_status()


@router.post("/kb/engine/run")
async def trigger_kb_engine(admin: User = Depends(require_admin)):
    """Manually kick off one enrichment pass."""
    import asyncio
    async def _bg():
        try:
            await kb_engine_run(max_prompts=15)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception(f"KB engine run failed: {e}")
    asyncio.create_task(_bg())


# --- Admin v2.1: plan CRUD + discount codes + kb-only-mode ---
from services.pricing_engine import create_plan, delete_plan
from services.discount_service import (
    create_discount, list_discounts, update_discount, delete_discount, validate as validate_discount
)


class PlanCreate(BaseModel):
    plan_id: str = Field(min_length=2, max_length=32)
    name: str
    monthly_credits: float
    window_hours: int = 5
    window_credits: float
    price_usd: float = 0.0
    billing_period: str = "monthly"  # monthly | annual | one_time
    is_free: bool = False
    one_time: bool = False
    priority: int = 99


@router.post("/plans")
async def admin_create_plan(req: PlanCreate, admin: User = Depends(require_admin)):
    try:
        doc = await create_plan(req.plan_id, req.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))
    from services.data_lake import log_event
    await log_event("admin_plan_created", user_id=admin.id, payload={"plan_id": req.plan_id})
    return {"ok": True, "plan": doc}


@router.delete("/plans/{plan_id}")
async def admin_delete_plan(plan_id: str, admin: User = Depends(require_admin)):
    ok = await delete_plan(plan_id)
    if not ok:
        raise HTTPException(400, "Cannot delete this plan (free is protected)")
    from services.data_lake import log_event
    await log_event("admin_plan_deleted", user_id=admin.id, payload={"plan_id": plan_id})
    return {"ok": True}


class DiscountCreate(BaseModel):
    code: str = Field(min_length=3, max_length=32)
    percent_off: float = 0
    flat_off_usd: float = 0
    applies_to: str = "any"
    max_uses: int = 0
    expires_at: Optional[str] = None
    active: bool = True


@router.get("/discounts")
async def admin_list_discounts(admin: User = Depends(require_admin)):
    return {"items": await list_discounts()}


@router.post("/discounts")
async def admin_create_discount(req: DiscountCreate, admin: User = Depends(require_admin)):
    if req.percent_off <= 0 and req.flat_off_usd <= 0:
        raise HTTPException(400, "Provide percent_off or flat_off_usd (or both)")
    try:
        doc = await create_discount(req.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "discount": {**doc, "code": doc.pop("_id")}}


class DiscountUpdate(BaseModel):
    percent_off: Optional[float] = None
    flat_off_usd: Optional[float] = None
    applies_to: Optional[str] = None
    max_uses: Optional[int] = None
    expires_at: Optional[str] = None
    active: Optional[bool] = None


@router.patch("/discounts/{code}")
async def admin_update_discount(code: str, req: DiscountUpdate, admin: User = Depends(require_admin)):
    updates = {k: v for k, v in req.model_dump(exclude_none=True).items()}
    if not updates:
        raise HTTPException(400, "No fields to update")
    await update_discount(code, updates)
    return {"ok": True}


@router.delete("/discounts/{code}")
async def admin_delete_discount(code: str, admin: User = Depends(require_admin)):
    ok = await delete_discount(code)
    if not ok:
        raise HTTPException(404, "Discount not found")
    return {"ok": True}


# --- Admin subscriptions view ---
from services.payments_service import list_subscriptions as _list_subs


@router.get("/subscriptions")
async def admin_subscriptions(limit: int = 100, skip: int = 0, admin: User = Depends(require_admin)):
    return await _list_subs(limit=limit, skip=skip)


class DiscountValidateReq(BaseModel):
    code: str
    base_usd: float
    target_kind: Optional[str] = None


@router.post("/discounts/validate")
async def admin_validate_discount(req: DiscountValidateReq, admin: User = Depends(require_admin)):
    return await validate_discount(req.code, req.base_usd, req.target_kind)

    return {"ok": True, "message": "Knowledge engine pass started in background"}
