"""Proprietary Data Lake - captures every event/interaction to MongoDB for future model training."""
import asyncio
import logging
from typing import Any, Dict, Optional
from db import db, now_iso

logger = logging.getLogger(__name__)

events_col = db["events"]


async def log_event(
    event_type: str,
    user_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """Fire-and-forget event logging. Never raises."""
    try:
        doc = {
            "event_type": event_type,
            "user_id": user_id,
            "payload": payload or {},
            "meta": meta or {},
            "created_at": now_iso(),
        }
        await events_col.insert_one(doc)
    except Exception as e:
        logger.warning(f"Data lake log failed for {event_type}: {e}")


def log_event_bg(event_type: str, **kwargs) -> None:
    """Schedule an event log without awaiting."""
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(log_event(event_type, **kwargs))
    except Exception:
        pass


async def query_events(
    event_type: Optional[str] = None,
    user_id: Optional[str] = None,
    limit: int = 50,
    text_search: Optional[str] = None,
) -> list:
    """Query the data lake — used by counseling module to seed context."""
    q: Dict[str, Any] = {}
    if event_type:
        q["event_type"] = event_type
    if user_id:
        q["user_id"] = user_id
    if text_search:
        q["$text"] = {"$search": text_search}
    docs = []
    cursor = events_col.find(q).sort("created_at", -1).limit(limit)
    async for d in cursor:
        d["id"] = str(d.pop("_id"))
        docs.append(d)
    return docs


async def ensure_events_indexes():
    await events_col.create_index([("event_type", 1), ("created_at", -1)])
    await events_col.create_index([("user_id", 1), ("created_at", -1)])
