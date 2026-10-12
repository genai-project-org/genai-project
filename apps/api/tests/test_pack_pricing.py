"""Pack / pay-as-you-go pricing engine: unit tests (pure maths) + integration tests
(publish -> purchase -> wallet credit) against a throw-away Mongo database.

Needs only a reachable MONGO_URL (taken from .env); the database is dropped afterwards.
"""
import asyncio
import copy
import os
import re

os.environ["DB_NAME"] = "iema_pricing_test"  # must be set before `db` is imported

import httpx
import pytest
from fastapi import FastAPI

from services import pack_pricing as pp
from services.pricing_engine import DEFAULT_PRICING

CATALOG = [{**d, "service_key": d["_id"]} for d in DEFAULT_PRICING]
FX = 85.0


# ============================ unit ============================
def test_price_per_credit_hits_target_margin_after_commission():
    cost, margin, comm = 0.003, 40.0, 30.0
    ppc = pp.price_per_credit(cost, margin, comm)
    got = pp.margin_pct_after_commission(ppc * 1000, 1000, cost, comm)
    assert got == pytest.approx(margin, abs=0.05)


def test_higher_commission_or_margin_means_fewer_credits_per_usd():
    base = pp.credits_per_usd(0.003, 40, 2.36)
    assert pp.credits_per_usd(0.003, 40, 30) < base
    assert pp.credits_per_usd(0.003, 60, 2.36) < base


def test_credits_per_usd_is_clean_and_never_undermines_margin():
    cpu = pp.credits_per_usd(0.003, 40, 30, step=5)
    assert cpu % 5 == 0
    assert pp.margin_pct_after_commission(1.0, cpu, 0.003, 30) >= 40.0


def test_inr_is_ceiled_to_clean_figure():
    assert pp.inr_for_usd(4.99, 85.0, 50) == 450      # 424.15 -> 450
    assert pp.inr_for_usd(20, 85.0, 50) == 1700       # exact stays
    assert pp.inr_for_usd(20.01, 85.0, 50) == 1750    # never rounds down
    assert pp.inr_for_usd(9.99, 85.0, 100) == 900


def test_table_tiers_are_store_friendly_and_margin_floor_holds():
    t = pp.compute_pricing(CATALOG, pp.DEFAULT_CONFIG, FX)
    general = [p for p in t["packs"] if p["kind"] == "general"]
    assert [p["price_usd"] for p in general] == [4.99, 9.99, 19.99, 49.99, 99.99]
    floor = t["config"]["margin_floor_pct"]
    for p in t["packs"]:
        assert p["price_inr"] % 50 == 0
        assert min(p["margin_pct"].values()) >= floor - 0.01, p["slug"]
        # a pack is never worse value than pay-as-you-go
        assert p["total_credits"] >= int(p["price_usd"] * t["credits_per_usd"]) - 10
    ids = [p["product_id"] for p in t["packs"]]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"iema\.pack\.[a-z0-9_]+", i) for i in ids)
    assert not ({"Starter", "Standard", "Pro", "Business"} & {p["name"] for p in t["packs"]})


def test_higher_target_margin_gives_fewer_credits_for_same_price():
    lo = pp.compute_pricing(CATALOG, pp.merge_config(pp.DEFAULT_CONFIG, {"target_margin_pct": 30}), FX)
    hi = pp.compute_pricing(CATALOG, pp.merge_config(pp.DEFAULT_CONFIG, {"target_margin_pct": 60}), FX)
    assert hi["credits_per_usd"] < lo["credits_per_usd"]
    assert [p["price_usd"] for p in hi["packs"]] == [p["price_usd"] for p in lo["packs"]]


def test_specialised_packs_come_from_the_catalog():
    t = pp.compute_pricing(CATALOG, pp.DEFAULT_CONFIG, FX)
    cats = {p["category"] for p in t["packs"] if p["kind"] == "specialised"}
    assert {"chat", "studio", "builder", "career", "counseling"} <= cats
    # a new catalog category (e.g. interview) gets its own pack with no code change
    extra = CATALOG + [{"service_key": "interview_session", "credit_cost": 40, "provider": "anthropic",
                        "category": "interview", "description": "Mock interview session"}]
    t2 = pp.compute_pricing(extra, pp.DEFAULT_CONFIG, FX)
    iv = next(p for p in t2["packs"] if p["category"] == "interview")
    assert iv["highlights"][0]["units"] == iv["total_credits"] // 40


def test_payg_minimum_is_20_usd_and_cannot_be_configured_lower():
    cfg = pp.validate_config(pp.merge_config(pp.DEFAULT_CONFIG, {"payg": {"min_usd": 5}}))
    assert cfg["payg"]["min_usd"] == 20
    for bad in (0, 5, 19.99, -20):
        with pytest.raises(ValueError):
            pp.payg_quote(bad, cfg, 140, FX)
    q = pp.payg_quote(20, cfg, 140, FX)
    assert q["credits"] == 2800 and q["amount_inr"] == 1700
    with pytest.raises(ValueError):
        pp.payg_quote(cfg["payg"]["max_usd"] + 1, cfg, 140, FX)


def test_payg_uses_same_rate_as_packs():
    t = pp.compute_pricing(CATALOG, pp.DEFAULT_CONFIG, FX)
    q = pp.payg_quote(100, t["config"], t["credits_per_usd"], FX)
    titan = next(p for p in t["packs"] if p["slug"] == "titan")
    assert q["credits"] == int(100 * t["credits_per_usd"])
    assert titan["total_credits"] >= int(titan["price_usd"] * t["credits_per_usd"]) - 10


def test_config_validation():
    for patch in ({"target_margin_pct": 95}, {"target_margin_pct": -1}, {"commissions_pct": {"apple": 80}}):
        with pytest.raises(ValueError):
            pp.validate_config(pp.merge_config(pp.DEFAULT_CONFIG, patch))


def test_exports_contain_product_ids_and_prices():
    t = pp.compute_pricing(CATALOG, pp.DEFAULT_CONFIG, FX)
    csv_text = pp.export_text(t, "csv")
    md = pp.export_text(t, "md")
    assert csv_text.splitlines()[0].startswith("product_id,name,type")
    for p in t["packs"]:
        assert p["product_id"] in csv_text and p["product_id"] in md
    assert "4.99" in csv_text and "99.99" in md


# ============================ integration ============================
LOOP = asyncio.new_event_loop()


def run(coro):
    return LOOP.run_until_complete(coro)


class FakeLinks:
    def __init__(self):
        self.created = []
        self.status = "paid"

    def create(self, payload):
        self.created.append(payload)
        n = len(self.created)
        return {"id": f"plink_test_{n}", "short_url": f"https://rzp.io/i/test{n}"}

    def fetch(self, link_id):
        return {"id": link_id, "status": self.status, "short_url": "https://rzp.io/i/x"}


class FakeRzp:
    def __init__(self):
        self.payment_link = FakeLinks()


@pytest.fixture(scope="module")
def env():
    from db import db, client, users_col
    from models import User
    from services import payments_service
    from routers import payments_routes, pricing_routes
    from routers.payments_routes import router as pay_router
    from routers.pricing_routes import router as price_router
    from auth import get_current_user
    from services.pricing_engine import seed_defaults

    async def fx():
        return FX

    saved = (payments_service.get_usd_to_inr, payments_routes.get_usd_to_inr, pricing_routes.get_usd_to_inr,
             payments_routes._razorpay_client)
    payments_service.get_usd_to_inr = fx
    payments_routes.get_usd_to_inr = fx
    pricing_routes.get_usd_to_inr = fx
    rzp = FakeRzp()
    payments_routes._razorpay_client = rzp

    user = User(id="64b000000000000000000abc", email="buyer@example.com", name="Buyer")
    app = FastAPI()
    app.include_router(price_router, prefix="/api")
    app.include_router(pay_router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: user

    async def setup():
        await client.drop_database("iema_pricing_test")
        await seed_defaults()
        # legacy seeded packs that must disappear on publish
        await db["credit_packs"].insert_one({"name": "Starter", "slug": "starter-usd", "price": 5.0,
                                             "currency": "usd", "credits": 500, "bonus_credits": 0,
                                             "is_visible": True, "sort_order": 1})
        await pp.publish()

    run(setup())
    http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    yield {"http": http, "rzp": rzp, "user": user}
    run(http.aclose())
    run(client.drop_database("iema_pricing_test"))
    (payments_service.get_usd_to_inr, payments_routes.get_usd_to_inr, pricing_routes.get_usd_to_inr,
     payments_routes._razorpay_client) = saved


def _wallet(user_id):
    from services.credit_service import get_or_create_wallet
    return run(get_or_create_wallet(user_id))


def test_public_pricing_is_single_source_and_hides_margins(env):
    from services.credit_service import WELCOME_CREDITS, DAILY_CREDITS
    r = run(env["http"].get("/api/pricing"))
    assert r.status_code == 200
    d = r.json()
    assert d["welcome_credits"] == WELCOME_CREDITS and d["daily_credits"] == DAILY_CREDITS
    assert d["payg"]["min_usd"] == 20
    assert [x["usd"] for x in d["payg"]["presets"]] == [20, 50, 100]
    slugs = {p["slug"] for p in d["packs"]}
    assert "starter-usd" not in slugs and {"spark", "surge", "titan", "studio"} <= slugs
    assert all(p["product_id"].startswith("iema.pack.") for p in d["packs"])
    assert "margin_pct" not in r.text and "cost_per_credit" not in r.text
    assert len(d["store_products"]) == len(d["packs"])


def test_payg_below_minimum_rejected_server_side(env):
    for amt in (1, 10, 19.99):
        r = run(env["http"].post("/api/payments/razorpay/payg", json={"amount_usd": amt}))
        assert r.status_code == 400 and "Minimum" in r.json()["detail"]
    assert run(env["http"].get("/api/pricing/quote", params={"amount_usd": 5})).status_code == 400
    assert not env["rzp"].payment_link.created


def test_payg_purchase_credits_wallet_once(env):
    uid = env["user"].id
    before = _wallet(uid).purchased_credits
    r = run(env["http"].post("/api/payments/razorpay/payg", json={"amount_usd": 20}))
    assert r.status_code == 200, r.text
    d = r.json()
    cpu = run(pp.get_published())["credits_per_usd"]
    assert d["short_url"].startswith("https://rzp.io/")
    assert d["credits"] == 20 * cpu
    assert d["amount"] == pp.inr_for_usd(20, FX, 50) * 100          # paise charged == INR shown
    assert env["rzp"].payment_link.created[-1]["currency"] == "INR"
    for _ in range(2):  # polling twice must not double-credit
        s = run(env["http"].get(f"/api/payments/razorpay/link-status/{d['payment_link_id']}"))
        assert s.status_code == 200 and s.json()["credited"] is True
    assert _wallet(uid).purchased_credits == before + 20 * cpu


def test_pack_purchase_credits_total_including_bonus(env):
    uid = env["user"].id
    before = _wallet(uid).purchased_credits
    r = run(env["http"].post("/api/payments/razorpay/order", json={"pack_slug": "surge"}))
    assert r.status_code == 200, r.text
    d = r.json()
    total = d["pack"]["credits"] + d["pack"]["bonus_credits"]
    assert d["credits"] == total
    assert d["amount"] == pp.inr_for_usd(19.99, FX, 50) * 100
    run(env["http"].get(f"/api/payments/razorpay/link-status/{d['payment_link_id']}"))
    assert _wallet(uid).purchased_credits == before + total


def test_iap_pack_product_credits_once(env):
    from services.payments_service import credit_pack_product
    uid = "iap-user-1"
    a = run(credit_pack_product(uid, "iema.pack.boost", "google", "tok-1"))
    b = run(credit_pack_product(uid, "iema.pack.boost", "google", "tok-1"))
    assert a["ok"] and b["already_processed"]
    boost = next(p for p in run(pp.publish())["packs"] if p["slug"] == "boost")
    assert _wallet(uid).purchased_credits == boost["total_credits"]
    assert run(credit_pack_product(uid, "iema.unknown", "google", "tok-2")) is None


def test_publish_with_new_margin_changes_rate_for_packs_and_payg(env):
    before = run(pp.get_published())["credits_per_usd"]
    run(pp.publish({"target_margin_pct": 60}))
    after = run(pp.get_published())["credits_per_usd"]
    assert after < before
    r = run(env["http"].get("/api/pricing"))
    assert r.json()["credits_per_usd"] == after
    surge = next(p for p in r.json()["packs"] if p["slug"] == "surge")
    assert surge["total_credits"] >= int(19.99 * after) - 10
    run(pp.publish({"target_margin_pct": 40}))
