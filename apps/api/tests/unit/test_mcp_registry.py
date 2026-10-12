"""Registry sanity: every connector marked ready must point at a real tool
server module, and api_key connectors must map every credential field to an env var."""
import importlib

import pytest

from services.mcp.registry import list_connectors


def test_ready_stdio_connectors_have_importable_servers():
    for cfg in list_connectors():
        if cfg.mcp_status != "ready" or cfg.transport != "stdio":
            continue
        module = cfg.stdio_args[-1]
        assert importlib.import_module(module).mcp is not None, cfg.id


def test_api_key_connectors_map_all_fields():
    for cfg in list_connectors():
        if cfg.auth_type == "api_key":
            assert set(cfg.credential_fields) <= set(cfg.credential_env_map), cfg.id


@pytest.mark.parametrize("cid", ["gmail", "google_calendar", "slack", "github", "notion", "linear", "asana", "airtable", "trello"])
def test_demo_connectors_are_live(cid):
    cfg = next(c for c in list_connectors() if c.id == cid)
    assert cfg.mcp_status == "ready" and cfg.transport == "stdio"
