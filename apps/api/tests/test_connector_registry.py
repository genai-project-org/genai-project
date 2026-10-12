"""Registry config detection, authorize-URL shape and the generic REST server's URL guard."""
import asyncio
import importlib
import os
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services.mcp import oauth_service  # noqa: E402
from services.mcp.registry import CONNECTORS, get_connector  # noqa: E402

# connector id -> (client id env, client secret env) as present in apps/api/.env
EXPECTED_ENV = {
    "google_calendar": ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
    "gmail": ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
    "google_docs": ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
    "google_sheets": ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
    "google_drive": ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
    "gcp": ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
    "google_analytics": ("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
    "github": ("GITHUB_MCP_CLIENT_ID", "GITHUB_MCP_CLIENT_SECRET"),
    "slack": ("SLACK_CLIENT_ID", "SLACK_CLIENT_SECRET"),
    "notion": ("NOTION_CLIENT_ID", "NOTION_CLIENT_SECRET"),
    "atlassian_jira": ("ATLASSIAN_CLIENT_ID", "ATLASSIAN_CLIENT_SECRET"),
    "atlassian_confluence": ("ATLASSIAN_CLIENT_ID", "ATLASSIAN_CLIENT_SECRET"),
    "microsoft_teams": ("MS_TEAMS_CLIENT_ID", "MS_TEAMS_CLIENT_SECRET"),
    "microsoft_outlook_mail": ("MS_OUTLOOK_CLIENT_ID", "MS_OUTLOOK_CLIENT_SECRET"),
    "microsoft_onedrive": ("MS_GRAPH_CLIENT_ID", "MS_GRAPH_CLIENT_SECRET"),
    "microsoft_sharepoint": ("MS_GRAPH_CLIENT_ID", "MS_GRAPH_CLIENT_SECRET"),
    "azure": ("MS_GRAPH_CLIENT_ID", "MS_GRAPH_CLIENT_SECRET"),
    "dropbox": ("DROPBOX_APP_KEY", "DROPBOX_APP_SECRET"),
    "asana": ("ASANA_CLIENT_ID", "ASANA_CLIENT_SECRET"),
    "linear": ("LINEAR_CLIENT_ID", "LINEAR_CLIENT_SECRET"),
    "monday": ("MONDAY_CLIENT_ID", "MONDAY_CLIENT_SECRET"),
    "basecamp": ("BASECAMP_CLIENT_ID", "BASECAMP_CLIENT_SECRET"),
    "airtable": ("AIRTABLE_CLIENT_ID", "AIRTABLE_CLIENT_SECRET"),
    "gitlab": ("GITLAB_CLIENT_ID", "GITLAB_CLIENT_SECRET"),
    "bitbucket": ("BITBUCKET_CLIENT_ID", "BITBUCKET_CLIENT_SECRET"),
    "sentry": ("SENTRY_CLIENT_ID", "SENTRY_CLIENT_SECRET"),
    "salesforce": ("SALESFORCE_CLIENT_ID", "SALESFORCE_CLIENT_SECRET"),
    "intercom": ("INTERCOM_CLIENT_ID", "INTERCOM_CLIENT_SECRET"),
    "zendesk": ("ZENDESK_CLIENT_ID", "ZENDESK_CLIENT_SECRET"),
    "zoom": ("ZOOM_CLIENT_ID", "ZOOM_CLIENT_SECRET"),
    "discord": ("DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET"),
    "box": ("BOX_CLIENT_ID", "BOX_CLIENT_SECRET"),
    "clickup": ("CLICKUP_CLIENT_ID", "CLICKUP_CLIENT_SECRET"),
    "hubspot": ("HUBSPOT_CLIENT_ID", "HUBSPOT_CLIENT_SECRET"),
    "docusign": ("DOCUSIGN_CLIENT_ID", "DOCUSIGN_CLIENT_SECRET"),
    "linkedin": ("LINKEDIN_MCP_CLIENT_ID", "LINKEDIN_MCP_CLIENT_SECRET"),
    "mailchimp": ("MAILCHIMP_CLIENT_ID", "MAILCHIMP_CLIENT_SECRET"),
    "quickbooks": ("QUICKBOOKS_CLIENT_ID", "QUICKBOOKS_CLIENT_SECRET"),
    "reddit": ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"),
    "shopify": ("SHOPIFY_CLIENT_ID", "SHOPIFY_CLIENT_SECRET"),
    "stripe": ("STRIPE_CONNECT_CLIENT_ID", "STRIPE_CONNECT_CLIENT_SECRET"),
    "twitter_x": ("X_CLIENT_ID", "X_CLIENT_SECRET"),
}
API_KEY_ONLY = {"telegram", "twilio", "whatsapp_business", "vercel", "aws", "circleci", "freshdesk", "sendgrid", "paypal"}


def _clear_creds(monkeypatch):
    for cid, envs in EXPECTED_ENV.items():
        for e in envs:
            monkeypatch.delenv(e, raising=False)
    monkeypatch.delenv("TRELLO_API_KEY", raising=False)


def test_env_names_match_dotenv_contract():
    for cid, (idv, secv) in EXPECTED_ENV.items():
        cfg = get_connector(cid)
        assert cfg is not None, cid
        assert (cfg.client_id_env, cfg.client_secret_env) == (idv, secv), cid


def test_every_connector_is_covered():
    oauth_ids = {c.id for c in CONNECTORS.values() if c.auth_type == "oauth2"}
    assert oauth_ids == set(EXPECTED_ENV)
    assert {c.id for c in CONNECTORS.values() if c.auth_type == "api_key"} == API_KEY_ONLY


def test_unconfigured_until_both_env_vars_set(monkeypatch):
    _clear_creds(monkeypatch)
    cfg = get_connector("asana")
    assert not cfg.is_configured()
    monkeypatch.setenv("ASANA_CLIENT_ID", "x")
    assert not cfg.is_configured()
    monkeypatch.setenv("ASANA_CLIENT_SECRET", "y")
    assert cfg.is_configured()


def test_shared_credentials_configure_every_sibling(monkeypatch):
    _clear_creds(monkeypatch)
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "x")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "y")
    google = [c for c in CONNECTORS.values() if c.client_id_env == "GOOGLE_CLIENT_ID"]
    assert len(google) == 7 and all(c.is_configured() for c in google)


def test_api_key_and_trello_detection(monkeypatch):
    _clear_creds(monkeypatch)
    for cid in API_KEY_ONLY:
        assert get_connector(cid).is_configured()
    trello = get_connector("trello")
    assert trello.auth_type == "redirect_token" and not trello.is_configured()
    monkeypatch.setenv("TRELLO_API_KEY", "k")
    assert trello.is_configured()


def test_oauth_endpoints_are_https_and_complete():
    for cfg in CONNECTORS.values():
        if cfg.auth_type != "oauth2":
            continue
        assert cfg.authorize_url.startswith("https://") and cfg.token_url.startswith("https://"), cfg.id
        assert cfg.mcp_status in ("ready", "needs_server")
        if cfg.requires_domain:
            assert "{domain}" in cfg.authorize_url and "{domain}" in cfg.token_url, cfg.id


def test_ready_connectors_have_a_real_tool_server():
    for cfg in CONNECTORS.values():
        if cfg.mcp_status != "ready":
            continue
        if cfg.transport == "http":
            assert cfg.http_url.startswith("https://"), cfg.id
            continue
        assert cfg.stdio_args[:1] == ["-m"], cfg.id
        importlib.util.find_spec(cfg.stdio_args[1]) is not None or pytest.fail(cfg.id)
        if cfg.rest_base:
            assert cfg.rest_allowed_hosts and cfg.token_env_var == "REST_ACCESS_TOKEN", cfg.id


def test_phase_sets_are_ready():
    for cid in ["asana", "atlassian_jira", "atlassian_confluence", "github", "google_calendar", "gmail", "google_docs",
                "google_sheets", "google_drive", "gcp", "google_analytics", "intercom", "linear", "monday", "notion",
                "sentry", "slack", "airtable", "basecamp", "bitbucket", "dropbox", "gitlab", "microsoft_onedrive",
                "microsoft_sharepoint", "azure", "microsoft_outlook_mail", "microsoft_teams", "salesforce", "zendesk",
                "zoom", "discord", "trello"]:
        assert get_connector(cid).mcp_status == "ready", cid


class _FakeStates:
    def __init__(self):
        self.docs = []

    async def insert_one(self, doc):
        self.docs.append(doc)


def _authorize(monkeypatch, cid, redirect="http://localhost:5174/connectors/oauth-callback", domain=None):
    fake = _FakeStates()
    monkeypatch.setattr(oauth_service, "mcp_oauth_states_col", fake)
    cfg = get_connector(cid)
    monkeypatch.setenv(cfg.client_id_env, "cid")
    monkeypatch.setenv(cfg.client_secret_env, "sec")
    url = asyncio.run(oauth_service.build_authorize_url("u1", cid, redirect, domain=domain))
    return urlparse(url), parse_qs(urlparse(url).query), fake.docs[0]


def test_authorize_url_uses_given_redirect_and_env_client_id(monkeypatch):
    monkeypatch.delenv("CONNECTOR_REDIRECT_URI", raising=False)
    u, q, _ = _authorize(monkeypatch, "slack", "https://iema.ai/connectors/oauth-callback")
    assert u.netloc == "slack.com"
    assert q["redirect_uri"] == ["https://iema.ai/connectors/oauth-callback"]
    assert q["client_id"] == ["cid"] and q["state"][0].startswith("slack::")


def test_connector_redirect_uri_env_pins_redirect(monkeypatch):
    monkeypatch.setenv("CONNECTOR_REDIRECT_URI", "https://iema.ai/connectors/oauth-callback")
    _, q, _ = _authorize(monkeypatch, "github", "http://localhost:5174/connectors/oauth-callback")
    assert q["redirect_uri"] == ["https://iema.ai/connectors/oauth-callback"]


def test_linear_scopes_are_comma_separated(monkeypatch):
    _, q, _ = _authorize(monkeypatch, "linear")
    assert q["scope"] == ["read,write"]


def test_airtable_uses_pkce_and_stores_verifier(monkeypatch):
    _, q, doc = _authorize(monkeypatch, "airtable")
    assert q["code_challenge_method"] == ["S256"] and q["code_challenge"][0]
    assert doc["code_verifier"] and doc["code_verifier"] != q["code_challenge"][0]


def test_monday_and_asana_omit_scope(monkeypatch):
    for cid in ("monday", "asana", "zoom", "dropbox"):
        _, q, _ = _authorize(monkeypatch, cid)
        assert "scope" not in q, cid


def test_scope_env_override(monkeypatch):
    monkeypatch.setenv("GITLAB_SCOPES", "read_api, read_user")
    _, q, _ = _authorize(monkeypatch, "gitlab")
    assert q["scope"] == ["read_api read_user"]


def test_atlassian_audience_and_zendesk_subdomain(monkeypatch):
    _, q, _ = _authorize(monkeypatch, "atlassian_jira")
    assert q["audience"] == ["api.atlassian.com"] and "offline_access" in q["scope"][0]
    u, _, doc = _authorize(monkeypatch, "zendesk", domain="Acme")
    assert u.netloc == "acme.zendesk.com" and doc["domain"] == "Acme"
    u, _, _ = _authorize(monkeypatch, "zendesk", domain="https://acme.zendesk.com/")
    assert u.netloc == "acme.zendesk.com"


def test_unconfigured_connector_refuses_authorize(monkeypatch):
    _clear_creds(monkeypatch)
    with pytest.raises(oauth_service.OAuthError):
        asyncio.run(oauth_service.build_authorize_url("u1", "hubspot", "http://x/cb"))


# ---- generic REST server URL guard ----

def _rest():
    return importlib.import_module("services.mcp.servers.rest_server")


def test_rest_url_guard():
    r = _rest()
    allowed = ["api.zoom.us", "*.googleapis.com"]
    assert r.build_url("https://api.zoom.us/v2", "/users/me", allowed) == "https://api.zoom.us/v2/users/me"
    assert r.build_url("https://api.zoom.us/v2", "https://run.googleapis.com/x", allowed).startswith("https://run.googleapis.com")
    for bad in ("https://evil.example.com/x", "http://api.zoom.us/x", "//evil.com/x", "../admin", "https://googleapis.com.evil.com/x"):
        with pytest.raises(ValueError):
            r.build_url("https://api.zoom.us/v2", bad, allowed)
    assert r.host_allowed("a.force.com", ["*.force.com"]) and not r.host_allowed("force.com", ["*.force.com"])
