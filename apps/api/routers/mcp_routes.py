"""MCP connector routes — connect/disconnect third-party services and run
the prompt-to-action loop against whatever the user has connected."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from auth import get_current_user
from db import mcp_audit_log_col, mcp_connections_col
from models import McpApiKeyConnectRequest, McpCallbackRequest, McpConnectorPublic, McpPromptRequest, McpToggleRequest, User
from services.mcp import api_key_service, oauth_service
from services.mcp.orchestrator_service import run_prompt
from services.mcp.registry import list_connectors

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/mcp", tags=["mcp"])


@router.get("/connectors", response_model=list[McpConnectorPublic])
async def get_connectors(user: User = Depends(get_current_user)):
    connections = {
        doc["connector_id"]: doc
        async for doc in mcp_connections_col.find({"user_id": user.id})
    }
    return [
        McpConnectorPublic(
            id=cfg.id,
            display_name=cfg.display_name,
            description=cfg.description,
            category=cfg.category,
            auth_type=cfg.auth_type,
            mcp_status=cfg.mcp_status,
            credential_fields=cfg.credential_fields,
            scopes=cfg.scopes,
            connected=cfg.id in connections,
            enabled=connections.get(cfg.id, {}).get("enabled", True),
            external_label=connections.get(cfg.id, {}).get("external_label"),
            configured=cfg.is_configured(),
        )
        for cfg in list_connectors()
    ]


@router.get("/connect/{connector_id}")
async def connect(connector_id: str, redirect_uri: str = Query(...), user: User = Depends(get_current_user)):
    try:
        url = await oauth_service.build_authorize_url(user.id, connector_id, redirect_uri)
    except oauth_service.OAuthError as e:
        raise HTTPException(400, str(e))
    return {"authorize_url": url}


@router.post("/callback/{connector_id}")
async def callback(connector_id: str, req: McpCallbackRequest, user: User = Depends(get_current_user)):
    try:
        return await oauth_service.exchange_code(user.id, connector_id, req.code, req.redirect_uri, req.state)
    except oauth_service.OAuthError as e:
        raise HTTPException(400, str(e))


@router.post("/connections/{connector_id}/api-key")
async def connect_with_api_key(connector_id: str, req: McpApiKeyConnectRequest, user: User = Depends(get_current_user)):
    try:
        return await api_key_service.save_connection(user.id, connector_id, req.values)
    except api_key_service.ApiKeyError as e:
        raise HTTPException(400, str(e))


@router.delete("/connections/{connector_id}")
async def disconnect(connector_id: str, user: User = Depends(get_current_user)):
    await oauth_service.disconnect(user.id, connector_id)
    return {"ok": True}


@router.patch("/connections/{connector_id}/toggle")
async def toggle_connection(connector_id: str, req: McpToggleRequest, user: User = Depends(get_current_user)):
    from db import now_iso
    result = await mcp_connections_col.update_one(
        {"user_id": user.id, "connector_id": connector_id},
        {"$set": {"enabled": req.enabled, "updated_at": now_iso()}},
    )
    if result.matched_count == 0:
        raise HTTPException(404, "Not connected")
    return {"enabled": req.enabled}


@router.post("/prompt")
async def prompt(req: McpPromptRequest, user: User = Depends(get_current_user)):
    try:
        return await run_prompt(user.id, req.prompt)
    except Exception as e:
        logger.exception(f"MCP prompt failed for user {user.id}")
        raise HTTPException(500, f"Failed to run prompt: {e}")


@router.get("/audit")
async def audit_log(user: User = Depends(get_current_user), limit: int = Query(50, le=200)):
    cursor = mcp_audit_log_col.find({"user_id": user.id}).sort("created_at", -1).limit(limit)
    items = []
    async for d in cursor:
        d["id"] = str(d.pop("_id"))
        items.append(d)
    return {"items": items}
