"""AI Provider Selector — randomize between Claude and OpenAI, or honor user preference.

User preference (`users.ai_provider`):
- "iema"    : KB first, then random provider fallback (default)
- "claude"  : Force anthropic Claude Haiku 4.5
- "openai"  : Force OpenAI GPT-5.2
- "auto"    : Same as iema

The chosen model is returned so the caller can pass it to `LlmChat.with_model()`.
Usage tracking (in pricing_engine.spend) records the actual provider used.
"""
import os
import random
from typing import Optional, Tuple
from bson import ObjectId
from db import users_col

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
OPENAI_MODEL = os.environ.get("OPENAI_TEXT_MODEL", "gpt-4o-mini")

PROVIDERS = ("anthropic", "openai")


async def get_user_preference(user_id: Optional[str]) -> str:
    if not user_id:
        return "iema"
    try:
        u = await users_col.find_one({"_id": ObjectId(user_id)}, {"ai_provider": 1})
    except Exception:
        return "iema"
    return (u or {}).get("ai_provider") or "iema"


async def pick_provider(user_id: Optional[str] = None, force: Optional[str] = None) -> Tuple[str, str]:
    """Returns (provider, model). `force` overrides user preference."""
    pref = force or await get_user_preference(user_id)
    if pref == "claude":
        return "anthropic", CLAUDE_MODEL
    if pref == "openai":
        return "openai", OPENAI_MODEL
    # iema / auto → random
    p = random.choice(PROVIDERS)
    return (p, CLAUDE_MODEL if p == "anthropic" else OPENAI_MODEL)
