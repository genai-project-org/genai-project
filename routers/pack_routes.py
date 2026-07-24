"""Credit pack routes."""
from fastapi import APIRouter, Depends, HTTPException
from typing import List
from bson import ObjectId
from auth import get_current_user, require_admin
from db import credit_packs_col
from models import CreditPack, CreditPackCreate, User

router = APIRouter(prefix="/packs", tags=["packs"])


@router.get("/")
async def list_packs(currency: str = "usd"):
    cursor = credit_packs_col.find({"is_visible": True, "currency": currency}).sort([("sort_order", 1), ("price", 1)])
    items = []
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        items.append(doc)
    return {"items": items}


@router.get("/all")
async def list_all_packs(admin: User = Depends(require_admin)):
    cursor = credit_packs_col.find({}).sort([("sort_order", 1), ("price", 1)])
    items = []
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        items.append(doc)
    return {"items": items}


@router.post("/")
async def create_pack(req: CreditPackCreate, admin: User = Depends(require_admin)):
    pack = CreditPack(**req.model_dump())
    result = await credit_packs_col.insert_one(pack.to_mongo())
    pack.id = str(result.inserted_id)
    return pack.model_dump()


@router.patch("/{pack_id}")
async def update_pack(pack_id: str, req: CreditPackCreate, admin: User = Depends(require_admin)):
    await credit_packs_col.update_one({"_id": ObjectId(pack_id)}, {"$set": req.model_dump()})
    doc = await credit_packs_col.find_one({"_id": ObjectId(pack_id)})
    if not doc:
        raise HTTPException(404, "Not found")
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.delete("/{pack_id}")
async def delete_pack(pack_id: str, admin: User = Depends(require_admin)):
    await credit_packs_col.delete_one({"_id": ObjectId(pack_id)})
    return {"ok": True}
