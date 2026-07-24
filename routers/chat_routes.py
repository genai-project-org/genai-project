"""Chat/AI Workspace routes with streaming."""
import os
import json
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.responses import StreamingResponse
from bson import ObjectId
from auth import get_current_user
from db import conversations_col, messages_col, ai_requests_col, now_iso
from models import (
    SendMessageRequest, RenameConversationRequest, Conversation, Message, User
)
from services.credit_service import has_credits, deduct_credits
from services.pricing_engine import spend, resolve_cost
from services.ai_service import stream_ai_response

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])

CREDIT_COST_MESSAGE = float(os.environ.get("CREDIT_COST_MESSAGE", "1"))


@router.get("/conversations")
async def list_conversations(user: User = Depends(get_current_user), limit: int = 100, skip: int = 0):
    cursor = conversations_col.find({"user_id": user.id}).sort([("pinned", -1), ("updated_at", -1)]).skip(skip).limit(limit)
    items = []
    async for doc in cursor:
        doc["id"] = str(doc.pop("_id"))
        items.append(doc)
    return {"items": items}


@router.post("/conversations")
async def create_conversation(user: User = Depends(get_current_user)):
    conv = Conversation(user_id=user.id, title="New Chat")
    result = await conversations_col.insert_one(conv.to_mongo())
    conv.id = str(result.inserted_id)
    return conv.model_dump()


@router.get("/conversations/{conv_id}")
async def get_conversation(conv_id: str, user: User = Depends(get_current_user)):
    try:
        doc = await conversations_col.find_one({"_id": ObjectId(conv_id), "user_id": user.id})
    except Exception:
        doc = None
    if not doc:
        raise HTTPException(404, "Conversation not found")
    doc["id"] = str(doc.pop("_id"))
    # fetch messages
    msg_cursor = messages_col.find({"conversation_id": conv_id}).sort("created_at", 1)
    msgs = []
    async for m in msg_cursor:
        m["id"] = str(m.pop("_id"))
        msgs.append(m)
    return {"conversation": doc, "messages": msgs}


@router.patch("/conversations/{conv_id}")
async def rename_conversation(conv_id: str, req: RenameConversationRequest, user: User = Depends(get_current_user)):
    try:
        result = await conversations_col.update_one(
            {"_id": ObjectId(conv_id), "user_id": user.id},
            {"$set": {"title": req.title, "updated_at": now_iso()}},
        )
    except Exception:
        raise HTTPException(400, "Invalid conversation id")
    if result.matched_count == 0:
        raise HTTPException(404, "Not found")
    return {"ok": True}


@router.post("/conversations/{conv_id}/pin")
async def toggle_pin(conv_id: str, user: User = Depends(get_current_user)):
    doc = await conversations_col.find_one({"_id": ObjectId(conv_id), "user_id": user.id})
    if not doc:
        raise HTTPException(404, "Not found")
    new_pinned = not doc.get("pinned", False)
    await conversations_col.update_one({"_id": ObjectId(conv_id)}, {"$set": {"pinned": new_pinned, "updated_at": now_iso()}})
    return {"pinned": new_pinned}


@router.delete("/conversations/{conv_id}")
async def delete_conversation(conv_id: str, user: User = Depends(get_current_user)):
    await conversations_col.delete_one({"_id": ObjectId(conv_id), "user_id": user.id})
    await messages_col.delete_many({"conversation_id": conv_id})
    return {"ok": True}


@router.post("/stream")
async def stream_message(req: SendMessageRequest, user: User = Depends(get_current_user)):
    """SSE streaming endpoint for chat messages."""
    # Resolve cost dynamically via pricing engine
    msg_price = await resolve_cost("chat_message")
    img_price = await resolve_cost("chat_message_image")
    image_count = 0
    if req.attachments:
        image_count = sum(1 for a in req.attachments if (a.get("content_type") or "").startswith("image/"))
    total_cost = msg_price["credit_cost"] + image_count * img_price["credit_cost"]
    if not await has_credits(user.id, total_cost):
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, "Insufficient credits. Please recharge your wallet.")

    # Get or create conversation
    conv_id = req.conversation_id
    if not conv_id:
        conv = Conversation(user_id=user.id, title=req.content[:60] or "New Chat")
        result = await conversations_col.insert_one(conv.to_mongo())
        conv_id = str(result.inserted_id)
    else:
        try:
            existing = await conversations_col.find_one({"_id": ObjectId(conv_id), "user_id": user.id})
        except Exception:
            existing = None
        if not existing:
            raise HTTPException(404, "Conversation not found")

    # Save user message
    user_msg = Message(
        conversation_id=conv_id,
        user_id=user.id,
        role="user",
        content=req.content,
        attachments=req.attachments or [],
    )
    user_result = await messages_col.insert_one(user_msg.to_mongo())
    user_msg.id = str(user_result.inserted_id)

    # Load history
    history_docs = await messages_col.find({"conversation_id": conv_id}).sort("created_at", 1).to_list(50)
    history = [{"role": d["role"], "content": d["content"]} for d in history_docs[:-1]]  # exclude the just-inserted user msg from prefix

    async def event_stream():
        yield f"data: {json.dumps({'type': 'conversation', 'conversation_id': conv_id, 'user_message_id': user_msg.id})}\n\n"
        provider = None
        model = None
        full_text = ""
        try:
            async for evt in stream_ai_response(conv_id, req.content, history, req.model, attachments=req.attachments):
                if evt["type"] == "meta":
                    provider = evt["provider"]
                    model = evt["model"]
                    yield f"data: {json.dumps(evt)}\n\n"
                elif evt["type"] == "delta":
                    full_text += evt["content"]
                    yield f"data: {json.dumps(evt)}\n\n"
                elif evt["type"] == "done":
                    full_text = evt.get("content", full_text) or full_text
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    break
                elif evt["type"] == "warn":
                    yield f"data: {json.dumps(evt)}\n\n"
                elif evt["type"] == "error":
                    yield f"data: {json.dumps(evt)}\n\n"
                    break

            if full_text:
                # Save assistant message
                asst_msg = Message(
                    conversation_id=conv_id,
                    user_id=user.id,
                    role="assistant",
                    content=full_text,
                    provider=provider,
                    model=model,
                    credits_used=total_cost,
                )
                asst_res = await messages_col.insert_one(asst_msg.to_mongo())
                # Central spend (window + wallet + provider tracking)
                try:
                    await spend(user.id, "chat_message", provider_override=provider,
                                description=f"Chat message ({model})", ref_id=conv_id)
                    if image_count:
                        for _ in range(image_count):
                            await spend(user.id, "chat_message_image", provider_override=provider,
                                        description=f"Chat image ({model})", ref_id=conv_id)
                except HTTPException:
                    # rate-limit — already deducted via primary msg; ignore silently for chat
                    pass
                # Update conversation
                await conversations_col.update_one(
                    {"_id": ObjectId(conv_id)},
                    {"$set": {"updated_at": now_iso(), "provider_used": provider, "model_used": model}},
                )
                # Log AI request
                await ai_requests_col.insert_one({
                    "user_id": user.id,
                    "conversation_id": conv_id,
                    "provider": provider,
                    "model": model,
                    "credits_used": total_cost,
                    "created_at": now_iso(),
                })
                yield f"data: {json.dumps({'type': 'saved', 'assistant_message_id': str(asst_res.inserted_id), 'credits_used': total_cost})}\n\n"
        except Exception as e:
            logger.exception("Chat stream error")
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )

@router.post("")
async def send_message(
    req: SendMessageRequest,
    user: User = Depends(get_current_user),
):
    msg_price = await resolve_cost("chat_message")
    img_price = await resolve_cost("chat_message_image")

    image_count = 0
    if req.attachments:
        image_count = sum(
            1
            for a in req.attachments
            if (a.get("content_type") or "").startswith("image/")
        )

    total_cost = msg_price["credit_cost"] + image_count * img_price["credit_cost"]

    if not await has_credits(user.id, total_cost):
        raise HTTPException(
            status.HTTP_402_PAYMENT_REQUIRED,
            "Insufficient credits. Please recharge your wallet."
        )

    conv_id = req.conversation_id

    if not conv_id:
        conv = Conversation(
            user_id=user.id,
            title=req.content[:60] or "New Chat"
        )
        result = await conversations_col.insert_one(conv.to_mongo())
        conv_id = str(result.inserted_id)
    else:
        existing = await conversations_col.find_one(
            {
                "_id": ObjectId(conv_id),
                "user_id": user.id,
            }
        )

        if not existing:
            raise HTTPException(404, "Conversation not found")

    user_msg = Message(
        conversation_id=conv_id,
        user_id=user.id,
        role="user",
        content=req.content,
        attachments=req.attachments or [],
    )

    user_result = await messages_col.insert_one(user_msg.to_mongo())
    user_msg.id = str(user_result.inserted_id)

    history_docs = (
        await messages_col
        .find({"conversation_id": conv_id})
        .sort("created_at", 1)
        .to_list(50)
    )

    history = [
        {
            "role": d["role"],
            "content": d["content"],
        }
        for d in history_docs[:-1]
    ]

    provider = None
    model = None
    full_text = ""

    async for evt in stream_ai_response(
        conv_id,
        req.content,
        history,
        req.model,
        attachments=req.attachments,
    ):
        if evt["type"] == "meta":
            provider = evt["provider"]
            model = evt["model"]

        elif evt["type"] == "delta":
            full_text += evt["content"]

        elif evt["type"] == "done":
            full_text = evt.get("content", full_text) or full_text
            break

        elif evt["type"] == "error":
            raise HTTPException(500, evt["message"])

    assistant = Message(
        conversation_id=conv_id,
        user_id=user.id,
        role="assistant",
        content=full_text,
        provider=provider,
        model=model,
        credits_used=total_cost,
    )

    result = await messages_col.insert_one(assistant.to_mongo())

    await spend(
        user.id,
        "chat_message",
        provider_override=provider,
        description=f"Chat message ({model})",
        ref_id=conv_id,
    )

    if image_count:
        for _ in range(image_count):
            await spend(
                user.id,
                "chat_message_image",
                provider_override=provider,
                description=f"Chat image ({model})",
                ref_id=conv_id,
            )

    await conversations_col.update_one(
        {"_id": ObjectId(conv_id)},
        {
            "$set": {
                "updated_at": now_iso(),
                "provider_used": provider,
                "model_used": model,
            }
        },
    )

    await ai_requests_col.insert_one(
        {
            "user_id": user.id,
            "conversation_id": conv_id,
            "provider": provider,
            "model": model,
            "credits_used": total_cost,
            "created_at": now_iso(),
        }
    )

    return {
        "conversation_id": conv_id,
        "assistant_message_id": str(result.inserted_id),
        "content": full_text,
        "provider": provider,
        "model": model,
        "credits_used": total_cost,
    }