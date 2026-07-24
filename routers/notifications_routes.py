"""Notification routes and helper."""
from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from auth import get_current_user
from db import notifications_col, now_iso
from models import Notification, User

router = APIRouter(prefix="/notifications", tags=["notifications"])


async def notify(user_id: str, title: str, body: str = "", kind: str = "info", action_url: str = None):
    n = Notification(user_id=user_id, title=title, body=body, kind=kind, action_url=action_url)
    await notifications_col.insert_one(n.to_mongo())


@router.get("/")
async def list_notifications(user: User = Depends(get_current_user), limit: int = 50, unread_only: bool = False):
    q = {"user_id": user.id}
    if unread_only:
        q["read"] = False
    cursor = notifications_col.find(q).sort("created_at", -1).limit(limit)
    items = []
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        items.append(doc)
    unread_count = await notifications_col.count_documents({"user_id": user.id, "read": False})
    return {"items": items, "unread_count": unread_count}


@router.post("/{notif_id}/read")
async def mark_read(notif_id: str, user: User = Depends(get_current_user)):
    await notifications_col.update_one(
        {"_id": ObjectId(notif_id), "user_id": user.id},
        {"$set": {"read": True}},
    )
    return {"ok": True}


@router.post("/mark-all-read")
async def mark_all_read(user: User = Depends(get_current_user)):
    await notifications_col.update_many({"user_id": user.id, "read": False}, {"$set": {"read": True}})
    return {"ok": True}


@router.delete("/{notif_id}")
async def delete_notif(notif_id: str, user: User = Depends(get_current_user)):
    await notifications_col.delete_one({"_id": ObjectId(notif_id), "user_id": user.id})
    return {"ok": True}
