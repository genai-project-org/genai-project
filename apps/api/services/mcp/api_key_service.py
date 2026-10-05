"""Connect flow for connectors with no practical per-user OAuth redirect —
the user pastes one or more static credential values (API key, PAT, account
SID + auth token, etc.) they copied from the provider's own dashboard.

No server-wide app registration is involved here (contrast
services/mcp/oauth_service.py, which needs a client_id/client_secret this
server owns) — each user's values are theirs alone, encrypted the same way.
"""
from typing import Any, Dict

from db import mcp_connections_col, now_iso
from services import crypto_service
from services.mcp.registry import ConnectorConfig, get_connector


class ApiKeyError(ValueError):
    pass


def _connector_or_raise(connector_id: str) -> ConnectorConfig:
    cfg = get_connector(connector_id)
    if not cfg:
        raise ApiKeyError(f"Unknown connector: {connector_id}")
    if cfg.auth_type != "api_key":
        raise ApiKeyError(f"{connector_id} is not an api_key connector")
    return cfg


async def save_connection(user_id: str, connector_id: str, values: Dict[str, str]) -> Dict[str, Any]:
    cfg = _connector_or_raise(connector_id)
    missing = [f for f in cfg.credential_fields if not (values.get(f) or "").strip()]
    if missing:
        raise ApiKeyError(f"Missing required value(s) for {cfg.display_name}: {', '.join(missing)}")
    creds = {f: values[f].strip() for f in cfg.credential_fields}

    await mcp_connections_col.update_one(
        {"user_id": user_id, "connector_id": connector_id},
        {
            "$set": {
                "user_id": user_id,
                "connector_id": connector_id,
                "credentials_enc": crypto_service.encrypt_json(creds),
                "updated_at": now_iso(),
            },
            "$setOnInsert": {"connected_at": now_iso()},
        },
        upsert=True,
    )
    return {"connected": True, "connector_id": connector_id}


async def get_credentials(user_id: str, connector_id: str) -> Dict[str, str]:
    cfg = _connector_or_raise(connector_id)
    conn = await mcp_connections_col.find_one({"user_id": user_id, "connector_id": connector_id})
    if not conn:
        raise ApiKeyError(f"{cfg.display_name} is not connected")
    return crypto_service.decrypt_json(conn["credentials_enc"])
