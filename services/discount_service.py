"""Discount code service — admin-managed promo codes."""
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from db import db, now_iso

logger = logging.getLogger(__name__)

discounts_col = db["discounts"]


async def create_discount(data: Dict[str, Any]) -> Dict[str, Any]:
    code = (data.get("code") or "").strip().upper()
    if not code or not code.isalnum() or len(code) < 3:
        raise ValueError("code must be 3+ alphanumeric characters")
    existing = await discounts_col.find_one({"_id": code})
    if existing:
        raise ValueError(f"Discount `{code}` already exists")
    doc = {
        "_id": code,
        "percent_off": float(data.get("percent_off") or 0),
        "flat_off_usd": float(data.get("flat_off_usd") or 0),
        "applies_to": data.get("applies_to") or "any",   # any | plan:<id> | pack:<id>
        "max_uses": int(data.get("max_uses") or 0),      # 0 = unlimited
        "uses": 0,
        "expires_at": data.get("expires_at"),            # ISO string or null
        "active": bool(data.get("active", True)),
        "created_at": now_iso(),
    }
    await discounts_col.insert_one(doc)
    return doc


async def list_discounts() -> list:
    items = []
    async for d in discounts_col.find({}).sort("created_at", -1):
        d["code"] = d.pop("_id")
        items.append(d)
    return items


async def update_discount(code: str, updates: Dict[str, Any]) -> None:
    code = code.upper()
    allowed = {"percent_off", "flat_off_usd", "applies_to", "max_uses", "expires_at", "active"}
    clean = {k: v for k, v in updates.items() if k in allowed}
    clean["updated_at"] = now_iso()
    await discounts_col.update_one({"_id": code}, {"$set": clean})


async def delete_discount(code: str) -> bool:
    res = await discounts_col.delete_one({"_id": code.upper()})
    return res.deleted_count > 0


async def increment_use(code: str) -> None:
    """Count one redemption (called only after a payment is confirmed)."""
    await discounts_col.update_one({"_id": (code or "").upper()}, {"$inc": {"uses": 1}})


async def validate(code: str, base_usd: float, target_kind: Optional[str] = None) -> Dict[str, Any]:
    """Return {ok, discount_usd, final_usd, reason?}."""
    code = (code or "").strip().upper()
    if not code:
        return {"ok": False, "reason": "empty code"}
    doc = await discounts_col.find_one({"_id": code})
    if not doc:
        return {"ok": False, "reason": "code not found"}
    if not doc.get("active", True):
        return {"ok": False, "reason": "discount inactive"}
    if doc.get("expires_at"):
        try:
            exp = datetime.fromisoformat(doc["expires_at"])
            if exp.tzinfo is None: exp = exp.replace(tzinfo=timezone.utc)
            if exp < datetime.now(timezone.utc):
                return {"ok": False, "reason": "code expired"}
        except Exception:
            pass
    max_u = int(doc.get("max_uses") or 0)
    if max_u and doc.get("uses", 0) >= max_u:
        return {"ok": False, "reason": "code fully redeemed"}
    applies = doc.get("applies_to", "any")
    if applies != "any" and target_kind and applies != target_kind:
        return {"ok": False, "reason": f"discount only applies to {applies}"}
    percent = float(doc.get("percent_off") or 0)
    flat = float(doc.get("flat_off_usd") or 0)
    discount_usd = min(base_usd, base_usd * (percent / 100.0) + flat)
    final = max(0.0, base_usd - discount_usd)
    return {"ok": True, "discount_usd": round(discount_usd, 2), "final_usd": round(final, 2),
            "code": code, "percent_off": percent, "flat_off_usd": flat}
