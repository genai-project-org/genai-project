"""Pricing API — the single source of truth every client (web, mobile, admin) reads.

Public:  GET  /pricing            packs + pay-as-you-go + welcome/daily credit copy + service costs
         GET  /pricing/quote      price a custom recharge amount
Admin:   GET/PUT /pricing/admin/config, POST /pricing/admin/preview, POST /pricing/admin/publish,
         GET  /pricing/admin/export?format=csv|json|md   (store product setup table)
"""
import json
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from auth import require_admin
from db import credit_packs_col
from models import User
from services import pack_pricing as pp
from services.credit_service import WELCOME_CREDITS, DAILY_CREDITS
from services.payments_service import get_usd_to_inr

router = APIRouter(prefix="/pricing", tags=["pricing"])


async def _public_packs(fx: float, inr_step: int):
    items = []
    async for d in credit_packs_col.find({"is_visible": True, "currency": "usd"}).sort(
            [("sort_order", 1), ("price", 1)]):
        d["id"] = str(d.pop("_id"))
        total = float(d["credits"]) + float(d.get("bonus_credits", 0))
        d.update({
            "price_usd": float(d["price"]), "price_inr": pp.inr_for_usd(float(d["price"]), fx, inr_step),
            "total_credits": total, "kind": d.get("kind", "general"),
        })
        items.append(d)
    return items


@router.get("")
@router.get("/")
async def public_pricing():
    from services.pricing_engine import list_pricing
    pub = await pp.get_published()
    cfg = pub["config"]
    fx = await get_usd_to_inr()
    step = int(cfg["inr_round_step"])
    cpu = int(pub["credits_per_usd"])
    p = cfg["payg"]
    packs = await _public_packs(fx, step)
    services = [{"service_key": s["service_key"], "category": s.get("category"),
                 "description": s.get("description", ""), "credit_cost": s.get("credit_cost", 0)}
                for s in await list_pricing()]
    return {
        "brand": pp.BRAND,
        "currency": "USD",
        "fx_rate": fx,
        "inr_round_step": step,
        "welcome_credits": WELCOME_CREDITS,
        "daily_credits": DAILY_CREDITS,
        "credits_per_usd": cpu,
        "payg": {
            "min_usd": p["min_usd"], "max_usd": p["max_usd"], "step_usd": p["step_usd"],
            "credits_per_usd": cpu,
            "presets": [{"usd": u, "credits": int(u * cpu), "inr": pp.inr_for_usd(u, fx, step)}
                        for u in p["presets"]],
        },
        "packs": packs,
        "store_products": [{"product_id": x["product_id"], "slug": x["slug"], "price_usd": x["price_usd"],
                            "price_inr": x["price_inr"], "credits": x["total_credits"]}
                           for x in packs if x.get("product_id")],
        "services": services,
    }


@router.get("/quote")
async def quote(amount_usd: float = Query(...)):
    pub = await pp.get_published()
    try:
        return pp.payg_quote(amount_usd, pub["config"], int(pub["credits_per_usd"]), await get_usd_to_inr())
    except ValueError as e:
        raise HTTPException(400, str(e))


# ------------------------------------------------------------------ admin
class ConfigPatch(BaseModel):
    target_margin_pct: Optional[float] = None
    commissions_pct: Optional[Dict[str, float]] = None
    price_basis_channel: Optional[str] = None
    margin_floor_pct: Optional[float] = None
    cost_per_credit_override: Optional[float] = None
    provider_cost_usd_per_credit: Optional[Dict[str, float]] = None
    inr_round_step: Optional[int] = None
    tiers: Optional[list] = None
    specialised: Optional[Dict[str, Any]] = None
    payg: Optional[Dict[str, Any]] = None


def _patch(p: Optional[ConfigPatch]) -> Dict[str, Any]:
    return p.model_dump(exclude_unset=True) if p else {}


@router.get("/admin/config")
async def admin_get_config(admin: User = Depends(require_admin)):
    pub = await pp.pricing_config_col.find_one({"_id": "published"}) or {}
    return {"config": await pp.get_config(), "defaults": pp.DEFAULT_CONFIG,
            "published_at": pub.get("published_at")}


@router.put("/admin/config")
async def admin_save_config(patch: ConfigPatch, admin: User = Depends(require_admin)):
    try:
        return {"config": await pp.save_config(_patch(patch))}
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


@router.post("/admin/preview")
async def admin_preview(patch: Optional[ConfigPatch] = None, admin: User = Depends(require_admin)):
    try:
        return await pp.preview(_patch(patch))
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


@router.post("/admin/publish")
async def admin_publish(patch: Optional[ConfigPatch] = None, admin: User = Depends(require_admin)):
    """Persist the config, (re)write the packs and freeze the PAYG base rate."""
    try:
        return await pp.publish(_patch(patch))
    except (ValueError, KeyError) as e:
        raise HTTPException(400, str(e))


@router.get("/admin/export")
async def admin_export(format: str = Query("json", pattern="^(csv|json|md)$"),
                       admin: User = Depends(require_admin)):
    """Published pack table (product IDs + prices) for creating store products."""
    pub = await pp.get_published()
    cfg, cost = pub["config"], float(pub["cost_per_credit_usd"])
    fx = await get_usd_to_inr()
    step = int(cfg["inr_round_step"])
    packs = await _public_packs(fx, step)
    table = {"packs": [{
        "product_id": x.get("product_id", ""), "name": x["name"], "kind": x["kind"],
        "category": x.get("category"), "price_usd": x["price_usd"], "price_inr": x["price_inr"],
        "total_credits": x["total_credits"],
        "margin_pct": {ch: pp.margin_pct_after_commission(x["price_usd"], x["total_credits"], cost, c)
                       for ch, c in cfg["commissions_pct"].items()},
    } for x in packs]}
    if format == "json":
        return PlainTextResponse(json.dumps(table["packs"], indent=2), media_type="application/json")
    media = "text/csv" if format == "csv" else "text/markdown"
    ext = "csv" if format == "csv" else "md"
    return PlainTextResponse(pp.export_text(table, format), media_type=media,
                             headers={"Content-Disposition": f'attachment; filename="iema-store-products.{ext}"'})
