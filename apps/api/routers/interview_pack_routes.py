"""Interview Pack routes — catalog + admin CRUD. Mirrors routers/pack_routes.py
exactly, against interview_packs_col instead of credit_packs_col — kept as a
separate file/collection because interview sessions and wallet credits are a
deliberately non-fungible pair of entitlement tracks (see models.py's
RazorpayOrderRequest.pack_kind and services/interview_service.py)."""
from fastapi import APIRouter, Depends, HTTPException
from bson import ObjectId
from auth import get_current_user, require_admin
from db import interview_packs_col
from models import InterviewPack, InterviewPackCreate, User

router = APIRouter(prefix="/interview-packs", tags=["interview-packs"])


@router.get("/")
async def list_packs(currency: str = "usd"):
    cursor = interview_packs_col.find({"is_visible": True, "currency": currency}).sort([("sort_order", 1), ("price", 1)])
    items = []
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        items.append(doc)
    return {"items": items}


@router.get("/all")
async def list_all_packs(admin: User = Depends(require_admin)):
    cursor = interview_packs_col.find({}).sort([("sort_order", 1), ("price", 1)])
    items = []
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        items.append(doc)
    return {"items": items}


@router.post("/")
async def create_pack(req: InterviewPackCreate, admin: User = Depends(require_admin)):
    pack = InterviewPack(**req.model_dump())
    result = await interview_packs_col.insert_one(pack.to_mongo())
    pack.id = str(result.inserted_id)
    return pack.model_dump()


@router.patch("/{pack_id}")
async def update_pack(pack_id: str, req: InterviewPackCreate, admin: User = Depends(require_admin)):
    await interview_packs_col.update_one({"_id": ObjectId(pack_id)}, {"$set": req.model_dump()})
    doc = await interview_packs_col.find_one({"_id": ObjectId(pack_id)})
    if not doc:
        raise HTTPException(404, "Not found")
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.delete("/{pack_id}")
async def delete_pack(pack_id: str, admin: User = Depends(require_admin)):
    await interview_packs_col.delete_one({"_id": ObjectId(pack_id)})
    return {"ok": True}
