"""Payment routes: Razorpay (converts USD packs → INR at checkout) + IAP.

Stripe was removed per product decision — all web payments go through Razorpay,
all mobile subscriptions through App Store / Play Store IAP.
"""
import os
import logging
from fastapi import APIRouter, HTTPException, Depends, Request
from typing import Optional
from pydantic import BaseModel
from bson import ObjectId
import razorpay
from auth import get_current_user
from db import credit_packs_col, payment_transactions_col, now_iso
from models import (
    RazorpayOrderRequest, RazorpayVerifyRequest,
    PaymentTransaction, User
)
from services.credit_service import add_credits
from services.notification_service import notify
from services.payments_service import get_usd_to_inr, round_up_inr
from services.discount_service import validate as validate_discount, increment_use

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/payments", tags=["payments"])

RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")

_razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)) if RAZORPAY_KEY_ID else None


async def _get_pack(slug: str, currency: str = None) -> dict:
    query = {"slug": slug, "is_visible": True}
    if currency:
        query["currency"] = currency
    doc = await credit_packs_col.find_one(query)
    if not doc:
        raise HTTPException(404, "Pack not found")
    doc["id"] = str(doc.pop("_id"))
    return doc


# ================= STRIPE (removed) =================
# All Stripe endpoints were removed. Razorpay is the sole web payment provider.


# ================= RAZORPAY (Payment Links — domain-agnostic, hosted on rzp.io) =================
@router.post("/razorpay/order")
async def create_razorpay_payment_link(req: RazorpayOrderRequest, request: Request, user: User = Depends(get_current_user)):
    """Creates a Razorpay **Payment Link** (hosted at `rzp.io`) so the checkout
    page is served on Razorpay's own domain — bypassing the "unauthorized
    website" block that applies when opening Checkout.js on our own domain
    before the merchant has approved us as an additional website."""
    if not _razorpay_client:
        raise HTTPException(501, "Razorpay not configured")
    pack = await _get_pack(req.pack_slug, "usd")
    price_usd = float(pack["price"])
    discount = None
    if req.discount_code:
        d = await validate_discount(req.discount_code, price_usd, target_kind=f"pack:{req.pack_slug}")
        if not d.get("ok"):
            raise HTTPException(400, f"Discount not applied: {d.get('reason', 'invalid code')}")
        price_usd = d["final_usd"]  # charge the discounted USD
        discount = {"code": req.discount_code.upper(), "discount_usd": d["discount_usd"]}
    fx_rate = await get_usd_to_inr()
    amount_paise = round_up_inr(price_usd * fx_rate) * 100
    credits_val = float(pack["credits"] + pack.get("bonus_credits", 0))
    origin = str(request.headers.get("origin") or request.headers.get("referer") or "").rstrip("/") \
             or os.environ.get("APP_URL", "").rstrip("/")
    callback = f"{origin}/payment-success?provider=razorpay"
    # `reference_id` must be unique per link — used to correlate the webhook /
    # callback back to a specific transaction row.
    import uuid
    # Razorpay requires reference_id to be <= 40 chars
    ref_id = f"iema_{user.id[-6:]}_{uuid.uuid4().hex[:10]}"
    link = _razorpay_client.payment_link.create({
        "amount": amount_paise,
        "currency": "INR",
        "accept_partial": False,
        "reference_id": ref_id,
        "description": f"IEMA.ai — {pack['name']} ({int(credits_val)} credits, ${price_usd:.2f} USD"
                       + (f", code {discount['code']}" if discount else "") + ")",
        "customer": {
            "name": user.name or user.email.split("@")[0],
            "email": user.email,
        },
        "notify": {"sms": False, "email": True},
        "reminder_enable": False,
        "notes": {
            "user_id": user.id, "pack_slug": req.pack_slug,
            "usd_price": str(price_usd), "credits": str(credits_val),
        },
        "callback_url": callback,
        "callback_method": "get",
    })
    tx = PaymentTransaction(
        user_id=user.id,
        provider="razorpay",
        pack_slug=req.pack_slug,
        amount=price_usd,
        currency="usd",
        credits=credits_val,
        order_id=link["id"],   # store payment_link_id here
        status="initiated",
        metadata={"user_id": user.id, "pack_slug": req.pack_slug,
                  "reference_id": ref_id, "amount_paise": amount_paise,
                  "fx_rate": fx_rate, "short_url": link.get("short_url"),
                  "discount": discount},
    )
    await payment_transactions_col.insert_one(tx.to_mongo())
    return {
        "payment_link_id": link["id"],
        "short_url": link.get("short_url"),
        "reference_id": ref_id,
        "amount": amount_paise,
        "currency": "INR",
        "usd_price": price_usd,
        "credits": credits_val,
        "pack": pack,
    }


@router.get("/razorpay/link-status/{link_id}")
async def razorpay_link_status(link_id: str, user: User = Depends(get_current_user)):
    """Poll the Payment Link status server-side after Razorpay redirects the
    user back. Idempotently credits the wallet on the first `paid` sighting."""
    if not _razorpay_client:
        raise HTTPException(501, "Razorpay not configured")
    tx_doc = await payment_transactions_col.find_one({"order_id": link_id, "user_id": user.id})
    if not tx_doc:
        raise HTTPException(404, "Transaction not found")
    tx = PaymentTransaction.from_mongo(tx_doc)
    try:
        link = _razorpay_client.payment_link.fetch(link_id)
    except Exception as e:
        logger.exception(f"payment_link.fetch failed: {e}")
        raise HTTPException(400, "Failed to fetch payment link")
    status = link.get("status")  # 'created' | 'partially_paid' | 'paid' | 'cancelled' | 'expired'
    if status == "paid" and not tx.credited:
        await add_credits(user.id, tx.credits, bucket="purchased", kind="purchase",
                          description=f"Purchase: {tx.pack_slug}",
                          ref_id=link_id)
        await payment_transactions_col.update_one(
            {"order_id": link_id},
            {"$set": {"status": "paid", "credited": True, "updated_at": now_iso()}},
        )
        await notify(user.id, "Purchase successful",
                     f"{int(tx.credits)} credits added to your wallet.", kind="purchase")
        dc = (tx_doc.get("metadata") or {}).get("discount")
        if dc and dc.get("code"):
            await increment_use(dc["code"])
        tx.credited = True
    return {
        "status": status,
        "credited": tx.credited,
        "credits": tx.credits,
        "short_url": link.get("short_url"),
    }


@router.post("/razorpay/verify")
async def verify_razorpay(req: RazorpayVerifyRequest, user: User = Depends(get_current_user)):
    if not _razorpay_client:
        raise HTTPException(501, "Razorpay not configured")
    try:
        _razorpay_client.utility.verify_payment_signature({
            "razorpay_order_id": req.razorpay_order_id,
            "razorpay_payment_id": req.razorpay_payment_id,
            "razorpay_signature": req.razorpay_signature,
        })
    except Exception:
        raise HTTPException(400, "Invalid signature")

    tx_doc = await payment_transactions_col.find_one({"order_id": req.razorpay_order_id, "user_id": user.id})
    if not tx_doc:
        raise HTTPException(404, "Transaction not found")
    tx = PaymentTransaction.from_mongo(tx_doc)

    if not tx.credited:
        await add_credits(user.id, tx.credits, bucket="purchased", kind="purchase", description=f"Purchase: {tx.pack_slug}", ref_id=req.razorpay_payment_id)
        await payment_transactions_col.update_one(
            {"order_id": req.razorpay_order_id},
            {"$set": {"status": "paid", "credited": True, "payment_id": req.razorpay_payment_id, "updated_at": now_iso()}},
        )
        await notify(user.id, "Purchase successful", f"{int(tx.credits)} credits added to your wallet.", kind="purchase")
        dc = (tx_doc.get("metadata") or {}).get("discount")
        if dc and dc.get("code"):
            await increment_use(dc["code"])
    return {"ok": True, "credits": tx.credits}


@router.get("/fx-rate")
async def fx_rate():
    """Current USD→INR rate (live, cached) so the Billing page can show ₹ prices."""
    return {"rate": await get_usd_to_inr(), "currency": "INR"}


class DiscountCheckReq(BaseModel):
    code: str
    pack_slug: str


@router.post("/discount/validate")
async def discount_validate(req: DiscountCheckReq, user: User = Depends(get_current_user)):
    """Customer-facing: check a discount code against a pack's price (no redemption)."""
    pack = await _get_pack(req.pack_slug, "usd")
    res = await validate_discount(req.code, float(pack["price"]), target_kind=f"pack:{req.pack_slug}")
    if res.get("ok"):
        res["final_inr"] = round_up_inr(res["final_usd"] * await get_usd_to_inr())
    return res


@router.get("/plans")
async def list_public_plans():
    """Public list of subscription plans (non-free) shown on the Billing page.
    Admin-only `/admin/plans` returns everything including free — this endpoint
    is what normal users hit."""
    from services.pricing_engine import list_plans
    items = await list_plans()
    return {"items": [p for p in items if not p.get("is_free")]}


@router.get("/history")
async def payment_history(user: User = Depends(get_current_user), limit: int = 50):
    cursor = payment_transactions_col.find({"user_id": user.id}).sort("created_at", -1).limit(limit)
    items = []
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        items.append(doc)
    return {"items": items}


# ==================== Razorpay Subscriptions ====================
from services.payments_service import (
    create_subscription as _rzp_create_sub,
    handle_razorpay_webhook as _rzp_webhook,
    handle_revenuecat_webhook as _revenuecat_webhook,
    verify_apple_receipt as _apple_verify,
    verify_google_receipt as _google_verify,
    DEFAULT_PRODUCT_MAP,
)


@router.post("/subscribe/{plan_id}")
async def create_subscription(plan_id: str, user: User = Depends(get_current_user)):
    try:
        return await _rzp_create_sub(user.id, plan_id)
    except Exception as e:
        raise HTTPException(400, str(e)[:200])


@router.post("/webhook/razorpay-subscription", include_in_schema=False)
async def razorpay_sub_webhook(request: Request):
    signature = request.headers.get("x-razorpay-signature", "")
    body = await request.body()
    res = await _rzp_webhook(body, signature)
    if not res.get("ok"):
        raise HTTPException(400, res.get("reason", "webhook failed"))
    return res


@router.post("/webhook/revenuecat", include_in_schema=False)
async def revenuecat_webhook(request: Request):
    auth_header = request.headers.get("authorization", "")
    body = await request.json()
    res = await _revenuecat_webhook(body, auth_header)
    if not res.get("ok"):
        raise HTTPException(401, res.get("reason", "webhook failed"))
    return res


# ==================== Mobile IAP receipts ====================
class AppleReceiptRequest(BaseModel):
    receipt: str  # base64
    product_map: Optional[dict] = None


class GoogleReceiptRequest(BaseModel):
    product_id: str
    purchase_token: str
    is_subscription: bool = True
    product_map: Optional[dict] = None


@router.post("/iap/apple/verify")
async def iap_apple_verify(req: AppleReceiptRequest, user: User = Depends(get_current_user)):
    mapping = req.product_map or DEFAULT_PRODUCT_MAP
    res = await _apple_verify(user.id, req.receipt, mapping)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error", "invalid receipt"))
    return res


@router.post("/iap/google/verify")
async def iap_google_verify(req: GoogleReceiptRequest, user: User = Depends(get_current_user)):
    mapping = req.product_map or DEFAULT_PRODUCT_MAP
    res = await _google_verify(user.id, req.product_id, req.purchase_token, req.is_subscription, mapping)
    if not res.get("ok"):
        raise HTTPException(400, res.get("error", "invalid receipt"))
    return res

