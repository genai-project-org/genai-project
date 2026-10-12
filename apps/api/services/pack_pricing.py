"""Pack + pay-as-you-go pricing engine — ONE source of truth for what a credit costs.

Everything user-facing (Landing, Billing, Usage, mobile, Admin, store product export)
reads the output of this module through `GET /api/pricing`.

Inputs
  * the product catalog  -> `pricing_engine.pricing_col` (credit cost + provider per service)
  * provider cost / credit -> `pricing_engine.PROVIDER_COST_USD_PER_CREDIT` (admin-overridable)
  * admin config          -> target PROFIT margin %, per-channel commission %, tiers
  * live FX               -> `payments_service.get_usd_to_inr`

Maths (margin is on NET revenue, i.e. after the store / gateway commission):
    net      = price * (1 - commission)
    profit   = net - credits * cost_per_credit
    margin   = profit / net
  =>  price_per_credit = cost / ((1 - margin) * (1 - commission))

Prices must be identical across channels (same product has to exist at the same
price in Play Console / App Store Connect), so the engine prices against the most
expensive channel by default (`price_basis_channel = "max"`) and reports the real
margin per channel.

PAYG and packs share the SAME base rate (`credits_per_usd`); a pack is that rate
plus a volume / specialisation bonus, capped so the worst-channel margin never drops
below `margin_floor_pct`.

The pure functions below have no I/O so they are unit-testable.
"""
import copy
import csv
import io
import math
from typing import Any, Dict, List, Optional

from db import db, now_iso

pricing_config_col = db["pricing_config"]

BRAND = "IEMA.ai"
PAYG_HARD_MIN_USD = 20.0  # product rule; config may raise it but never lower it

DEFAULT_CONFIG: Dict[str, Any] = {
    "target_margin_pct": 40.0,
    # Razorpay 2% + 18% GST on the fee = 2.36%. Apple/Google: 15% (small-business / first $1M)
    # up to 30% standard. Defaults are the conservative (30%) figure.
    "commissions_pct": {"razorpay": 2.36, "apple": 30.0, "google": 30.0},
    "price_basis_channel": "max",
    "margin_floor_pct": 20.0,
    "cost_per_credit_override": None,
    "provider_cost_usd_per_credit": {},   # merged over PROVIDER_COST_USD_PER_CREDIT
    "rate_round_step": 5,                  # credits-per-USD is floored to a multiple of this
    "credit_round_step": 10,               # pack credits are floored to a multiple of this
    "inr_round_step": 50,                  # INR figures are ceil'd to this
    "tiers": [
        {"key": "spark", "name": "Spark", "usd": 4.99, "bonus_pct": 0, "description": "Try it out"},
        {"key": "boost", "name": "Boost", "usd": 9.99, "bonus_pct": 5, "description": "Regular use"},
        {"key": "surge", "name": "Surge", "usd": 19.99, "bonus_pct": 10, "description": "Best for most people", "popular": True},
        {"key": "turbo", "name": "Turbo", "usd": 49.99, "bonus_pct": 15, "description": "Heavy users"},
        {"key": "titan", "name": "Titan", "usd": 99.99, "bonus_pct": 20, "description": "Teams & creators"},
    ],
    "specialised": {"enabled": True, "tier_usd": 9.99, "bonus_pct": 10, "categories": None},
    "payg": {"min_usd": PAYG_HARD_MIN_USD, "max_usd": 2000.0, "step_usd": 5.0, "presets": [20, 50, 100]},
}

CATEGORY_LABELS = {
    "chat": "Chat",
    "studio": "Studio",
    "career": "Career & Resume",
    "counseling": "Counseling",
    "builder": "Builder",
    "interview": "Interview",
    "hackathon": "Hackathon",
    "contest": "Contest",
}
CATEGORY_BLURB = {
    "chat": "AI workspace conversations",
    "studio": "Image & video generation",
    "career": "Resume analysis & learning paths",
    "counseling": "Career, academic & wellness counseling",
    "builder": "Code Builder projects",
    "interview": "Mock interview sessions",
    "hackathon": "Hackathon tooling",
    "contest": "Contest entries",
}


# ------------------------------------------------------------------ pure helpers
def merge_config(base: Dict[str, Any], patch: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for k, v in (patch or {}).items():
        if k in ("commissions_pct", "payg", "specialised", "provider_cost_usd_per_credit") and isinstance(v, dict):
            out[k] = {**out.get(k, {}), **v}
        elif v is not None or k in ("cost_per_credit_override",):
            out[k] = v
    return out


def validate_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Raises ValueError on nonsense; returns the cleaned config."""
    m = float(cfg["target_margin_pct"])
    if not (0 <= m < 90):
        raise ValueError("target_margin_pct must be between 0 and 90")
    for ch, c in cfg["commissions_pct"].items():
        if not (0 <= float(c) < 60):
            raise ValueError(f"commission for {ch} must be between 0 and 60")
        cfg["commissions_pct"][ch] = float(c)
    cfg["target_margin_pct"] = m
    cfg["margin_floor_pct"] = float(cfg.get("margin_floor_pct", 0))
    p = cfg["payg"]
    p["min_usd"] = max(PAYG_HARD_MIN_USD, float(p.get("min_usd", PAYG_HARD_MIN_USD)))
    p["max_usd"] = max(p["min_usd"], float(p.get("max_usd", 2000)))
    p["step_usd"] = max(1.0, float(p.get("step_usd", 5)))
    p["presets"] = sorted({float(x) for x in p.get("presets", []) if float(x) >= p["min_usd"]}) or [p["min_usd"]]
    tiers = cfg.get("tiers") or []
    if not tiers:
        raise ValueError("at least one tier is required")
    keys = set()
    for t in tiers:
        if not t.get("key") or t["key"] in keys:
            raise ValueError("tier keys must be unique and non-empty")
        keys.add(t["key"])
        t["usd"] = float(t["usd"])
        t["bonus_pct"] = float(t.get("bonus_pct", 0))
        if t["usd"] <= 0:
            raise ValueError("tier price must be positive")
    return cfg


def effective_commission_pct(cfg: Dict[str, Any]) -> float:
    basis = cfg.get("price_basis_channel", "max")
    comms = cfg["commissions_pct"]
    if basis == "max" or basis not in comms:
        return max(float(v) for v in comms.values())
    return float(comms[basis])


def blended_cost_per_credit(catalog: List[Dict[str, Any]], cfg: Dict[str, Any],
                            usage_credits_by_provider: Optional[Dict[str, float]] = None) -> float:
    """Estimated provider $ per credit. Override > usage-weighted > catalog average."""
    if cfg.get("cost_per_credit_override"):
        return float(cfg["cost_per_credit_override"])
    from services.pricing_engine import PROVIDER_COST_USD_PER_CREDIT
    costs = {**PROVIDER_COST_USD_PER_CREDIT, **(cfg.get("provider_cost_usd_per_credit") or {})}
    default = 0.001
    usage = {k: v for k, v in (usage_credits_by_provider or {}).items() if v and k in costs}
    if sum(usage.values()) >= 500:
        total = sum(usage.values())
        return sum(costs[p] * v for p, v in usage.items()) / total
    billable = [s for s in catalog if float(s.get("credit_cost", 0)) > 0]
    if not billable:
        return default
    return sum(costs.get(s.get("provider"), default) for s in billable) / len(billable)


def price_per_credit(cost: float, margin_pct: float, commission_pct: float) -> float:
    return cost / ((1 - margin_pct / 100.0) * (1 - commission_pct / 100.0))


def credits_per_usd(cost: float, margin_pct: float, commission_pct: float, step: int = 5) -> int:
    """Credits a customer gets per $1. Floored to a clean number so margin is >= target."""
    raw = 1.0 / price_per_credit(cost, margin_pct, commission_pct)
    return max(1, int(math.floor(raw / step) * step) or 1)


def margin_pct_after_commission(price_usd: float, credits: float, cost: float, commission_pct: float) -> float:
    net = price_usd * (1 - commission_pct / 100.0)
    if net <= 0:
        return 0.0
    return round((net - credits * cost) / net * 100.0, 2)


def ceil_to_step(x: float, step: float) -> int:
    return int(math.ceil(round(x, 6) / step) * step)


def inr_for_usd(usd: float, fx_rate: float, step: int = 50) -> int:
    """Clean INR figure, always rounded UP so a dip in FX never undercharges."""
    return ceil_to_step(usd * fx_rate, step)


def payg_quote(amount_usd: float, cfg: Dict[str, Any], base_cpu: int, fx_rate: float) -> Dict[str, Any]:
    """Validates and prices a custom recharge. Raises ValueError on a bad amount."""
    p = cfg["payg"]
    amt = round(float(amount_usd), 2)
    if amt < max(PAYG_HARD_MIN_USD, p["min_usd"]):
        raise ValueError(f"Minimum recharge is ${p['min_usd']:.0f}")
    if amt > p["max_usd"]:
        raise ValueError(f"Maximum recharge is ${p['max_usd']:.0f}")
    return {
        "amount_usd": amt,
        "credits": int(math.floor(amt * base_cpu)),
        "amount_inr": inr_for_usd(amt, fx_rate, int(cfg["inr_round_step"])),
        "credits_per_usd": base_cpu,
    }


def _credits_for(price: float, base_cpu: int, bonus_pct: float, cost: float, worst_comm: float,
                 floor_pct: float, step: int) -> Dict[str, int]:
    base = int(math.floor(price * base_cpu / step) * step)
    wanted = int(math.floor(price * base_cpu * (1 + bonus_pct / 100.0) / step) * step)
    # most credits we can hand out while still clearing the margin floor on the worst channel
    net = price * (1 - worst_comm / 100.0)
    cap = int(math.floor(net * (1 - floor_pct / 100.0) / cost / step) * step) if cost > 0 else wanted
    total = max(base, min(wanted, cap))
    return {"base": base, "bonus": total - base, "total": total}


def _category_stats(catalog: List[Dict[str, Any]], total_credits: int) -> List[Dict[str, Any]]:
    out = []
    for s in sorted((x for x in catalog if float(x.get("credit_cost", 0)) > 0),
                    key=lambda x: float(x["credit_cost"])):
        out.append({"service_key": s["service_key"], "description": s.get("description", s["service_key"]),
                    "units": int(total_credits // float(s["credit_cost"]))})
    return out


def compute_pricing(catalog: List[Dict[str, Any]], cfg: Dict[str, Any], fx_rate: float,
                    usage_credits_by_provider: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Pure: catalog + config + fx -> full pricing table (packs, payg, per-service)."""
    cfg = validate_config(copy.deepcopy(cfg))
    margin = cfg["target_margin_pct"]
    comms = cfg["commissions_pct"]
    worst = max(comms.values())
    basis = effective_commission_pct(cfg)
    cost = blended_cost_per_credit(catalog, cfg, usage_credits_by_provider)
    cpu = credits_per_usd(cost, margin, basis, int(cfg["rate_round_step"]))
    cstep = int(cfg["credit_round_step"])
    inr_step = int(cfg["inr_round_step"])
    floor_pct = float(cfg["margin_floor_pct"])

    def build(key, name, usd, bonus_pct, kind, category, description, sort, popular=False, highlights=None):
        cr = _credits_for(usd, cpu, bonus_pct, cost, worst, floor_pct, cstep)
        pid = f"iema.pack.{key}"
        return {
            "slug": key, "product_id": pid, "name": name, "kind": kind, "category": category,
            "description": description, "price_usd": usd, "price_inr": inr_for_usd(usd, fx_rate, inr_step),
            "credits": cr["base"], "bonus_credits": cr["bonus"], "total_credits": cr["total"],
            "credits_per_usd": round(cr["total"] / usd, 1),
            "value_vs_payg_pct": round((cr["total"] / (usd * cpu) - 1) * 100, 1),
            "margin_pct": {ch: margin_pct_after_commission(usd, cr["total"], cost, c) for ch, c in comms.items()},
            "is_popular": popular, "sort_order": sort, "highlights": highlights or [],
        }

    packs = []
    for i, t in enumerate(cfg["tiers"]):
        packs.append(build(t["key"], t["name"], t["usd"], t["bonus_pct"], "general", None,
                           t.get("description", ""), i + 1, bool(t.get("popular"))))

    sp = cfg["specialised"]
    if sp.get("enabled"):
        cats = {}
        for s in catalog:
            if float(s.get("credit_cost", 0)) > 0:
                cats.setdefault(s.get("category") or "other", []).append(s)
        wanted = sp.get("categories")
        for j, cat in enumerate(sorted(cats)):
            if wanted and cat not in wanted:
                continue
            label = CATEGORY_LABELS.get(cat, cat.title())
            pk = build(f"{cat}", f"{label} Pack", float(sp["tier_usd"]), float(sp["bonus_pct"]),
                       "specialised", cat, CATEGORY_BLURB.get(cat, f"{label} credits"), 100 + j)
            pk["highlights"] = _category_stats(cats[cat], pk["total_credits"])[:4]
            packs.append(pk)

    from services.pricing_engine import PROVIDER_COST_USD_PER_CREDIT
    pcosts = {**PROVIDER_COST_USD_PER_CREDIT, **(cfg.get("provider_cost_usd_per_credit") or {})}
    ppc = price_per_credit(cost, margin, basis)
    services = []
    for s in sorted(catalog, key=lambda x: (x.get("category") or "", x["service_key"])):
        cc = float(s.get("credit_cost", 0))
        pc = pcosts.get(s.get("provider"), 0.001) * cc
        services.append({"service_key": s["service_key"], "category": s.get("category"),
                         "provider": s.get("provider"), "credit_cost": cc,
                         "provider_cost_usd": round(pc, 5),
                         "list_price_usd": round(cc / cpu, 5)})

    p = cfg["payg"]
    return {
        "config": cfg,
        "fx_rate": fx_rate,
        "cost_per_credit_usd": round(cost, 6),
        "price_per_credit_usd": round(ppc, 6),
        "basis_commission_pct": basis,
        "credits_per_usd": cpu,
        "payg": {
            "min_usd": p["min_usd"], "max_usd": p["max_usd"], "step_usd": p["step_usd"],
            "presets": [{"usd": u, "credits": int(math.floor(u * cpu)),
                         "inr": inr_for_usd(u, fx_rate, inr_step)} for u in p["presets"]],
            "credits_per_usd": cpu, "inr_per_usd": round(fx_rate, 2),
            "inr_round_step": inr_step,
        },
        "packs": packs,
        "services": services,
    }


# ------------------------------------------------------------------ exports
def export_rows(table: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for p in table["packs"]:
        rows.append({
            "product_id": p["product_id"], "name": p["name"], "type": "consumable",
            "kind": p["kind"], "category": p.get("category") or "",
            "price_usd": f"{p['price_usd']:.2f}", "price_inr": p["price_inr"],
            "credits": p["total_credits"],
            **{f"margin_{ch}_pct": m for ch, m in p["margin_pct"].items()},
        })
    return rows


def export_text(table: Dict[str, Any], fmt: str) -> str:
    rows = export_rows(table)
    if fmt == "csv":
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
        return buf.getvalue()
    if fmt == "md":
        cols = list(rows[0].keys())
        lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
        for r in rows:
            lines.append("| " + " | ".join(str(r[c]) for c in cols) + " |")
        return "\n".join(lines) + "\n"
    raise ValueError("fmt must be csv|md|json")


# ------------------------------------------------------------------ persistence
async def get_config() -> Dict[str, Any]:
    doc = await pricing_config_col.find_one({"_id": "config"}) or {}
    doc.pop("_id", None)
    doc.pop("updated_at", None)
    return merge_config(DEFAULT_CONFIG, doc)


async def save_config(patch: Dict[str, Any]) -> Dict[str, Any]:
    cfg = validate_config(merge_config(await get_config(), patch))
    await pricing_config_col.update_one({"_id": "config"}, {"$set": {**cfg, "updated_at": now_iso()}}, upsert=True)
    return cfg


async def _catalog() -> List[Dict[str, Any]]:
    from services.pricing_engine import list_pricing
    return await list_pricing()


async def _usage_by_provider(days: int = 30) -> Dict[str, float]:
    from datetime import timedelta
    from db import now_utc
    from services.pricing_engine import usage_col
    since = (now_utc() - timedelta(days=days)).isoformat()
    out: Dict[str, float] = {}
    async for r in usage_col.aggregate([
        {"$match": {"created_at": {"$gte": since}, "kb_hit": {"$ne": True}}},
        {"$group": {"_id": "$provider", "c": {"$sum": "$credits"}}},
    ]):
        out[r["_id"]] = float(r["c"])
    return out


async def preview(patch: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from services.payments_service import get_usd_to_inr
    cfg = merge_config(await get_config(), patch)
    return compute_pricing(await _catalog(), cfg, await get_usd_to_inr(), await _usage_by_provider())


async def publish(patch: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Compute + persist config, write the packs, and freeze the PAYG base rate."""
    from db import credit_packs_col
    if patch:
        await save_config(patch)
    table = await preview()
    slugs = []
    for p in table["packs"]:
        doc = {
            "name": p["name"], "slug": p["slug"], "description": p["description"],
            "price": p["price_usd"], "currency": "usd",
            "credits": float(p["credits"]), "bonus_credits": float(p["bonus_credits"]),
            "is_popular": p["is_popular"], "is_visible": True, "sort_order": p["sort_order"],
            "product_id": p["product_id"], "kind": p["kind"], "category": p["category"],
            "highlights": p["highlights"], "managed": True, "updated_at": now_iso(),
        }
        await credit_packs_col.update_one({"slug": p["slug"], "currency": "usd"},
                                          {"$set": doc, "$setOnInsert": {"created_at": now_iso()}}, upsert=True)
        slugs.append(p["slug"])
    # drop stale managed packs and the legacy seeded Starter/Standard/Pro/Business packs (+ INR twins)
    legacy = [f"{n}-{c}" for n in ("starter", "standard", "pro", "business") for c in ("usd", "inr")]
    await credit_packs_col.delete_many({"$or": [
        {"managed": True, "slug": {"$nin": slugs}},
        {"slug": {"$in": legacy}, "managed": {"$ne": True}},
        {"currency": "inr", "managed": {"$ne": True}, "slug": {"$regex": "-inr$"}},
    ]})
    published = {k: table[k] for k in ("cost_per_credit_usd", "price_per_credit_usd", "basis_commission_pct",
                                       "credits_per_usd")}
    published["config"] = table["config"]
    published["published_at"] = now_iso()
    await pricing_config_col.update_one({"_id": "published"}, {"$set": published}, upsert=True)
    return table


async def get_published() -> Dict[str, Any]:
    doc = await pricing_config_col.find_one({"_id": "published"})
    if not doc:
        await publish()
        doc = await pricing_config_col.find_one({"_id": "published"})
    doc.pop("_id", None)
    return doc


async def ensure_published() -> None:
    from db import credit_packs_col
    if not await pricing_config_col.find_one({"_id": "published"}) or \
            not await credit_packs_col.count_documents({"managed": True}):
        await publish()
