"""Global app settings (admin-configurable, key/value in Mongo)."""
import logging
from typing import Any, Optional
from db import db, now_iso

logger = logging.getLogger(__name__)

settings_col = db["app_settings"]

DEFAULTS = {
    "kb_similarity_threshold": 0.85,   # Jaccard threshold for semantic KB reuse
    "kb_enabled": True,                # Master switch — turn off to bypass KB
    "kb_only_mode": False,             # If true, LLM calls fail unless KB has an answer
}


async def get_setting(key: str, default: Any = None) -> Any:
    doc = await settings_col.find_one({"_id": key})
    if doc and "value" in doc:
        return doc["value"]
    if default is not None:
        return default
    return DEFAULTS.get(key)


async def set_setting(key: str, value: Any) -> None:
    await settings_col.update_one(
        {"_id": key},
        {"$set": {"value": value, "updated_at": now_iso()}},
        upsert=True,
    )


async def all_settings() -> dict:
    out = dict(DEFAULTS)
    async for d in settings_col.find({}):
        out[d["_id"]] = d.get("value")
    return out
