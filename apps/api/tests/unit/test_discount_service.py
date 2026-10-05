"""Unit tests for services/discount_service.py — admin-managed promo codes:
creation validation, redemption-eligibility checks (`validate`), and the
mutating helpers (`update_discount`, `delete_discount`, `increment_use`).
"""
import datetime as dt

import pytest

from services import discount_service

pytestmark = pytest.mark.anyio


# ------------------------------ create_discount ------------------------------

async def test_create_discount_normalizes_code_to_uppercase():
    doc = await discount_service.create_discount({"code": "save10", "percent_off": 10})
    assert doc["_id"] == "SAVE10"


async def test_create_discount_rejects_short_code():
    with pytest.raises(ValueError):
        await discount_service.create_discount({"code": "ab", "percent_off": 10})


async def test_create_discount_rejects_non_alphanumeric_code():
    with pytest.raises(ValueError):
        await discount_service.create_discount({"code": "SAVE-10", "percent_off": 10})


async def test_create_discount_rejects_duplicate():
    await discount_service.create_discount({"code": "DUPE1", "percent_off": 5})
    with pytest.raises(ValueError):
        await discount_service.create_discount({"code": "dupe1", "percent_off": 15})


async def test_create_discount_defaults():
    doc = await discount_service.create_discount({"code": "DEFAULTS"})
    assert doc["percent_off"] == 0
    assert doc["flat_off_usd"] == 0
    assert doc["applies_to"] == "any"
    assert doc["max_uses"] == 0
    assert doc["uses"] == 0
    assert doc["active"] is True


# ------------------------------ validate ------------------------------

async def test_validate_rejects_empty_code():
    result = await discount_service.validate("", 100.0)
    assert result["ok"] is False


async def test_validate_rejects_unknown_code():
    result = await discount_service.validate("GHOST", 100.0)
    assert result["ok"] is False
    assert result["reason"] == "code not found"


async def test_validate_rejects_inactive_code():
    await discount_service.create_discount({"code": "OFFCODE", "percent_off": 10, "active": False})
    result = await discount_service.validate("OFFCODE", 100.0)
    assert result["ok"] is False
    assert result["reason"] == "discount inactive"


async def test_validate_rejects_expired_code():
    yesterday = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=1)).isoformat()
    await discount_service.create_discount({"code": "OLDCODE", "percent_off": 10})
    await discount_service.update_discount("OLDCODE", {"expires_at": yesterday})
    result = await discount_service.validate("OLDCODE", 100.0)
    assert result["ok"] is False
    assert result["reason"] == "code expired"


async def test_validate_accepts_future_expiry():
    tomorrow = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=1)).isoformat()
    await discount_service.create_discount({"code": "FRESHCODE", "percent_off": 10, "expires_at": tomorrow})
    result = await discount_service.validate("FRESHCODE", 100.0)
    assert result["ok"] is True


async def test_validate_rejects_when_fully_redeemed():
    await discount_service.create_discount({"code": "MAXED", "percent_off": 10, "max_uses": 1})
    await discount_service.increment_use("MAXED")
    result = await discount_service.validate("MAXED", 100.0)
    assert result["ok"] is False
    assert result["reason"] == "code fully redeemed"


async def test_validate_allows_unlimited_uses_by_default():
    await discount_service.create_discount({"code": "UNLIMITED", "percent_off": 5})
    for _ in range(5):
        await discount_service.increment_use("UNLIMITED")
    result = await discount_service.validate("UNLIMITED", 100.0)
    assert result["ok"] is True


async def test_validate_enforces_applies_to_target():
    await discount_service.create_discount({
        "code": "PACKONLY", "percent_off": 10, "applies_to": "pack:starter-usd",
    })
    mismatched = await discount_service.validate("PACKONLY", 100.0, target_kind="pack:pro-usd")
    assert mismatched["ok"] is False
    assert "only applies to" in mismatched["reason"]

    matched = await discount_service.validate("PACKONLY", 100.0, target_kind="pack:starter-usd")
    assert matched["ok"] is True


async def test_validate_computes_percent_off():
    await discount_service.create_discount({"code": "TENOFF", "percent_off": 10})
    result = await discount_service.validate("TENOFF", 50.0)
    assert result["ok"] is True
    assert result["discount_usd"] == 5.0
    assert result["final_usd"] == 45.0


async def test_validate_computes_flat_off():
    await discount_service.create_discount({"code": "FLAT5", "flat_off_usd": 5})
    result = await discount_service.validate("FLAT5", 20.0)
    assert result["ok"] is True
    assert result["discount_usd"] == 5.0
    assert result["final_usd"] == 15.0


async def test_validate_combines_percent_and_flat_but_never_exceeds_base_price():
    """A generous stacked discount on a cheap item must floor at $0, never go negative."""
    await discount_service.create_discount({"code": "HUGE", "percent_off": 90, "flat_off_usd": 50})
    result = await discount_service.validate("HUGE", 10.0)
    assert result["ok"] is True
    assert result["discount_usd"] == 10.0
    assert result["final_usd"] == 0.0


async def test_validate_is_case_insensitive():
    await discount_service.create_discount({"code": "MixedCase", "percent_off": 10})
    result = await discount_service.validate("mixedcase", 100.0)
    assert result["ok"] is True


# ------------------------------ update / delete / list ------------------------------

async def test_update_discount_ignores_disallowed_fields():
    await discount_service.create_discount({"code": "LOCKED", "percent_off": 10})
    await discount_service.update_discount("LOCKED", {"percent_off": 20, "uses": 999, "_id": "HACKED"})
    doc = await discount_service.discounts_col.find_one({"_id": "LOCKED"})
    assert doc["percent_off"] == 20
    assert doc["uses"] == 0  # not in the allowed-fields set — must be untouched


async def test_delete_discount_removes_it():
    await discount_service.create_discount({"code": "GONE", "percent_off": 5})
    assert await discount_service.delete_discount("gone") is True
    assert await discount_service.discounts_col.find_one({"_id": "GONE"}) is None


async def test_delete_discount_returns_false_when_missing():
    assert await discount_service.delete_discount("NEVEREXISTED") is False


async def test_list_discounts_exposes_code_field():
    await discount_service.create_discount({"code": "LISTED", "percent_off": 5})
    items = await discount_service.list_discounts()
    codes = {d["code"] for d in items}
    assert "LISTED" in codes
