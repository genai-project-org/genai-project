"""Knowledge Retriever — data-lake-first LLM avoidance layer.

Flow for any AI-generating call:
    1. Exact hash match on (kind, prompt_norm) → return cached (0 credits)
    2. MongoDB $text search over prompt_norm → top N candidates
    3. Jaccard-similarity score >= threshold → return best match (0 credits)
    4. Miss → caller invokes LLM, then calls `store(...)` to write back.

Threshold is admin-configurable via `settings.kb_similarity_threshold` (default 0.85).
No external embeddings — pure Mongo + Python. Zero third-party dependency.
"""
import re
import hashlib
import logging
from typing import Any, Dict, Optional, Tuple
from db import db, now_iso
from services.settings_service import get_setting

logger = logging.getLogger(__name__)

ai_responses_col = db["ai_responses"]

_STOP = set(
    "a an the and or but for of on in at to from with by is are was were be been being "
    "i me my we our you your he she it they them do does did have has had can could should "
    "would will just also as if then than that this these those about into over under out "
    "up down off no not so too very please help me want need what how why when where which".split()
)
_WORD = re.compile(r"[a-z0-9]+")


def _normalize(text: str) -> str:
    return " ".join(_WORD.findall((text or "").lower()))


def _tokens(text: str) -> set:
    # Keep >=2-char tech tokens (llm, gpt, aws, sql, seo, iam, ai, ml…) — improves match precision on short-tech prompts.
    return {w for w in _WORD.findall((text or "").lower()) if w not in _STOP and len(w) >= 2}


def _jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


def _hash(kind: str, prompt: str) -> str:
    return hashlib.sha256(f"{kind}::{_normalize(prompt)}".encode()).hexdigest()


async def ensure_kb_indexes():
    try:
        await ai_responses_col.create_index([("hash", 1)], unique=True)
        await ai_responses_col.create_index([("kind", 1), ("created_at", -1)])
        await ai_responses_col.create_index([("prompt_norm", "text")])
    except Exception as e:
        logger.warning(f"KB index creation warning: {e}")


async def retrieve(kind: str, prompt: str, user_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Return a cached AI response for this (kind, prompt) or None on miss."""
    norm = _normalize(prompt)
    if not norm:
        return None

    # 1) Exact hash
    h = _hash(kind, prompt)
    exact = await ai_responses_col.find_one({"hash": h})
    if exact:
        await ai_responses_col.update_one({"hash": h}, {"$inc": {"hit_count": 1}, "$set": {"last_used_at": now_iso()}})
        return {
            "response": exact["response"],
            "meta": exact.get("meta", {}),
            "match": "exact",
            "score": 1.0,
        }

    # 2) Text search + Jaccard
    threshold = float(await get_setting("kb_similarity_threshold", 0.85))
    query_tokens = _tokens(prompt)
    if not query_tokens:
        return None
    try:
        cursor = ai_responses_col.find(
            {"kind": kind, "$text": {"$search": norm}},
            {"score": {"$meta": "textScore"}, "prompt_norm": 1, "response": 1, "meta": 1, "hash": 1},
        ).sort([("score", {"$meta": "textScore"})]).limit(10)
    except Exception:
        return None

    best = None
    best_score = 0.0
    async for cand in cursor:
        cand_tokens = _tokens(cand["prompt_norm"])
        score = _jaccard(query_tokens, cand_tokens)
        if score > best_score:
            best_score = score
            best = cand

    if best and best_score >= threshold:
        await ai_responses_col.update_one(
            {"hash": best["hash"]},
            {"$inc": {"hit_count": 1}, "$set": {"last_used_at": now_iso()}},
        )
        return {
            "response": best["response"],
            "meta": best.get("meta", {}),
            "match": "semantic",
            "score": round(best_score, 3),
        }
    return None


async def store(
    kind: str,
    prompt: str,
    response: Any,
    user_id: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist a fresh LLM response to the knowledge bank."""
    norm = _normalize(prompt)
    if not norm:
        return
    doc = {
        "hash": _hash(kind, prompt),
        "kind": kind,
        "prompt": prompt[:4000],
        "prompt_norm": norm[:4000],
        "response": response,
        "meta": meta or {},
        "user_id": user_id,
        "hit_count": 0,
        "created_at": now_iso(),
        "last_used_at": now_iso(),
    }
    try:
        await ai_responses_col.update_one(
            {"hash": doc["hash"]},
            {"$set": doc},
            upsert=True,
        )
    except Exception as e:
        logger.warning(f"KB store failed: {e}")


async def stats() -> Dict[str, Any]:
    total = await ai_responses_col.count_documents({})
    by_kind = {}
    async for row in ai_responses_col.aggregate([
        {"$group": {"_id": "$kind", "count": {"$sum": 1}, "hits": {"$sum": "$hit_count"}}}
    ]):
        by_kind[row["_id"]] = {"count": row["count"], "hits": row["hits"]}
    total_hits = sum(v["hits"] for v in by_kind.values())
    return {"total_entries": total, "total_hits": total_hits, "by_kind": by_kind}
