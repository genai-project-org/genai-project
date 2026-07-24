"""Usage analytics routes."""
from datetime import datetime, timedelta, timezone
from typing import Literal
from fastapi import APIRouter, Depends, Query
from auth import get_current_user
from db import ai_requests_col, transactions_col
from models import User

router = APIRouter(prefix="/usage", tags=["usage"])


def _range_start(period: str) -> datetime:
    now = datetime.now(timezone.utc)
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    if period == "7d":
        return now - timedelta(days=7)
    if period == "30d":
        return now - timedelta(days=30)
    if period == "90d":
        return now - timedelta(days=90)
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


@router.get("/summary")
async def usage_summary(user: User = Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week_ago = (now - timedelta(days=7)).isoformat()
    month_ago = (now - timedelta(days=30)).isoformat()

    async def total_credits(since_iso):
        pipeline = [
            {"$match": {"user_id": user.id, "kind": "ai_usage", "created_at": {"$gte": since_iso}}},
            {"$group": {"_id": None, "total": {"$sum": "$amount"}, "count": {"$sum": 1}}},
        ]
        res = await transactions_col.aggregate(pipeline).to_list(1)
        return (-res[0]["total"] if res else 0.0), (res[0]["count"] if res else 0)

    today_credits, today_count = await total_credits(today)
    week_credits, week_count = await total_credits(week_ago)
    month_credits, month_count = await total_credits(month_ago)
    life_credits, life_count = await total_credits("1970-01-01T00:00:00+00:00")

    avg = (life_credits / life_count) if life_count else 0

    # Most used provider/model
    provider_agg = await ai_requests_col.aggregate([
        {"$match": {"user_id": user.id}},
        {"$group": {"_id": "$provider", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 1},
    ]).to_list(1)
    model_agg = await ai_requests_col.aggregate([
        {"$match": {"user_id": user.id}},
        {"$group": {"_id": "$model", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 1},
    ]).to_list(1)

    return {
        "credits_used_today": today_credits,
        "credits_used_week": week_credits,
        "credits_used_month": month_credits,
        "credits_used_lifetime": life_credits,
        "requests_today": today_count,
        "requests_week": week_count,
        "requests_month": month_count,
        "requests_lifetime": life_count,
        "avg_credits_per_request": round(avg, 2),
        "most_used_provider": provider_agg[0]["_id"] if provider_agg else None,
        "most_used_model": model_agg[0]["_id"] if model_agg else None,
    }


@router.get("/timeline")
async def usage_timeline(
    user: User = Depends(get_current_user),
    period: Literal["today", "7d", "30d", "90d", "lifetime"] = Query("30d"),
):
    start = _range_start(period).isoformat()
    pipeline = [
        {"$match": {"user_id": user.id, "kind": "ai_usage", "created_at": {"$gte": start}}},
        {"$addFields": {"day": {"$substr": ["$created_at", 0, 10]}}},
        {"$group": {"_id": "$day", "credits": {"$sum": {"$multiply": ["$amount", -1]}}, "requests": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    res = await transactions_col.aggregate(pipeline).to_list(1000)
    return {"items": [{"date": r["_id"], "credits": r["credits"], "requests": r["requests"]} for r in res]}


@router.get("/recent")
async def recent_requests(user: User = Depends(get_current_user), limit: int = 20):
    cursor = ai_requests_col.find({"user_id": user.id}).sort("created_at", -1).limit(limit)
    items = []
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        items.append(doc)
    return {"items": items}
