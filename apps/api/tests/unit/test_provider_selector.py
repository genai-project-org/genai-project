"""Unit tests for services/provider_selector.py — AI provider/model selection
based on the user's `ai_provider` preference, with the random iema/auto
fallback pinned via monkeypatch so the tests are deterministic.
"""
import pytest

from bson import ObjectId

from db import users_col
from services import provider_selector

pytestmark = pytest.mark.anyio


async def _make_user(ai_provider=None):
    doc = {"email": "provider-test@example.com"}
    if ai_provider is not None:
        doc["ai_provider"] = ai_provider
    result = await users_col.insert_one(doc)
    return str(result.inserted_id)


# ------------------------------ get_user_preference ------------------------------

async def test_get_user_preference_defaults_to_iema_for_no_user_id():
    assert await provider_selector.get_user_preference(None) == "iema"


async def test_get_user_preference_defaults_to_iema_when_field_missing():
    user_id = await _make_user()
    assert await provider_selector.get_user_preference(user_id) == "iema"


async def test_get_user_preference_returns_stored_value():
    user_id = await _make_user(ai_provider="claude")
    assert await provider_selector.get_user_preference(user_id) == "claude"


async def test_get_user_preference_falls_back_to_iema_on_bad_id():
    assert await provider_selector.get_user_preference("not-a-valid-object-id") == "iema"


# ------------------------------ pick_provider ------------------------------

async def test_pick_provider_forced_claude_ignores_user_pref():
    user_id = await _make_user(ai_provider="openai")
    provider, model = await provider_selector.pick_provider(user_id, force="claude")
    assert provider == "anthropic"
    assert model == provider_selector.CLAUDE_MODEL


async def test_pick_provider_forced_openai():
    provider, model = await provider_selector.pick_provider(force="openai")
    assert provider == "openai"
    assert model == provider_selector.OPENAI_MODEL


async def test_pick_provider_honors_user_preference_claude():
    user_id = await _make_user(ai_provider="claude")
    provider, model = await provider_selector.pick_provider(user_id)
    assert provider == "anthropic"
    assert model == provider_selector.CLAUDE_MODEL


async def test_pick_provider_honors_user_preference_openai():
    user_id = await _make_user(ai_provider="openai")
    provider, model = await provider_selector.pick_provider(user_id)
    assert provider == "openai"
    assert model == provider_selector.OPENAI_MODEL


async def test_pick_provider_random_for_iema_preference(monkeypatch):
    monkeypatch.setattr(provider_selector.random, "choice", lambda seq: "anthropic")
    user_id = await _make_user(ai_provider="iema")
    provider, model = await provider_selector.pick_provider(user_id)
    assert provider == "anthropic"
    assert model == provider_selector.CLAUDE_MODEL


async def test_pick_provider_random_for_auto_preference(monkeypatch):
    monkeypatch.setattr(provider_selector.random, "choice", lambda seq: "openai")
    user_id = await _make_user(ai_provider="auto")
    provider, model = await provider_selector.pick_provider(user_id)
    assert provider == "openai"
    assert model == provider_selector.OPENAI_MODEL


async def test_pick_provider_random_choice_is_drawn_from_both_providers(monkeypatch):
    captured = {}

    def _choice(seq):
        captured["seq"] = tuple(seq)
        return seq[0]

    monkeypatch.setattr(provider_selector.random, "choice", _choice)
    await provider_selector.pick_provider(None)
    assert captured["seq"] == provider_selector.PROVIDERS
