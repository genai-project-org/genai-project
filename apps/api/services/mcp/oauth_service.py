"""Generic per-connector OAuth: authorize URL, code exchange, refresh, disconnect.

Parameterized by services/mcp/registry.py's ConnectorConfig so every connector
shares one implementation — the same httpx-based code-exchange/refresh shape
already proven in services/gmail_service.py, generalized across providers.
"""
import logging
import secrets
from datetime import timedelta
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import httpx

from db import mcp_connections_col, mcp_oauth_states_col, now_iso, now_utc
from services import crypto_service
from services.mcp.registry import ConnectorConfig, get_connector

logger = logging.getLogger(__name__)

# Providers with a known, stable revoke endpoint for best-effort disconnect.
# Anything not listed here is simply deleted from our store without a
# provider-side revoke call — hardcoding a guessed revoke URL is worse than
# not calling one.
_REVOKE_URLS = {
    "google_calendar": "https://oauth2.googleapis.com/revoke",
}


class OAuthError(ValueError):
    pass


def _connector_or_raise(connector_id: str) -> ConnectorConfig:
    cfg = get_connector(connector_id)
    if not cfg:
        raise OAuthError(f"Unknown connector: {connector_id}")
    return cfg


def _resolve_urls(cfg: ConnectorConfig, domain: Optional[str]) -> tuple:
    if not cfg.requires_domain:
        return cfg.authorize_url, cfg.token_url
    if not domain:
        raise OAuthError(f"{cfg.display_name} needs your {cfg.domain_label.lower()} first")
    # Accept either a bare subdomain or the full host the user is likely to paste.
    host = domain.strip().lower().removeprefix("https://").removeprefix("http://").rstrip("/")
    return cfg.authorize_url.format(domain=host), cfg.token_url.format(domain=host)


async def build_authorize_url(user_id: str, connector_id: str, redirect_uri: str, domain: Optional[str] = None) -> str:
    cfg = _connector_or_raise(connector_id)
    if not cfg.is_configured():
        raise OAuthError(
            f"{cfg.display_name} is not configured on this server "
            f"(missing {cfg.client_id_env}/{cfg.client_secret_env})"
        )
    authorize_url, _ = _resolve_urls(cfg, domain)
    # Prefixing the opaque nonce with the connector id is purely a frontend
    # routing convenience (one generic /connectors callback page can tell
    # which connector a redirect belongs to without a second round trip) —
    # it doesn't weaken the CSRF check below, which still requires the full
    # string to match this exact stored doc's user_id + connector_id.
    state = f"{connector_id}::{secrets.token_urlsafe(24)}"
    await mcp_oauth_states_col.insert_one({
        "state": state,
        "user_id": user_id,
        "connector_id": connector_id,
        "domain": domain,  # re-read at exchange_code time to resolve the same per-store token_url
        "created_at": now_utc(),  # real BSON date — the TTL index on this collection needs it
    })
    params = {
        "client_id": cfg.client_id(),
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
        **({"scope": " ".join(cfg.scopes)} if cfg.scopes else {}),
        **cfg.extra_authorize_params,
    }
    return f"{authorize_url}?{urlencode(params)}"


def build_redirect_token_url(connector_id: str, redirect_uri: str, app_name: str = "AI Workspace") -> str:
    """Trello-style flow: no client secret, no server-side code exchange — the
    per-user token comes back directly in the redirect's URL fragment (see
    ConnectorOAuthCallback.jsx), which the popup posts to the opener for
    routers/mcp_routes.py's POST /connections/{id}/redirect-token to store.
    """
    cfg = _connector_or_raise(connector_id)
    if cfg.auth_type != "redirect_token":
        raise OAuthError(f"{connector_id} is not a redirect_token connector")
    if not cfg.is_configured():
        raise OAuthError(f"{cfg.display_name} is not configured on this server (missing {cfg.client_id_env})")
    params = {
        "expiration": "never",
        "name": app_name,
        "scope": "read,write",
        "response_type": "token",
        "key": cfg.client_id(),
        "return_url": redirect_uri,
        "callback_method": "fragment",
    }
    return f"{cfg.authorize_url}?{urlencode(params)}"


async def save_redirect_token(user_id: str, connector_id: str, token: str) -> Dict[str, Any]:
    cfg = _connector_or_raise(connector_id)
    if cfg.auth_type != "redirect_token":
        raise OAuthError(f"{connector_id} is not a redirect_token connector")
    if not token:
        raise OAuthError("No token received — please try connecting again")
    await mcp_connections_col.update_one(
        {"user_id": user_id, "connector_id": connector_id},
        {
            "$set": {
                "user_id": user_id, "connector_id": connector_id,
                "credentials_enc": crypto_service.encrypt_json({"token": token}),
                "updated_at": now_iso(),
            },
            "$setOnInsert": {"connected_at": now_iso()},
        },
        upsert=True,
    )
    return {"connected": True, "connector_id": connector_id}


async def _consume_state(user_id: str, connector_id: str, state: str) -> dict:
    doc = await mcp_oauth_states_col.find_one_and_delete({"state": state})
    if not doc or doc.get("user_id") != user_id or doc.get("connector_id") != connector_id:
        raise OAuthError("Invalid or expired connect request — please try connecting again")
    return doc


async def exchange_code(user_id: str, connector_id: str, code: str, redirect_uri: str, state: str) -> Dict[str, Any]:
    cfg = _connector_or_raise(connector_id)
    state_doc = await _consume_state(user_id, connector_id, state)
    _, token_url = _resolve_urls(cfg, state_doc.get("domain"))

    async with httpx.AsyncClient(timeout=15) as http:
        res = await http.post(
            token_url,
            data={
                "code": code,
                "client_id": cfg.client_id(),
                "client_secret": cfg.client_secret(),
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            headers={"Accept": "application/json"},
        )
    if res.status_code != 200:
        logger.error(f"{connector_id} token exchange failed: {res.text}")
        raise OAuthError(f"{cfg.display_name} authorization failed — try connecting again")

    tokens = res.json()
    access_token = tokens.get("access_token")
    if not access_token:
        logger.error(f"{connector_id} token exchange returned no access_token: {tokens}")
        raise OAuthError(f"{cfg.display_name} did not return an access token — try again")

    refresh_token = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in")
    expiry = (now_utc() + timedelta(seconds=int(expires_in))).isoformat() if expires_in else None

    creds: Dict[str, str] = {"access_token": access_token}
    if refresh_token:
        creds["refresh_token"] = refresh_token

    update: Dict[str, Any] = {
        "user_id": user_id,
        "connector_id": connector_id,
        "credentials_enc": crypto_service.encrypt_json(creds),
        "token_expiry": expiry,
        "scopes": cfg.scopes,
        "updated_at": now_iso(),
    }
    if cfg.requires_domain:
        update["domain"] = state_doc.get("domain")
    await mcp_connections_col.update_one(
        {"user_id": user_id, "connector_id": connector_id},
        {"$set": update, "$setOnInsert": {"connected_at": now_iso()}},
        upsert=True,
    )
    return {"connected": True, "connector_id": connector_id}


async def get_valid_access_token(user_id: str, connector_id: str) -> str:
    cfg = _connector_or_raise(connector_id)
    conn = await mcp_connections_col.find_one({"user_id": user_id, "connector_id": connector_id})
    if not conn:
        raise OAuthError(f"{cfg.display_name} is not connected")
    creds = crypto_service.decrypt_json(conn["credentials_enc"])

    expiry = conn.get("token_expiry")
    if not expiry:
        # Provider issues non-expiring tokens (e.g. a classic GitHub OAuth App token).
        return creds["access_token"]

    from datetime import datetime
    if now_utc() < datetime.fromisoformat(expiry):
        return creds["access_token"]

    refresh_token = creds.get("refresh_token")
    if not refresh_token:
        raise OAuthError(f"{cfg.display_name} connection expired — please reconnect")

    _, token_url = _resolve_urls(cfg, conn.get("domain"))
    async with httpx.AsyncClient(timeout=15) as http:
        res = await http.post(
            token_url,
            data={
                "refresh_token": refresh_token,
                "client_id": cfg.client_id(),
                "client_secret": cfg.client_secret(),
                "grant_type": "refresh_token",
            },
            headers={"Accept": "application/json"},
        )
    if res.status_code != 200:
        logger.warning(f"{connector_id} token refresh failed for user {user_id}: {res.text}")
        raise OAuthError(f"{cfg.display_name} connection expired — please reconnect")

    tokens = res.json()
    access_token = tokens["access_token"]
    new_expiry = (now_utc() + timedelta(seconds=int(tokens.get("expires_in", 3600)))).isoformat()
    # Most providers don't re-issue a refresh_token on plain refresh — never
    # overwrite the one we already have with a missing value.
    new_creds = {"access_token": access_token, "refresh_token": tokens.get("refresh_token") or refresh_token}
    await mcp_connections_col.update_one(
        {"user_id": user_id, "connector_id": connector_id},
        {"$set": {"credentials_enc": crypto_service.encrypt_json(new_creds), "token_expiry": new_expiry, "updated_at": now_iso()}},
    )
    return access_token


async def get_connection_status(user_id: str, connector_id: str) -> Optional[Dict[str, Any]]:
    return await mcp_connections_col.find_one({"user_id": user_id, "connector_id": connector_id})


async def disconnect(user_id: str, connector_id: str) -> None:
    revoke_url = _REVOKE_URLS.get(connector_id)
    conn = await mcp_connections_col.find_one({"user_id": user_id, "connector_id": connector_id})
    if conn and revoke_url:
        try:
            token = crypto_service.decrypt_json(conn["credentials_enc"])["access_token"]
            async with httpx.AsyncClient(timeout=10) as http:
                await http.post(revoke_url, params={"token": token})
        except Exception:
            logger.warning(f"Best-effort revoke failed for {connector_id}/{user_id}", exc_info=True)
    await mcp_connections_col.delete_one({"user_id": user_id, "connector_id": connector_id})
