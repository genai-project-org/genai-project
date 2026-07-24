"""Payments — Razorpay (web) + Apple IAP + Google Play IAP.

All three call `_credit_plan(user_id, plan_id, source, ref_id)` on success — one code path.
"""
import os
import json
import logging
from typing import Optional, Dict, Any
import httpx
from bson import ObjectId
import razorpay
from db import db, now_iso, users_col
from services.pricing_engine import get_plan, assign_plan
from services.data_lake import log_event

logger = logging.getLogger(__name__)

RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
APPLE_APP_STORE_SHARED_SECRET = os.environ.get("APPLE_APP_STORE_SHARED_SECRET", "")
GOOGLE_PLAY_SA_JSON = os.environ.get("GOOGLE_PLAY_SA_JSON", "")
GOOGLE_PLAY_PACKAGE = os.environ.get("GOOGLE_PLAY_PACKAGE", "com.iemaai.app")

subscriptions_col = db["subscriptions"]
iap_receipts_col = db["iap_receipts"]

_rzp = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)) if RAZORPAY_KEY_ID else None


# ==================== plan crediting ====================
async def _credit_plan(user_id: str, plan_id: str, source: str, ref_id: str) -> None:
    plan = await get_plan(plan_id)
    if not plan or not plan.get("plan_id"):
        logger.warning(f"Unknown plan_id={plan_id} for {source} {ref_id}")
        return
    await assign_plan(user_id, plan_id, add_monthly_credits=True)
    await subscriptions_col.update_one(
        {"user_id": user_id, "source": source, "ref_id": ref_id},
        {"$set": {
            "user_id": user_id, "plan_id": plan_id, "source": source, "ref_id": ref_id,
            "status": "active", "granted_at": now_iso(), "credits_granted": plan.get("monthly_credits"),
        }},
        upsert=True,
    )
    await log_event("subscription_granted", user_id=user_id,
                    payload={"plan_id": plan_id, "source": source, "ref_id": ref_id})


# ==================== Razorpay subscriptions ====================
_razorpay_plan_map_col = db["razorpay_plan_map"]  # {_id: iema_plan_id, rzp_plan_id}


async def get_or_create_rzp_plan(iema_plan_id: str) -> str:
    """Ensure a Razorpay plan exists for our IEMA plan. Returns Razorpay plan_id."""
    if not _rzp:
        raise RuntimeError("Razorpay not configured")
    existing = await _razorpay_plan_map_col.find_one({"_id": iema_plan_id})
    if existing and existing.get("rzp_plan_id"):
        return existing["rzp_plan_id"]
    plan = await get_plan(iema_plan_id)
    if not plan or plan.get("is_free"):
        raise RuntimeError(f"Cannot subscribe to plan `{iema_plan_id}`")
    period = "yearly" if plan.get("billing_period") == "annual" else "monthly"
    # Razorpay India accounts only support INR. Convert USD → INR at ~₹85/USD.
    price_usd = float(plan.get("price_usd") or 0)
    price_inr = float(plan.get("price_inr") or (price_usd * 85))
    amount = int(round(price_inr * 100))  # paise
    rzp_plan = _rzp.plan.create({
        "period": period, "interval": 1,
        "item": {"name": plan.get("name", iema_plan_id), "amount": amount, "currency": "INR",
                 "description": f"IEMA.ai {plan.get('name', iema_plan_id)}"},
    })
    rzp_id = rzp_plan["id"]
    await _razorpay_plan_map_col.update_one(
        {"_id": iema_plan_id},
        {"$set": {"rzp_plan_id": rzp_id, "created_at": now_iso()}}, upsert=True,
    )
    return rzp_id


async def create_subscription(user_id: str, iema_plan_id: str) -> Dict[str, Any]:
    if not _rzp:
        raise RuntimeError("Razorpay not configured")
    rzp_plan_id = await get_or_create_rzp_plan(iema_plan_id)
    total_count = 12 if (await get_plan(iema_plan_id)).get("billing_period") == "monthly" else 5
    sub = _rzp.subscription.create({
        "plan_id": rzp_plan_id, "total_count": total_count,
        "customer_notify": 1,
        "notes": {"user_id": user_id, "iema_plan": iema_plan_id},
    })
    await subscriptions_col.insert_one({
        "user_id": user_id, "plan_id": iema_plan_id, "source": "razorpay",
        "ref_id": sub["id"], "status": "created", "created_at": now_iso(),
    })
    return {"subscription_id": sub["id"], "short_url": sub.get("short_url"),
            "razorpay_key": RAZORPAY_KEY_ID}


async def handle_razorpay_webhook(body: bytes, signature: str) -> Dict[str, Any]:
    if not _rzp:
        return {"ok": False, "reason": "razorpay not configured"}
    webhook_secret = os.environ.get("RAZORPAY_WEBHOOK_SECRET", RAZORPAY_KEY_SECRET)
    try:
        _rzp.utility.verify_webhook_signature(body.decode(), signature, webhook_secret)
    except Exception as e:
        logger.warning(f"Razorpay webhook signature invalid: {e}")
        return {"ok": False, "reason": "bad signature"}
    payload = json.loads(body)
    event = payload.get("event", "")
    if event in ("subscription.charged", "subscription.activated"):
        sub = payload.get("payload", {}).get("subscription", {}).get("entity", {})
        user_id = (sub.get("notes") or {}).get("user_id")
        iema_plan = (sub.get("notes") or {}).get("iema_plan")
        if user_id and iema_plan:
            await _credit_plan(user_id, iema_plan, "razorpay", sub.get("id", ""))
    elif event == "subscription.cancelled":
        sub = payload.get("payload", {}).get("subscription", {}).get("entity", {})
        await subscriptions_col.update_one({"ref_id": sub.get("id")}, {"$set": {"status": "cancelled"}})
    return {"ok": True, "event": event}


# ==================== Apple App Store IAP ====================
APPLE_VERIFY_PROD = "https://buy.itunes.apple.com/verifyReceipt"
APPLE_VERIFY_SANDBOX = "https://sandbox.itunes.apple.com/verifyReceipt"


async def verify_apple_receipt(user_id: str, receipt_b64: str, product_to_plan: Dict[str, str]) -> Dict[str, Any]:
    """Verify an Apple receipt. Auto-fallback to sandbox on status 21007."""
    payload = {"receipt-data": receipt_b64,
               "password": APPLE_APP_STORE_SHARED_SECRET,
               "exclude-old-transactions": True}
    async with httpx.AsyncClient(timeout=20) as http:
        r = await http.post(APPLE_VERIFY_PROD, json=payload)
        data = r.json()
        if data.get("status") == 21007:  # sandbox receipt used against prod
            r = await http.post(APPLE_VERIFY_SANDBOX, json=payload)
            data = r.json()
    if data.get("status") != 0:
        return {"ok": False, "status": data.get("status"), "error": "Apple receipt invalid"}
    receipt = data.get("receipt", {})
    latest = data.get("latest_receipt_info") or receipt.get("in_app", [])
    if not latest:
        return {"ok": False, "error": "no purchases in receipt"}
    purchase = latest[-1]
    product_id = purchase.get("product_id")
    txn_id = purchase.get("transaction_id")
    iema_plan = product_to_plan.get(product_id)
    if not iema_plan:
        return {"ok": False, "error": f"unknown product {product_id}"}
    # Idempotency check
    existing = await iap_receipts_col.find_one({"txn_id": txn_id})
    if existing:
        return {"ok": True, "already_processed": True, "plan_id": iema_plan}
    await iap_receipts_col.insert_one({
        "user_id": user_id, "store": "apple", "product_id": product_id,
        "txn_id": txn_id, "raw": receipt_b64[:2000], "created_at": now_iso(),
    })
    await _credit_plan(user_id, iema_plan, "apple", txn_id)
    return {"ok": True, "plan_id": iema_plan, "product_id": product_id, "txn_id": txn_id}


# ==================== Google Play IAP ====================
def _google_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    if not GOOGLE_PLAY_SA_JSON or not os.path.exists(GOOGLE_PLAY_SA_JSON):
        raise RuntimeError("GOOGLE_PLAY_SA_JSON not configured or missing")
    creds = service_account.Credentials.from_service_account_file(
        GOOGLE_PLAY_SA_JSON, scopes=["https://www.googleapis.com/auth/androidpublisher"],
    )
    return build("androidpublisher", "v3", credentials=creds, cache_discovery=False)


async def verify_google_receipt(user_id: str, product_id: str, purchase_token: str,
                                is_subscription: bool, product_to_plan: Dict[str, str]) -> Dict[str, Any]:
    """Verify a Google Play purchase (product or subscription)."""
    import asyncio
    try:
        svc = _google_service()
    except Exception as e:
        return {"ok": False, "error": f"google svc init failed: {e}"}

    def _call():
        if is_subscription:
            return svc.purchases().subscriptions().get(
                packageName=GOOGLE_PLAY_PACKAGE, subscriptionId=product_id, token=purchase_token
            ).execute()
        return svc.purchases().products().get(
            packageName=GOOGLE_PLAY_PACKAGE, productId=product_id, token=purchase_token
        ).execute()

    try:
        info = await asyncio.to_thread(_call)
    except Exception as e:
        return {"ok": False, "error": f"google verify failed: {str(e)[:200]}"}

    # Ack state 1 = purchased/active
    state_key = "paymentState" if is_subscription else "purchaseState"
    state = info.get(state_key, 0)
    if is_subscription and state not in (1,):
        return {"ok": False, "error": f"subscription state={state}"}
    if not is_subscription and state != 0:  # 0 = purchased for products
        return {"ok": False, "error": f"purchase state={state}"}

    iema_plan = product_to_plan.get(product_id)
    if not iema_plan:
        return {"ok": False, "error": f"unknown product {product_id}"}
    existing = await iap_receipts_col.find_one({"txn_id": purchase_token})
    if existing:
        return {"ok": True, "already_processed": True, "plan_id": iema_plan}
    await iap_receipts_col.insert_one({
        "user_id": user_id, "store": "google", "product_id": product_id,
        "txn_id": purchase_token, "raw": json.dumps(info)[:2000], "created_at": now_iso(),
    })
    await _credit_plan(user_id, iema_plan, "google", purchase_token)
    return {"ok": True, "plan_id": iema_plan, "product_id": product_id}


# ==================== admin queries ====================
async def list_subscriptions(limit: int = 100, skip: int = 0) -> Dict[str, Any]:
    items = []
    async for d in subscriptions_col.find({}).sort("created_at", -1).skip(skip).limit(limit):
        d["id"] = str(d.pop("_id"))
        # Enrich with user email
        try:
            u = await users_col.find_one({"_id": ObjectId(d["user_id"])}, {"email": 1})
            d["email"] = (u or {}).get("email")
        except Exception:
            d["email"] = None
        items.append(d)
    total = await subscriptions_col.count_documents({})
    return {"items": items, "total": total}


# Product IDs → IEMA plan mapping (both stores). Admin can override in DB later.
DEFAULT_PRODUCT_MAP = {
    "iema.pro.monthly": "pro",
    "iema.pro.annual": "pro_annual",
    "iema.team.monthly": "team",
    "iema.team.annual": "team_annual",
}
