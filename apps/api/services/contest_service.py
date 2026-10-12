"""Contest Mode — timed, team-based hackathon contests built on top of the
existing Practice Engine (problems, Piston grading). Nothing here duplicates
grading logic: `run_submission()` from `practice_service` is reused as-is —
this module only adds the contest-shaped bookkeeping around it (time window,
teams, a separate free submission ledger, leaderboard, certificate/stats-card
generation).

Design decisions (documented here so a future reader doesn't have to
re-derive them):

* Contest submissions are recorded in their OWN collection
  (`contest_submissions`), never mixed into `practice_submissions`. This keeps
  the free, contest-only lane fully separate from the credit-tracked regular
  practice flow — a contest submission must never show up as a spend in
  admin financial dashboards, and a regular submission must never count
  toward a contest leaderboard.
* Contest submissions are FREE — no `precheck()`/`spend()` call anywhere in
  this module or in `routers/contest_routes.py`. This is a deliberate
  business decision (the hackathon itself is free-entry), not an oversight —
  see the comment at the submit route.
* Team score = the number of DISTINCT contest problems solved by AT LEAST ONE
  team member (not the sum of each member's solves) — this avoids rewarding
  a team for having more people redundantly solve the same problem, and
  matches "did the team, collectively, get this problem done?" which is the
  natural reading of a team hackathon leaderboard.
* Ties are broken the classic ICPC/Codeforces way: total time-to-solve, i.e.
  the sum of (first-passing-submission time − contest start) across every
  problem the team solved. Lower total time wins — the team that reached its
  solved count FASTER ranks higher. A final tie-break on team creation time
  keeps ordering fully deterministic (matters for tests and for a genuinely
  simultaneous tie).
* An individual's personal stats (used for their certificate + stats card)
  are separate from the team score: "problems solved" on a personal card
  counts only THAT user's own passing submissions, not the whole team's.
"""
import csv
import hmac
import io
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from html import escape as html_escape
from io import BytesIO
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFont

from db import db, now_iso, now_utc, users_col
from services.practice_service import practice_problems_col, get_problem_public, get_problem_raw
from services.llm_client import LlmChat, UserMessage
from services.builder_service import _extract_json
from services import contest_scoring as scoring
from services.contest_settings import (
    ContestSettings, ProblemConfig, parse_settings, parse_problem_config,
    validate_settings_patch, default_settings_dict, get_template, ALL_LANGUAGES,
)

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

contests_col = db["contests"]
contest_teams_col = db["contest_teams"]
contest_submissions_col = db["contest_submissions"]
contest_adjustments_col = db["contest_adjustments"]
contest_audit_col = db["contest_audit"]
contest_announcements_col = db["contest_announcements"]
contest_clarifications_col = db["contest_clarifications"]

MIN_TEAM_SIZE = 1  # solo participation is allowed — see create_team()
MAX_TEAM_SIZE = 3

# Default contest problem set: 4 of the 11 seeded practice_problems, all
# "Arrays & Hashing" Easy/Medium problems so a mixed-skill hackathon team has
# something everyone can pick up immediately without a long ramp-up. Used
# only when an admin creates a contest without specifying `problem_ids`.
DEFAULT_CONTEST_PROBLEM_IDS = [
    "two-sum", "contains-duplicate", "valid-anagram", "best-time-to-buy-sell-stock",
]


# ---------------------------------------------------------------------------
# Auto-generated registration landing page — generated ONCE at contest
# creation time (never per page view, same reasoning as the cached
# YouTube-link lookups elsewhere in this codebase: an LLM call is not free).
#
# Deliberately NOT raw LLM-generated HTML: the model only ever picks from a
# small closed set of structured fields (a headline, a tagline, 2-4
# highlight bullets, and a `layout`/`accent` chosen from a FIXED palette
# below). The frontend renders that structured JSON through its own
# hand-built React templates — real per-contest visual variety (copy,
# color, layout) without ever executing untrusted markup.
# ---------------------------------------------------------------------------
LANDING_ACCENTS = ["indigo", "violet", "emerald", "amber", "rose", "sky"]
LANDING_LAYOUTS = ["centered", "split", "cards"]

LANDING_SYSTEM_PROMPT = (
    "You are a marketing copywriter for a competitive-programming hackathon platform. "
    "Given one contest's name, schedule, and problem set, write the copy for its team-registration "
    "landing page.\n"
    "Output ONLY a single strict JSON object — no markdown fences, no prose, no trailing commentary.\n"
    "Schema:\n"
    "{\n"
    '  "headline": string, <= 70 chars, a punchy hook that names or clearly evokes THIS contest,\n'
    '  "tagline": string, <= 140 chars, one supporting sentence with a concrete, specific detail '
    "(timing, problem count/topics, or team format),\n"
    '  "highlights": array of 2 to 4 short strings, each <= 90 chars, concrete reasons to register '
    "(mention real specifics like the number of problems, that it is free/team-based, the deadline, etc.),\n"
    f'  "accent": one of {json.dumps(LANDING_ACCENTS)},\n'
    f'  "layout": one of {json.dumps(LANDING_LAYOUTS)}\n'
    "}\n"
    "Make every field genuinely specific to the contest given below — never generic filler that could "
    "apply to any contest — and vary your wording, accent and layout pick across different contests, "
    "so no two contests ever read identically."
)


async def generate_landing_page(name: str, problems: List[dict], start_at: str, end_at: str, use_llm: bool = True) -> dict:
    """Structured (never raw-HTML) landing-page copy for one contest. Falls
    back to a deterministic, still contest-specific template if the LLM call
    fails or returns something unusable — contest creation must never hard-fail
    just because a copywriting call had a bad day."""
    start_dt = _parse_iso(start_at)
    end_dt = _parse_iso(end_at)
    problem_titles = [p.get("title", p.get("_id", "")) for p in problems]
    problem_desc = ", ".join(
        f'{p.get("title", pid)} ({p.get("difficulty", "")})' for pid, p in zip(problem_titles, problems)
    ) or "a curated problem set"

    fallback = {
        "headline": f"Register for {name}",
        "tagline": (
            f"A free, team-based coding contest — {len(problems)} problem(s), "
            f"live {start_dt.strftime('%b %d')}–{end_dt.strftime('%b %d')}."
        ),
        "highlights": [
            f"{len(problems)} hand-picked problems to solve as a team",
            "Free entry — contest submissions never cost credits",
            "Live leaderboard, plus a certificate and stats card for every participant",
        ],
        "accent": LANDING_ACCENTS[0],
        "layout": LANDING_LAYOUTS[0],
    }

    if not use_llm:
        return fallback

    prompt = (
        f'Contest name: "{name}"\n'
        f"Runs: {start_dt.strftime('%B %d, %Y %H:%M UTC')} to {end_dt.strftime('%B %d, %Y %H:%M UTC')}\n"
        f"Problem set ({len(problems)} problems): {problem_desc}\n"
        "Generate the landing page JSON now."
    )
    try:
        chat = LlmChat(system_message=LANDING_SYSTEM_PROMPT).with_model(
            "anthropic", "claude-sonnet-5", max_tokens=16000,
        )
        resp = await chat.send_message(UserMessage(text=prompt))
        data = _extract_json(resp)

        headline = str(data.get("headline") or "").strip()[:100] or fallback["headline"]
        tagline = str(data.get("tagline") or "").strip()[:220] or fallback["tagline"]
        highlights = [str(h).strip()[:140] for h in (data.get("highlights") or []) if str(h).strip()][:4]
        if len(highlights) < 2:
            highlights = fallback["highlights"]
        accent = data.get("accent") if data.get("accent") in LANDING_ACCENTS else fallback["accent"]
        layout = data.get("layout") if data.get("layout") in LANDING_LAYOUTS else fallback["layout"]

        return {"headline": headline, "tagline": tagline, "highlights": highlights, "accent": accent, "layout": layout}
    except Exception as e:
        logger.warning(f"Landing page generation failed for contest '{name}' — using fallback copy: {e}")
        return fallback


_parse_iso = scoring.parse_iso


async def ensure_indexes():
    await contests_col.create_index([("start_at", 1)])
    await contest_teams_col.create_index([("contest_id", 1)])
    await contest_submissions_col.create_index([("contest_id", 1), ("team_id", 1)])
    await contest_submissions_col.create_index([("contest_id", 1), ("user_id", 1), ("problem_id", 1)])
    await contest_announcements_col.create_index([("contest_id", 1), ("created_at", -1)])
    await contest_clarifications_col.create_index([("contest_id", 1), ("created_at", -1)])
    await contest_audit_col.create_index([("contest_id", 1), ("created_at", -1)])
    await contest_adjustments_col.create_index([("contest_id", 1), ("team_id", 1)])


# ---------------------------------------------------------------------------
# Contest CRUD + lifecycle
# ---------------------------------------------------------------------------
def contest_status(contest: dict, now: Optional[datetime] = None) -> str:
    """"draft" | "upcoming" | "live" | "paused" | "ended" — the real, enforced
    source of truth for whether a submission should be accepted (see
    routers/contest_routes.py).

    An admin-triggered `stop_contest()` sets `ended_early: True`, which this
    checks right after the draft flag and unconditionally returns "ended" for
    — regardless of what `start_at`/`end_at` say — so a manual stop takes
    effect immediately and can never be raced by comparing against a
    not-yet-passed timestamp. Documents written before `state` existed have no
    such key and are treated as published."""
    if contest.get("state") == "draft":
        return "draft"
    if contest.get("ended_early"):
        return "ended"
    now = now or now_utc()
    start = _parse_iso(contest["start_at"])
    end = _parse_iso(contest["end_at"])
    if now < start:
        return "upcoming"
    if contest.get("paused_at"):
        # The clock is stopped while paused (end_at is pushed out on resume).
        return "paused"
    if now > end:
        return "ended"
    return "live"


async def audit(contest_id: str, actor: str, action: str, details: Optional[dict] = None) -> None:
    await contest_audit_col.insert_one({
        "_id": uuid.uuid4().hex, "contest_id": contest_id, "actor": actor, "action": action,
        "details": details or {}, "created_at": now_iso(),
    })


async def list_audit(contest_id: str, limit: int = 200) -> List[dict]:
    items = []
    async for d in contest_audit_col.find({"contest_id": contest_id}).sort("created_at", -1).limit(limit):
        items.append({"id": d["_id"], "actor": d["actor"], "action": d["action"],
                      "details": d.get("details", {}), "created_at": d["created_at"]})
    return items


async def _validated_problem_ids(ids: List[str]) -> Dict[str, dict]:
    ids = list(ids)
    if not ids:
        raise ValueError("A contest needs at least one problem")
    if len(set(ids)) != len(ids):
        raise ValueError("Duplicate problem ids")
    # Validate every id refers to a real, already-seeded practice problem —
    # never silently accept a typo'd id that would 404 for every contestant
    # the moment they open the contest.
    found_docs = {}
    async for d in practice_problems_col.find({"_id": {"$in": ids}}, {"_id": 1, "title": 1, "difficulty": 1}):
        found_docs[d["_id"]] = d
    missing = [i for i in ids if i not in found_docs]
    if missing:
        raise ValueError(f"Unknown problem id(s): {', '.join(missing)}")
    return found_docs


def _clean_configs(raw: Optional[Dict[str, Any]], problem_ids: List[str]) -> Dict[str, dict]:
    out = {}
    for pid, cfg in (raw or {}).items():
        if pid in problem_ids:
            out[pid] = ProblemConfig.model_validate(cfg or {}).model_dump()
    return out


async def create_contest(
    name: str, start_at: str, end_at: str, problem_ids: Optional[List[str]], created_by: str,
    settings: Optional[Dict[str, Any]] = None, problem_configs: Optional[Dict[str, Any]] = None,
    state: str = "published", ai_landing: bool = True,
) -> dict:
    start_dt = _parse_iso(start_at)
    end_dt = _parse_iso(end_at)
    if end_dt <= start_dt:
        raise ValueError("end_at must be after start_at")
    if state not in ("draft", "published"):
        raise ValueError("state must be 'draft' or 'published'")

    ids = list(problem_ids) if problem_ids else list(DEFAULT_CONTEST_PROBLEM_IDS)
    found_docs = await _validated_problem_ids(ids)
    clean_settings = ContestSettings.model_validate(settings or {}).model_dump()
    clean_configs = _clean_configs(problem_configs, ids)

    landing_page = await generate_landing_page(
        name, [found_docs[pid] for pid in ids], start_dt.isoformat(), end_dt.isoformat(), use_llm=ai_landing,
    )

    doc = {
        "_id": uuid.uuid4().hex,
        "name": name,
        "problem_ids": ids,
        "problem_configs": clean_configs,
        "settings": clean_settings,
        "state": state,
        "archived": False,
        "start_at": start_dt.isoformat(),
        "end_at": end_dt.isoformat(),
        "created_by": created_by,
        "landing_page": landing_page,
        "ended_early": False,
        "paused_at": None,
        "pauses": [],
        "invited_emails": [],
        "disqualified_user_ids": [],
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await contests_col.insert_one(doc)
    await audit(doc["_id"], created_by, "create", {"name": name, "state": state})
    return doc


async def create_from_template(
    template_id: str, name: str, created_by: str, start_at: Optional[str] = None,
) -> dict:
    tpl = get_template(template_id)
    if not tpl:
        raise ValueError("Unknown template")
    start_dt = _parse_iso(start_at) if start_at else now_utc().replace(microsecond=0)
    end_dt = start_dt + timedelta(minutes=tpl["duration_minutes"])
    existing = {d["_id"] async for d in practice_problems_col.find({"_id": {"$in": tpl["problem_ids"]}}, {"_id": 1})}
    ids = [p for p in tpl["problem_ids"] if p in existing] or list(DEFAULT_CONTEST_PROBLEM_IDS)
    ladder = tpl.get("point_ladder")
    configs = {}
    for i, pid in enumerate(ids):
        pts = (ladder[i] if ladder and i < len(ladder) else tpl.get("problem_config", {}).get("points", 100))
        configs[pid] = {"points": pts}
    return await create_contest(
        name, start_dt.isoformat(), end_dt.isoformat(), ids, created_by,
        settings=tpl["settings"], problem_configs=configs, state="published", ai_landing=False,
    )


async def get_contest(contest_id: str) -> Optional[dict]:
    return await contests_col.find_one({"_id": contest_id})


async def list_contests(include_hidden: bool = True) -> List[dict]:
    """`include_hidden=False` is the participant view: drafts and archived
    contests are invisible."""
    items = []
    async for d in contests_col.find({}).sort("start_at", -1):
        if not include_hidden and (d.get("state") == "draft" or d.get("archived")):
            continue
        items.append(d)
    return items


async def update_contest(contest_id: str, updates: Dict[str, Any], actor: str = "system") -> Optional[dict]:
    allowed = {"name", "start_at", "end_at", "problem_ids", "settings", "problem_configs", "state", "archived"}
    clean = {k: v for k, v in updates.items() if k in allowed and v is not None}
    existing = await get_contest(contest_id)
    if not existing:
        return None
    if "start_at" in clean:
        clean["start_at"] = _parse_iso(clean["start_at"]).isoformat()
    if "end_at" in clean:
        clean["end_at"] = _parse_iso(clean["end_at"]).isoformat()
    if _parse_iso(clean.get("end_at", existing["end_at"])) <= _parse_iso(clean.get("start_at", existing["start_at"])):
        raise ValueError("end_at must be after start_at")
    if "state" in clean and clean["state"] not in ("draft", "published"):
        raise ValueError("state must be 'draft' or 'published'")
    if "problem_ids" in clean:
        await _validated_problem_ids(clean["problem_ids"])
    ids = clean.get("problem_ids", existing["problem_ids"])
    if "settings" in clean:
        clean["settings"] = validate_settings_patch(existing.get("settings"), clean["settings"])
    if "problem_configs" in clean:
        merged = dict(existing.get("problem_configs") or {})
        merged.update(clean["problem_configs"] or {})
        clean["problem_configs"] = _clean_configs(merged, ids)
    if not clean:
        return existing
    clean["updated_at"] = now_iso()
    await contests_col.update_one({"_id": contest_id}, {"$set": clean})
    await audit(contest_id, actor, "update", {"fields": sorted(k for k in clean if k != "updated_at")})
    return await get_contest(contest_id)


async def set_problems(contest_id: str, problems: List[Dict[str, Any]], actor: str = "system") -> dict:
    """Replace the ordered problem list + per-problem config in one call. Safe
    while the contest is live: standings are recomputed from submissions on
    every read, so adding/removing/reordering/re-weighting takes effect
    immediately and removed problems simply stop counting."""
    contest = await get_contest(contest_id)
    if not contest:
        raise ValueError("Contest not found")
    ids = [p["problem_id"] for p in problems]
    await _validated_problem_ids(ids)
    configs = {}
    for p in problems:
        cfg = {k: v for k, v in p.items() if k != "problem_id"}
        configs[p["problem_id"]] = ProblemConfig.model_validate(cfg).model_dump()
    await contests_col.update_one(
        {"_id": contest_id},
        {"$set": {"problem_ids": ids, "problem_configs": configs, "updated_at": now_iso()}},
    )
    await audit(contest_id, actor, "set_problems", {"problem_ids": ids})
    return await get_contest(contest_id)


async def stop_contest(contest_id: str, actor: str = "system") -> Optional[dict]:
    """Admin "end now" action — immediately ends a contest regardless of its
    scheduled `end_at`. Irreversible from the participant's point of view:
    once stopped, contest_status() always reports "ended" for this contest
    (see the flag check above), so a submission attempted right after this
    call is rejected exactly like one made after the original deadline.
    (An admin can still `extend_contest()` to deliberately reopen it.)"""
    stamp = now_iso()
    contest = await get_contest(contest_id)
    pauses = list((contest or {}).get("pauses") or [])
    if pauses and not pauses[-1].get("end"):
        pauses[-1]["end"] = stamp
    await contests_col.update_one(
        {"_id": contest_id},
        {"$set": {"ended_early": True, "end_at": stamp, "paused_at": None, "pauses": pauses, "updated_at": stamp}},
    )
    await audit(contest_id, actor, "stop")
    return await get_contest(contest_id)


async def start_now(contest_id: str, actor: str = "system") -> dict:
    c = await get_contest(contest_id)
    if not c:
        raise ValueError("Contest not found")
    if contest_status(c) not in ("draft", "upcoming"):
        raise ValueError("Only a draft or upcoming contest can be started now")
    now = now_utc().replace(microsecond=0)
    duration = max(_parse_iso(c["end_at"]) - _parse_iso(c["start_at"]), timedelta(minutes=1))
    await contests_col.update_one({"_id": contest_id}, {"$set": {
        "start_at": now.isoformat(), "end_at": (now + duration).isoformat(), "state": "published",
        "ended_early": False, "paused_at": None, "pauses": [], "updated_at": now_iso(),
    }})
    await audit(contest_id, actor, "start_now")
    return await get_contest(contest_id)


async def pause_contest(contest_id: str, actor: str = "system") -> dict:
    c = await get_contest(contest_id)
    if not c:
        raise ValueError("Contest not found")
    if contest_status(c) != "live":
        raise ValueError("Only a live contest can be paused")
    stamp = now_iso()
    pauses = list(c.get("pauses") or []) + [{"start": stamp, "end": None}]
    await contests_col.update_one({"_id": contest_id}, {"$set": {"paused_at": stamp, "pauses": pauses, "updated_at": stamp}})
    await audit(contest_id, actor, "pause")
    return await get_contest(contest_id)


async def resume_contest(contest_id: str, actor: str = "system") -> dict:
    c = await get_contest(contest_id)
    if not c:
        raise ValueError("Contest not found")
    if contest_status(c) != "paused":
        raise ValueError("Contest is not paused")
    now = now_utc()
    paused_for = now - _parse_iso(c["paused_at"])
    pauses = list(c.get("pauses") or [])
    if pauses and not pauses[-1].get("end"):
        pauses[-1]["end"] = now.isoformat()
    new_end = (_parse_iso(c["end_at"]) + paused_for).isoformat()  # paused time is not lost
    await contests_col.update_one({"_id": contest_id}, {"$set": {
        "paused_at": None, "pauses": pauses, "end_at": new_end, "updated_at": now_iso(),
    }})
    await audit(contest_id, actor, "resume", {"paused_seconds": round(paused_for.total_seconds())})
    return await get_contest(contest_id)


async def extend_contest(contest_id: str, minutes: int, actor: str = "system") -> dict:
    if not (1 <= minutes <= 60 * 24 * 14):
        raise ValueError("minutes must be between 1 and 20160")
    c = await get_contest(contest_id)
    if not c:
        raise ValueError("Contest not found")
    now = now_utc()
    if contest_status(c) == "ended":
        # Deliberately reopening an ended contest.
        new_end = now + timedelta(minutes=minutes)
        extra = {"ended_early": False}
    else:
        new_end = _parse_iso(c["end_at"]) + timedelta(minutes=minutes)
        extra = {}
    await contests_col.update_one({"_id": contest_id}, {"$set": {"end_at": new_end.isoformat(), "updated_at": now_iso(), **extra}})
    await audit(contest_id, actor, "extend", {"minutes": minutes})
    return await get_contest(contest_id)


async def archive_contest(contest_id: str, archived: bool, actor: str = "system") -> dict:
    await contests_col.update_one({"_id": contest_id}, {"$set": {"archived": bool(archived), "updated_at": now_iso()}})
    await audit(contest_id, actor, "archive" if archived else "unarchive")
    return await get_contest(contest_id)


async def duplicate_contest(contest_id: str, actor: str, name: Optional[str] = None) -> dict:
    c = await get_contest(contest_id)
    if not c:
        raise ValueError("Contest not found")
    duration = _parse_iso(c["end_at"]) - _parse_iso(c["start_at"])
    # Participants, submissions, invites, announcements and runtime flags are
    # never copied — only the configuration.
    start = (now_utc() + timedelta(days=1)).replace(minute=0, second=0, microsecond=0)
    doc = {
        **{k: c[k] for k in ("problem_ids", "landing_page") if k in c},
        "_id": uuid.uuid4().hex,
        "name": name or f"{c['name']} (copy)",
        "problem_configs": c.get("problem_configs") or {},
        "settings": c.get("settings") or default_settings_dict(),
        "state": "draft", "archived": False,
        "start_at": start.isoformat(), "end_at": (start + duration).isoformat(),
        "created_by": actor, "ended_early": False, "paused_at": None, "pauses": [],
        "invited_emails": [], "disqualified_user_ids": [],
        "created_at": now_iso(), "updated_at": now_iso(),
    }
    await contests_col.insert_one(doc)
    await audit(doc["_id"], actor, "duplicate", {"from": contest_id})
    return doc


async def delete_contest(contest_id: str, actor: str = "system") -> bool:
    res = await contests_col.delete_one({"_id": contest_id})
    if not res.deleted_count:
        return False
    for col in (contest_teams_col, contest_submissions_col, contest_adjustments_col,
                contest_announcements_col, contest_clarifications_col):
        await col.delete_many({"contest_id": contest_id})
    # The audit trail is kept (with a tombstone entry) so deletions are traceable.
    await audit(contest_id, actor, "delete")
    return True


# ---------------------------------------------------------------------------
# Public (participant-facing) shapes
# ---------------------------------------------------------------------------
async def participant_count(contest_id: str) -> int:
    n = 0
    async for t in contest_teams_col.find({"contest_id": contest_id}, {"member_user_ids": 1}):
        n += len(t["member_user_ids"])
    return n


def registration_state(contest: dict, participants: int, now: Optional[datetime] = None) -> dict:
    """Can new teams/members register right now, and if not, why."""
    now = now or now_utc()
    reg = parse_settings(contest.get("settings")).registration
    status = contest_status(contest, now)
    mn, mx = reg.effective_sizes()
    info = {"open": True, "reason": None, "mode": reg.mode, "min_team_size": mn, "max_team_size": mx,
            "access": reg.access, "cap": reg.cap, "spots_left": (reg.cap - participants) if reg.cap else None,
            "open_at": reg.open_at, "close_at": reg.close_at}
    reason = None
    if status == "draft":
        reason = "This contest is not published yet"
    elif status == "ended":
        reason = "This contest has already ended"
    elif not reg.open:
        reason = "Registration is closed"
    elif reg.open_at and now < _parse_iso(reg.open_at):
        reason = f"Registration opens at {reg.open_at}"
    elif reg.close_at and now > _parse_iso(reg.close_at):
        reason = "Registration has closed"
    elif reg.cap and participants >= reg.cap:
        reason = "This contest is full"
    if reason:
        info["open"], info["reason"] = False, reason
    return info


def _problem_public(contest: dict, pid: str, p: Optional[dict], cfg: ProblemConfig, now: datetime, is_admin: bool,
                    attempts: int = 0) -> dict:
    released = scoring.is_released(contest, cfg, now)
    rel = scoring.release_time(contest, cfg)
    sc = parse_settings(contest.get("settings")).scoring
    base = {
        "id": pid, "points": cfg.points, "locked": not released and not is_admin,
        "release_at": rel.isoformat() if rel else None, "hidden": cfg.hidden,
        "time_limit_ms": cfg.time_limit_ms, "memory_limit_mb": cfg.memory_limit_mb,
        "allowed_languages": cfg.allowed_languages,
        "max_attempts": cfg.max_attempts if cfg.max_attempts is not None else sc.max_attempts,
        "attempts": attempts,
    }
    if base["locked"] or not p:
        return {**base, "title": "Locked problem", "difficulty": None, "tags": []}
    return {**base, "title": p["title"], "difficulty": p["difficulty"], "tags": p["tags"]}


def public_settings(contest: dict) -> dict:
    """The slice of settings participants may see (never the access code or
    invite list)."""
    s = parse_settings(contest.get("settings"))
    return {
        "scoring": {
            "mode": s.scoring.mode, "penalty_minutes_per_wrong": s.scoring.penalty_minutes_per_wrong,
            "wrong_penalty_points": s.scoring.wrong_penalty_points, "first_solve_bonus": s.scoring.first_solve_bonus,
            "speed_bonus_max": s.scoring.speed_bonus_max, "milestone_bonuses": [m.model_dump() for m in s.scoring.milestone_bonuses],
            "max_attempts": s.scoring.max_attempts, "partial_scoring": s.scoring.partial_scoring,
            "tie_breakers": s.scoring.tie_breakers,
        },
        "leaderboard": {"freeze_minutes": s.leaderboard.freeze_minutes, "visibility": s.leaderboard.visibility},
        "prizes": [p.model_dump() for p in s.prizes],
        "certificate": s.certificate.model_dump(),
        "branding": s.branding.model_dump(),
        "clarifications_enabled": s.clarifications_enabled,
    }


async def get_contest_public(contest_id: str, user_id: Optional[str] = None, is_admin: bool = False) -> Optional[dict]:
    """Participant-facing contest detail: the problem set (public shape, same
    as /practice/problems/{id} summaries) plus the caller's own team, if any.
    Never includes another user's team info — only the caller's. Drafts are
    invisible to non-admins; locked (not-yet-released) problems are redacted
    to id + release time."""
    contest = await get_contest(contest_id)
    if not contest:
        return None
    if contest.get("state") == "draft" and not is_admin:
        return None
    now = now_utc()
    team = await get_my_team(contest["_id"], user_id) if user_id else None
    attempts_by_problem: Dict[str, int] = {}
    if team:
        async for s in contest_submissions_col.find({"contest_id": contest_id, "team_id": team["_id"]}, {"problem_id": 1}):
            attempts_by_problem[s["problem_id"]] = attempts_by_problem.get(s["problem_id"], 0) + 1
    problems = []
    for pid in contest["problem_ids"]:
        cfg = parse_problem_config((contest.get("problem_configs") or {}).get(pid))
        if cfg.hidden and not is_admin:
            continue
        p = await get_problem_public(pid)
        if not p and not is_admin:
            continue
        problems.append(_problem_public(contest, pid, p, cfg, now, is_admin, attempts_by_problem.get(pid, 0)))
    count = await participant_count(contest_id)
    out = {
        "id": contest["_id"],
        "name": contest["name"],
        "start_at": contest["start_at"],
        "end_at": contest["end_at"],
        "status": contest_status(contest, now),
        "state": contest.get("state", "published"),
        "archived": bool(contest.get("archived")),
        "server_now": now.isoformat(),
        "ended_early": bool(contest.get("ended_early")),
        "paused": bool(contest.get("paused_at")),
        "problems": problems,
        # Structured, pre-generated (never regenerated per view) copy for the
        # not-yet-registered landing page — see generate_landing_page() above.
        "landing_page": contest.get("landing_page"),
        "settings": public_settings(contest),
        "registration": registration_state(contest, count, now),
        "participant_count": count,
    }
    if user_id:
        out["my_team"] = _team_public(team) if team else None
        reg = parse_settings(contest.get("settings")).registration
        if reg.access == "invite_only":
            email = await _user_email(user_id)
            out["invited"] = bool(email and email in [e.lower() for e in contest.get("invited_emails") or []])
    return out


def _team_public(t: dict) -> dict:
    return {
        "id": t["_id"], "contest_id": t["contest_id"], "name": t["name"],
        "member_user_ids": t["member_user_ids"], "created_by": t["created_by"],
        "is_open": bool(t.get("is_open")),
        "disqualified": bool(t.get("disqualified")),
        "created_at": t["created_at"],
    }


async def _user_email(user_id: str) -> Optional[str]:
    try:
        d = await users_col.find_one({"_id": ObjectId(user_id)}, {"email": 1})
    except Exception:
        return None
    return (d or {}).get("email", "").lower() or None


# ---------------------------------------------------------------------------
# Teams — size limits, solo/team/both mode, registration window, cap and
# access (public / invite-only / code) all come from the contest's
# `settings.registration` (defaults: 1-3 members, public, always open until the
# contest ends). One team per contest per user. Three ways onto a team:
#   1. Create a team and invite named teammates by email (member_user_ids).
#   2. Register solo (member_user_ids=[]) — a team of 1 is valid where the mode
#      allows it. Optionally mark it `open_to_join` so others can join it.
#   3. Browse list_open_teams() and join_open_team() into an existing team
#      someone else created, without knowing anyone's email in advance.
# Admins can bypass every check via add_participant() below.
# ---------------------------------------------------------------------------
async def get_my_team(contest_id: str, user_id: str) -> Optional[dict]:
    return await contest_teams_col.find_one({"contest_id": contest_id, "member_user_ids": user_id})


def _check_access(contest: dict, email: Optional[str], access_code: Optional[str]) -> None:
    reg = parse_settings(contest.get("settings")).registration
    if reg.access == "invite_only":
        invited = {e.lower() for e in contest.get("invited_emails") or []}
        if not email or email not in invited:
            raise ValueError("This contest is invite-only — your email is not on the invite list")
    elif reg.access == "code":
        if not hmac.compare_digest((access_code or "").strip().encode(), (reg.access_code or "").strip().encode()):
            raise ValueError("A valid access code is required to register for this contest")


async def _check_can_register(contest: dict, user_id: str, new_participants: int, access_code: Optional[str]) -> None:
    status = contest_status(contest)
    if status == "ended":
        raise ValueError("This contest has already ended — no new teams can be formed")
    state = registration_state(contest, await participant_count(contest["_id"]))
    if not state["open"]:
        raise ValueError(state["reason"])
    reg = parse_settings(contest.get("settings")).registration
    if reg.cap and state["spots_left"] is not None and state["spots_left"] < new_participants:
        raise ValueError("This contest is full")
    _check_access(contest, await _user_email(user_id), access_code)


async def create_team(
    contest_id: str, name: str, member_user_ids: List[str], created_by: str, open_to_join: bool = False,
    access_code: Optional[str] = None,
) -> dict:
    contest = await get_contest(contest_id)
    if not contest or contest.get("state") == "draft":
        raise ValueError("Contest not found")
    if contest_status(contest) == "ended":
        raise ValueError("This contest has already ended — no new teams can be formed")

    reg = parse_settings(contest.get("settings")).registration
    min_size, max_size = reg.effective_sizes()
    members = list(dict.fromkeys(member_user_ids))  # de-dup, preserve order
    if created_by not in members:
        members.insert(0, created_by)
    too_small = len(members) < min_size and not (open_to_join and len(members) < max_size)
    if too_small or len(members) > max_size:
        raise ValueError(f"A team must have {min_size}-{max_size} members (got {len(members)})")

    found_ids = set()
    for uid in members:
        try:
            if await users_col.find_one({"_id": ObjectId(uid)}, {"_id": 1}):
                found_ids.add(uid)
        except Exception:
            pass
    missing = [m for m in members if m not in found_ids]
    if missing:
        raise ValueError(f"Unknown user id(s): {', '.join(missing)}")

    # Registration window / cap / access are checked for the creator, and the
    # cap for every member being added.
    await _check_can_register(contest, created_by, len(members), access_code)

    # One team per user per contest — check every incoming member, not just
    # the creator.
    existing = await contest_teams_col.find_one(
        {"contest_id": contest_id, "member_user_ids": {"$in": members}}
    )
    if existing:
        raise ValueError("One or more of these members is already on a team for this contest")

    doc = {
        "_id": uuid.uuid4().hex,
        "contest_id": contest_id,
        "name": name,
        "member_user_ids": members,
        "created_by": created_by,
        # Only meaningful while the team still has a free slot — see
        # list_open_teams(), which also filters on capacity.
        "is_open": bool(open_to_join) and len(members) < max_size,
        "disqualified": False,
        "created_at": now_iso(),
    }
    await contest_teams_col.insert_one(doc)
    return doc


async def list_teams(contest_id: str) -> List[dict]:
    items = []
    async for d in contest_teams_col.find({"contest_id": contest_id}):
        items.append(d)
    return items


async def list_open_teams(contest_id: str) -> List[dict]:
    """Teams in this contest marked `is_open` that still have a free slot —
    the "browse and join" path for a user with no pre-formed squad."""
    contest = await get_contest(contest_id)
    max_size = parse_settings((contest or {}).get("settings")).registration.effective_sizes()[1]
    items = []
    async for d in contest_teams_col.find({"contest_id": contest_id, "is_open": True}):
        if len(d["member_user_ids"]) < max_size:
            items.append(d)
    return items


async def join_open_team(contest_id: str, team_id: str, user_id: str, access_code: Optional[str] = None) -> dict:
    """A solo (or otherwise teamless) user joins an existing open team
    directly — no email/invite needed."""
    contest = await get_contest(contest_id)
    if not contest or contest.get("state") == "draft":
        raise ValueError("Contest not found")
    if contest_status(contest) == "ended":
        raise ValueError("This contest has already ended — no new teams can be joined")
    max_size = parse_settings(contest.get("settings")).registration.effective_sizes()[1]

    if await get_my_team(contest_id, user_id):
        raise ValueError("You are already on a team for this contest")
    await _check_can_register(contest, user_id, 1, access_code)

    team = await contest_teams_col.find_one({"_id": team_id, "contest_id": contest_id})
    if not team:
        raise ValueError("Team not found")
    if not team.get("is_open"):
        raise ValueError("This team is not open to new members")
    if len(team["member_user_ids"]) >= max_size:
        raise ValueError("This team is already full")

    # Re-check capacity atomically at write time (best-effort against a
    # concurrent joiner landing between the read above and this update —
    # mirrors the same check-then-write style create_team() already uses for
    # its own "already on a team" guard elsewhere in this module).
    result = await contest_teams_col.update_one(
        {"_id": team_id, "contest_id": contest_id, "is_open": True},
        {"$addToSet": {"member_user_ids": user_id}},
    )
    if result.matched_count == 0:
        raise ValueError("This team is no longer open to new members")
    updated = await contest_teams_col.find_one({"_id": team_id})
    if len(updated["member_user_ids"]) > max_size:
        # Lost a race against another joiner who filled the last slot first —
        # roll back and surface a clear, actionable error.
        await contest_teams_col.update_one({"_id": team_id}, {"$pull": {"member_user_ids": user_id}})
        raise ValueError("This team just filled up — pick another open team")

    # A team that just reached capacity stops being listed as open.
    if len(updated["member_user_ids"]) >= max_size:
        await contest_teams_col.update_one({"_id": team_id}, {"$set": {"is_open": False}})
        updated["is_open"] = False
    return updated


# ---------------------------------------------------------------------------
# Admin participant management
# ---------------------------------------------------------------------------
async def add_participant(
    contest_id: str, email: str, actor: str, team_id: Optional[str] = None, team_name: Optional[str] = None,
) -> dict:
    """Add a user to the contest manually, bypassing window/cap/access/size
    checks (admin override). Creates a solo team unless `team_id` is given."""
    contest = await get_contest(contest_id)
    if not contest:
        raise ValueError("Contest not found")
    user = await users_col.find_one({"email": email.strip().lower()})
    if not user:
        raise ValueError(f"No user with email `{email}` — ask them to sign up first, or send an invite")
    uid = str(user["_id"])
    if await get_my_team(contest_id, uid):
        raise ValueError("That user is already on a team for this contest")
    if team_id:
        team = await contest_teams_col.find_one({"_id": team_id, "contest_id": contest_id})
        if not team:
            raise ValueError("Team not found")
        await contest_teams_col.update_one({"_id": team_id}, {"$addToSet": {"member_user_ids": uid}})
        team = await contest_teams_col.find_one({"_id": team_id})
    else:
        team = {
            "_id": uuid.uuid4().hex, "contest_id": contest_id, "name": (team_name or user.get("name") or "Team")[:80],
            "member_user_ids": [uid], "created_by": uid, "is_open": False, "disqualified": False,
            "created_at": now_iso(),
        }
        await contest_teams_col.insert_one(team)
    await audit(contest_id, actor, "add_participant", {"user_id": uid, "team_id": team["_id"]})
    return team


async def remove_participant(contest_id: str, user_id: str, actor: str) -> bool:
    team = await get_my_team(contest_id, user_id)
    if not team:
        return False
    remaining = [u for u in team["member_user_ids"] if u != user_id]
    if remaining:
        await contest_teams_col.update_one({"_id": team["_id"]}, {"$set": {"member_user_ids": remaining}})
    else:
        await contest_teams_col.delete_one({"_id": team["_id"]})
    await audit(contest_id, actor, "remove_participant", {"user_id": user_id, "team_id": team["_id"]})
    return True


async def remove_team(contest_id: str, team_id: str, actor: str) -> bool:
    res = await contest_teams_col.delete_one({"_id": team_id, "contest_id": contest_id})
    if res.deleted_count:
        await contest_submissions_col.delete_many({"contest_id": contest_id, "team_id": team_id})
        await contest_adjustments_col.delete_many({"contest_id": contest_id, "team_id": team_id})
        await audit(contest_id, actor, "remove_team", {"team_id": team_id})
    return bool(res.deleted_count)


async def set_team_disqualified(contest_id: str, team_id: str, disqualified: bool, reason: str, actor: str) -> dict:
    if disqualified and len((reason or "").strip()) < 3:
        raise ValueError("A reason is required to disqualify a team")
    res = await contest_teams_col.update_one(
        {"_id": team_id, "contest_id": contest_id},
        {"$set": {"disqualified": bool(disqualified), "dq_reason": reason if disqualified else None}},
    )
    if not res.matched_count:
        raise ValueError("Team not found")
    await audit(contest_id, actor, "disqualify_team" if disqualified else "reinstate_team",
                {"team_id": team_id, "reason": reason})
    return await contest_teams_col.find_one({"_id": team_id})


async def set_user_disqualified(contest_id: str, user_id: str, disqualified: bool, reason: str, actor: str) -> None:
    if disqualified and len((reason or "").strip()) < 3:
        raise ValueError("A reason is required to disqualify a participant")
    op = {"$addToSet": {"disqualified_user_ids": user_id}} if disqualified else {"$pull": {"disqualified_user_ids": user_id}}
    res = await contests_col.update_one({"_id": contest_id}, op)
    if not res.matched_count:
        raise ValueError("Contest not found")
    await audit(contest_id, actor, "disqualify_user" if disqualified else "reinstate_user",
                {"user_id": user_id, "reason": reason})


async def list_participants(contest_id: str, q: str = "") -> List[dict]:
    contest = await get_contest(contest_id)
    dq_users = set((contest or {}).get("disqualified_user_ids") or [])
    teams = await list_teams(contest_id)
    sub_counts: Dict[str, int] = {}
    async for s in contest_submissions_col.find({"contest_id": contest_id}, {"user_id": 1}):
        sub_counts[s["user_id"]] = sub_counts.get(s["user_id"], 0) + 1
    uids = {u for t in teams for u in t["member_user_ids"]}
    oids = []
    for u in uids:
        try:
            oids.append(ObjectId(u))
        except Exception:
            pass
    users: Dict[str, dict] = {}
    async for u in users_col.find({"_id": {"$in": oids}}, {"name": 1, "email": 1}):
        users[str(u["_id"])] = u
    needle = (q or "").strip().lower()
    rows = []
    for t in teams:
        for uid in t["member_user_ids"]:
            u = users.get(uid, {})
            row = {
                "user_id": uid, "name": u.get("name", "Unknown"), "email": u.get("email", ""),
                "team_id": t["_id"], "team_name": t["name"], "team_size": len(t["member_user_ids"]),
                "team_disqualified": bool(t.get("disqualified")), "user_disqualified": uid in dq_users,
                "submissions": sub_counts.get(uid, 0), "joined_at": t["created_at"],
            }
            if needle and needle not in f"{row['name']} {row['email']} {row['team_name']}".lower():
                continue
            rows.append(row)
    return rows


async def bulk_invite(contest_id: str, emails: List[str], actor: str) -> dict:
    """Add emails to the contest's invite list (used by invite-only access)
    and send each an invitation email (a dev-mode log line when no mail
    provider is configured)."""
    contest = await get_contest(contest_id)
    if not contest:
        raise ValueError("Contest not found")
    existing = {e.lower() for e in contest.get("invited_emails") or []}
    added, already, invalid = [], [], []
    for raw in emails[:500]:
        e = (raw or "").strip().lower()
        if not _EMAIL_RE.match(e):
            invalid.append(raw)
        elif e in existing or e in added:
            already.append(e)
        else:
            added.append(e)
    if added:
        await contests_col.update_one({"_id": contest_id}, {"$addToSet": {"invited_emails": {"$each": added}}})
        from services.email_service import send_email
        html = (
            f"<p>You have been invited to <b>{html_escape(contest['name'])}</b>.</p>"
            f"<p>Sign in (or create a free account) with this email address and open Contest Mode to register.</p>"
        )
        for e in added:
            try:
                await send_email(e, f"You're invited: {contest['name']}", html)
            except Exception as exc:  # an email hiccup must never fail the invite itself
                logger.warning("Contest invite email to %s failed: %s", e, exc)
    await audit(contest_id, actor, "bulk_invite", {"added": len(added)})
    return {"added": added, "already_invited": already, "invalid": invalid}


# ---------------------------------------------------------------------------
# Announcements + clarifications
# ---------------------------------------------------------------------------
async def create_announcement(contest_id: str, text: str, pinned: bool, actor: str) -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("Announcement text is required")
    doc = {"_id": uuid.uuid4().hex, "contest_id": contest_id, "text": text[:2000], "pinned": bool(pinned),
           "created_by": actor, "created_at": now_iso()}
    await contest_announcements_col.insert_one(doc)
    await audit(contest_id, actor, "announce", {"text": text[:120]})
    return _announcement_out(doc)


def _announcement_out(d: dict) -> dict:
    return {"id": d["_id"], "text": d["text"], "pinned": bool(d.get("pinned")), "created_at": d["created_at"]}


async def list_announcements(contest_id: str, limit: int = 50) -> List[dict]:
    items = []
    async for d in contest_announcements_col.find({"contest_id": contest_id}).sort("created_at", -1).limit(limit):
        items.append(_announcement_out(d))
    items.sort(key=lambda a: not a["pinned"])  # stable: pinned first, newest first within each group
    return items


async def delete_announcement(contest_id: str, ann_id: str, actor: str) -> bool:
    res = await contest_announcements_col.delete_one({"_id": ann_id, "contest_id": contest_id})
    if res.deleted_count:
        await audit(contest_id, actor, "delete_announcement", {"id": ann_id})
    return bool(res.deleted_count)


def _clar_out(d: dict, admin: bool = False) -> dict:
    out = {
        "id": d["_id"], "problem_id": d.get("problem_id"), "question": d["question"],
        "answer": d.get("answer"), "public": bool(d.get("public")),
        "created_at": d["created_at"], "answered_at": d.get("answered_at"),
    }
    if admin:
        out["user_id"] = d["user_id"]
        out["user_name"] = d.get("user_name")
    return out


async def ask_clarification(contest_id: str, user_id: str, user_name: str, question: str, problem_id: Optional[str]) -> dict:
    contest = await get_contest(contest_id)
    if not contest or contest.get("state") == "draft":
        raise ValueError("Contest not found")
    if not parse_settings(contest.get("settings")).clarifications_enabled:
        raise ValueError("Clarifications are disabled for this contest")
    if not await get_my_team(contest_id, user_id):
        raise ValueError("Register for the contest to ask a question")
    question = (question or "").strip()
    if not question:
        raise ValueError("Question is required")
    if await contest_clarifications_col.count_documents({"contest_id": contest_id, "user_id": user_id}) >= 30:
        raise ValueError("You've reached the question limit for this contest")
    doc = {"_id": uuid.uuid4().hex, "contest_id": contest_id, "user_id": user_id, "user_name": user_name,
           "problem_id": problem_id, "question": question[:1000], "answer": None, "public": False,
           "created_at": now_iso(), "answered_at": None}
    await contest_clarifications_col.insert_one(doc)
    return _clar_out(doc)


async def list_clarifications(contest_id: str, user_id: Optional[str] = None, admin: bool = False) -> List[dict]:
    items = []
    async for d in contest_clarifications_col.find({"contest_id": contest_id}).sort("created_at", -1).limit(300):
        if admin or d["user_id"] == user_id or (d.get("public") and d.get("answer")):
            items.append(_clar_out(d, admin))
    return items


async def answer_clarification(contest_id: str, clar_id: str, answer: str, public: bool, actor: str) -> dict:
    answer = (answer or "").strip()
    if not answer:
        raise ValueError("Answer is required")
    res = await contest_clarifications_col.update_one(
        {"_id": clar_id, "contest_id": contest_id},
        {"$set": {"answer": answer[:2000], "public": bool(public), "answered_at": now_iso(), "answered_by": actor}},
    )
    if not res.matched_count:
        raise ValueError("Question not found")
    await audit(contest_id, actor, "answer_clarification", {"id": clar_id, "public": bool(public)})
    return _clar_out(await contest_clarifications_col.find_one({"_id": clar_id}), admin=True)


# ---------------------------------------------------------------------------
# Contest submissions — separate ledger from practice_submissions (see module
# docstring). NEVER charges credits; the caller (routers/contest_routes.py)
# must not call precheck()/spend() for this path.
# ---------------------------------------------------------------------------
async def record_contest_submission(
    contest_id: str, team_id: str, user_id: str, problem_id: str,
    language: str, code: str, run_result: Dict[str, Any],
) -> dict:
    flags = [bool(r.get("passed")) for r in (run_result.get("results") or [])]
    doc = {
        "contest_id": contest_id,
        "team_id": team_id,
        "user_id": user_id,
        "problem_id": problem_id,
        "language": language,
        "code": code[:20000],
        "passed_count": run_result["passed_count"],
        "total": run_result["total"],
        "all_passed": run_result["all_passed"],
        # Per-test verdicts (by test index) so partial scoring / weights can be
        # re-applied later without re-running the code.
        "passed_flags": flags,
        "created_at": now_iso(),
    }
    ins = await contest_submissions_col.insert_one(doc)
    doc["_id"] = str(ins.inserted_id)
    return doc


async def count_attempts(contest_id: str, team_id: str, problem_id: str) -> int:
    return await contest_submissions_col.count_documents(
        {"contest_id": contest_id, "team_id": team_id, "problem_id": problem_id, "invalidated": {"$ne": True}}
    )


async def has_solved(contest: dict, team_id: str, problem_id: str) -> bool:
    cfg = parse_problem_config((contest.get("problem_configs") or {}).get(problem_id))
    partial = parse_settings(contest.get("settings")).scoring.partial_scoring
    async for s in contest_submissions_col.find(
        {"contest_id": contest["_id"], "team_id": team_id, "problem_id": problem_id, "invalidated": {"$ne": True}}
    ):
        if scoring.submission_fraction(s, cfg, partial) >= 1.0 - scoring.EPS:
            return True
    return False


def max_attempts_for(contest: dict, problem_id: str) -> int:
    cfg = parse_problem_config((contest.get("problem_configs") or {}).get(problem_id))
    if cfg.max_attempts is not None:
        return cfg.max_attempts
    return parse_settings(contest.get("settings")).scoring.max_attempts


# ---------------------------------------------------------------------------
# Manual scoring controls: adjustments (grace / override), per-submission
# override or invalidation, rejudge. Every one is audit-logged.
# ---------------------------------------------------------------------------
def _adj_out(a: dict) -> dict:
    return {"id": a["_id"], "team_id": a["team_id"], "kind": a["kind"], "points": a.get("points", 0),
            "penalty_minutes": a.get("penalty_minutes", 0), "reason": a["reason"],
            "created_by": a["created_by"], "created_at": a["created_at"]}


async def add_adjustment(
    contest_id: str, team_id: str, kind: str, points: float, penalty_minutes: float, reason: str, actor: str,
) -> dict:
    if kind not in ("grace", "override"):
        raise ValueError("kind must be 'grace' or 'override'")
    if len((reason or "").strip()) < 3:
        raise ValueError("A reason is required for every manual adjustment")
    if not await contest_teams_col.find_one({"_id": team_id, "contest_id": contest_id}, {"_id": 1}):
        raise ValueError("Team not found")
    doc = {"_id": uuid.uuid4().hex, "contest_id": contest_id, "team_id": team_id, "kind": kind,
           "points": float(points), "penalty_minutes": float(penalty_minutes), "reason": reason.strip()[:500],
           "created_by": actor, "created_at": now_iso()}
    await contest_adjustments_col.insert_one(doc)
    await audit(contest_id, actor, f"adjust_{kind}", {"team_id": team_id, "points": points,
                                                        "penalty_minutes": penalty_minutes, "reason": reason})
    return _adj_out(doc)


async def list_adjustments(contest_id: str) -> List[dict]:
    items = []
    async for a in contest_adjustments_col.find({"contest_id": contest_id}).sort("created_at", -1):
        items.append(_adj_out(a))
    return items


async def delete_adjustment(contest_id: str, adj_id: str, actor: str) -> bool:
    res = await contest_adjustments_col.delete_one({"_id": adj_id, "contest_id": contest_id})
    if res.deleted_count:
        await audit(contest_id, actor, "delete_adjustment", {"id": adj_id})
    return bool(res.deleted_count)


async def override_submission(
    contest_id: str, submission_id: str, fraction: Optional[float], invalidated: Optional[bool],
    reason: str, actor: str,
) -> dict:
    """Manually set a submission's score fraction (0..1) and/or void it
    entirely (e.g. cheating, infra failure)."""
    if len((reason or "").strip()) < 3:
        raise ValueError("A reason is required")
    try:
        oid = ObjectId(submission_id)
    except Exception:
        raise ValueError("Submission not found")
    sets: Dict[str, Any] = {}
    if fraction is not None:
        if not (0 <= fraction <= 1):
            raise ValueError("fraction must be between 0 and 1")
        sets["fraction_override"] = float(fraction)
    if invalidated is not None:
        sets["invalidated"] = bool(invalidated)
    if not sets:
        raise ValueError("Nothing to change")
    res = await contest_submissions_col.update_one({"_id": oid, "contest_id": contest_id}, {"$set": sets})
    if not res.matched_count:
        raise ValueError("Submission not found")
    await audit(contest_id, actor, "override_submission", {"submission_id": submission_id, **sets, "reason": reason})
    return _sub_out(await contest_submissions_col.find_one({"_id": oid}))


def _sub_out(s: dict, with_code: bool = False) -> dict:
    out = {
        "id": str(s["_id"]), "team_id": s["team_id"], "user_id": s["user_id"], "problem_id": s["problem_id"],
        "language": s["language"], "passed_count": s["passed_count"], "total": s["total"],
        "all_passed": s["all_passed"], "created_at": s["created_at"],
        "fraction_override": s.get("fraction_override"), "invalidated": bool(s.get("invalidated")),
        "rejudged_at": s.get("rejudged_at"),
    }
    if with_code:
        out["code"] = s.get("code", "")
    return out


async def list_submissions(contest_id: str, problem_id: Optional[str] = None, team_id: Optional[str] = None,
                           limit: int = 200) -> List[dict]:
    q: Dict[str, Any] = {"contest_id": contest_id}
    if problem_id:
        q["problem_id"] = problem_id
    if team_id:
        q["team_id"] = team_id
    items = []
    async for s in contest_submissions_col.find(q).sort("created_at", -1).limit(limit):
        items.append(_sub_out(s))
    return items


async def rejudge(contest_id: str, actor: str, submission_id: Optional[str] = None,
                  problem_id: Optional[str] = None) -> dict:
    """Re-run stored code through the grader with the contest's CURRENT
    problem config (time/memory limits) and refresh the stored verdicts —
    standings follow automatically. Pass a submission id or a problem id."""
    from services.practice_service import run_submission  # local: tests monkeypatch the httpx boundary
    contest = await get_contest(contest_id)
    if not contest:
        raise ValueError("Contest not found")
    q: Dict[str, Any] = {"contest_id": contest_id}
    if submission_id:
        try:
            q["_id"] = ObjectId(submission_id)
        except Exception:
            raise ValueError("Submission not found")
    elif problem_id:
        q["problem_id"] = problem_id
    else:
        raise ValueError("Provide submission_id or problem_id")
    subs = [s async for s in contest_submissions_col.find(q).limit(500)]
    if not subs:
        raise ValueError("No matching submissions")
    changed = 0
    for s in subs:
        problem = await get_problem_raw(s["problem_id"])
        if not problem:
            continue
        cfg = parse_problem_config((contest.get("problem_configs") or {}).get(s["problem_id"]))
        res = await run_submission(problem, s["code"], s["language"], time_limit_ms=cfg.time_limit_ms,
                                   memory_limit_mb=cfg.memory_limit_mb, visible_indices=cfg.visible_tests)
        flags = [bool(r.get("passed")) for r in res["results"]]
        if flags != s.get("passed_flags") or res["all_passed"] != s["all_passed"]:
            changed += 1
        await contest_submissions_col.update_one({"_id": s["_id"]}, {"$set": {
            "passed_count": res["passed_count"], "total": res["total"], "all_passed": res["all_passed"],
            "passed_flags": flags, "rejudged_at": now_iso(),
        }})
    await audit(contest_id, actor, "rejudge", {"submission_id": submission_id, "problem_id": problem_id,
                                              "count": len(subs), "changed": changed})
    return {"rejudged": len(subs), "changed": changed}


async def plagiarism_report(contest_id: str) -> List[dict]:
    subs = [s async for s in contest_submissions_col.find({"contest_id": contest_id, "all_passed": True})]
    groups = scoring.find_duplicate_groups(subs)
    teams = {t["_id"]: t["name"] for t in await list_teams(contest_id)}
    for g in groups:
        g["team_names"] = [teams.get(t, "?") for t in g["team_ids"]]
    return groups


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------
async def _member_names(rows: List[dict]) -> None:
    """Batch-resolve member display names for the frontend."""
    all_uids = {uid for r in rows for uid in r["member_user_ids"]}
    names: Dict[str, str] = {}
    if all_uids:
        object_ids = []
        for uid in all_uids:
            try:
                object_ids.append(ObjectId(uid))
            except Exception:
                pass
        async for u in users_col.find({"_id": {"$in": object_ids}}, {"name": 1}):
            names[str(u["_id"])] = u.get("name", "Unknown")
    for r in rows:
        r["members"] = [{"user_id": uid, "name": names.get(uid, "Unknown")} for uid in r["member_user_ids"]]


async def compute_leaderboard(
    contest_id: str, include_dq: bool = False, as_of: Optional[datetime] = None,
) -> List[dict]:
    """Ranked standings under the contest's scoring rules (see
    services/contest_scoring.py for the full rule list). Default behaviour —
    no settings — is the original one: most distinct problems solved, ties
    broken by lower total time-to-solve, then team creation time."""
    contest = await get_contest(contest_id)
    if not contest:
        return []
    teams = await list_teams(contest_id)
    subs = [s async for s in contest_submissions_col.find({"contest_id": contest_id})]
    adjustments = [a async for a in contest_adjustments_col.find({"contest_id": contest_id})]
    rows = scoring.compute_standings(contest, teams, subs, adjustments, as_of=as_of)
    if not include_dq:
        rows = [r for r in rows if not r["disqualified"]]
    await _member_names(rows)
    return rows


async def participant_leaderboard(contest: dict, is_admin: bool = False, now: Optional[datetime] = None) -> dict:
    """The leaderboard as a given viewer may see it right now: admins always
    get live standings (incl. disqualified teams); participants get nothing
    while hidden, and a board frozen at `freeze_at` during the freeze window."""
    now = now or now_utc()
    mode = parse_settings(contest.get("settings")).scoring.mode
    if is_admin:
        view = scoring.leaderboard_view(contest, now)
        rows = await compute_leaderboard(contest["_id"], include_dq=True)
        return {"items": rows, "top5": rows[:5], "hidden": False, "frozen": False,
                "admin_view": {"participant_hidden": view["hidden"], "participant_frozen": view["frozen"]},
                "mode": mode}
    view = scoring.leaderboard_view(contest, now)
    if view["hidden"]:
        return {"items": [], "top5": [], "hidden": True, "frozen": False, "mode": mode}
    rows = await compute_leaderboard(contest["_id"], as_of=view["as_of"])
    return {"items": rows, "top5": rows[:5], "hidden": False, "frozen": view["frozen"],
            "frozen_at": view["as_of"].isoformat() if view["as_of"] else None, "mode": mode}


def _csv_safe(v: Any) -> Any:
    """Neutralise spreadsheet formula injection in user-controlled text."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def _to_csv(header: List[str], rows: List[List[Any]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    for r in rows:
        w.writerow([_csv_safe(c) for c in r])
    return buf.getvalue()


async def export_standings_csv(contest_id: str) -> str:
    contest = await get_contest(contest_id)
    rows = await compute_leaderboard(contest_id, include_dq=True)
    pids = contest["problem_ids"]
    header = ["rank", "team", "members", "solved", "score", "penalty_minutes", "disqualified"] + [f"problem:{p}" for p in pids]
    out = []
    for r in rows:
        per = {p["problem_id"]: p for p in r["per_problem"]}
        out.append([
            r["rank"] if r["rank"] is not None else "", r["team_name"], "; ".join(m["name"] for m in r["members"]),
            r["problems_solved"], r["score"], round(r["penalty_seconds"] / 60, 1), "yes" if r["disqualified"] else "no",
        ] + [f"{per[p]['points']} ({per[p]['attempts']} att)" if p in per else "" for p in pids])
    return _to_csv(header, out)


async def export_submissions_csv(contest_id: str) -> str:
    teams = {t["_id"]: t["name"] for t in await list_teams(contest_id)}
    out = []
    async for s in contest_submissions_col.find({"contest_id": contest_id}).sort("created_at", 1):
        out.append([s["created_at"], teams.get(s["team_id"], "(removed)"), s["user_id"], s["problem_id"], s["language"],
                    s["passed_count"], s["total"], "yes" if s["all_passed"] else "no",
                    s.get("fraction_override", ""), "yes" if s.get("invalidated") else "no"])
    return _to_csv(["time", "team", "user_id", "problem", "language", "passed", "total", "all_passed",
                    "fraction_override", "invalidated"], out)


# ---------------------------------------------------------------------------
# Personal stats (certificate + stats card data source)
# ---------------------------------------------------------------------------
async def get_user_contest_stats(contest_id: str, user_id: str) -> dict:
    contest = await get_contest(contest_id)
    if not contest:
        raise ValueError("Contest not found")

    user_subs = []
    async for d in contest_submissions_col.find({"contest_id": contest_id, "user_id": user_id}).sort("created_at", 1):
        user_subs.append(d)

    user_subs = [s for s in user_subs if not s.get("invalidated")]
    passed_subs = [s for s in user_subs if s["all_passed"]]
    solved_problem_ids = list(dict.fromkeys(s["problem_id"] for s in passed_subs))  # first-solved order, deduped

    # "Strongest topic": the roadmap `step` (e.g. "Arrays & Hashing") that
    # shows up most often among THIS user's own solved contest problems —
    # first-seen wins any count tie, for determinism. "N/A" if nothing solved.
    strongest_topic = "N/A"
    if solved_problem_ids:
        step_counts: Dict[str, int] = {}
        step_first_seen: Dict[str, int] = {}
        for i, pid in enumerate(solved_problem_ids):
            prob = await get_problem_raw(pid)
            step = (prob or {}).get("step", "Uncategorized")
            step_counts[step] = step_counts.get(step, 0) + 1
            step_first_seen.setdefault(step, i)
        strongest_topic = max(step_counts, key=lambda s: (step_counts[s], -step_first_seen[s]))

    team = await get_my_team(contest_id, user_id)
    team_rank, team_name, team_score = None, None, None
    if team:
        team_name = team["name"]
        # The rank a participant is shown follows the same visibility/freeze
        # rules as the public board — a hidden or frozen board never leaks a
        # fresher rank through the stats card or certificate.
        board = await participant_leaderboard(contest)
        for row in board["items"]:
            if row["team_id"] == team["_id"]:
                team_rank, team_score = row["rank"], row["score"]
                break

    return {
        "contest_id": contest_id,
        "contest_name": contest["name"],
        "user_id": user_id,
        "submissions_count": len(user_subs),
        "problems_solved": len(solved_problem_ids),
        "total_contest_problems": len(contest["problem_ids"]),
        "strongest_topic": strongest_topic,
        "team_name": team_name,
        "team_rank": team_rank,
        "team_score": team_score,
        "team_disqualified": bool(team and team.get("disqualified")),
        "first_submission_at": user_subs[0]["created_at"] if user_subs else None,
        "last_submission_at": user_subs[-1]["created_at"] if user_subs else None,
        # Certificates/stats cards are issued to anyone with >=1 contest
        # submission, not just people who passed — "participation", not
        # "success".
        "has_participated": len(user_subs) > 0,
    }


def prize_for_rank(contest: dict, rank: Optional[int]) -> Optional[dict]:
    if not rank:
        return None
    for tier in parse_settings(contest.get("settings")).prizes:
        if tier.from_rank <= rank <= tier.to_rank:
            return tier.model_dump()
    return None


def certificate_award(contest: dict, stats: dict) -> dict:
    """Decide what (if any) certificate this participant gets under the
    contest's certificate options. kind: "winner" | "participation" | None."""
    cert = parse_settings(contest.get("settings")).certificate
    if not cert.enabled:
        return {"eligible": False, "kind": None, "reason": "Certificates are not issued for this contest"}
    if stats.get("team_disqualified"):
        return {"eligible": False, "kind": None, "reason": "Disqualified participants are not issued certificates"}
    if cert.issue_after == "ended" and contest_status(contest) != "ended":
        return {"eligible": False, "kind": None, "reason": "Certificates are issued once the contest has ended"}
    rank = stats.get("team_rank")
    if cert.winner_top_n and rank and rank <= cert.winner_top_n and stats.get("has_participated") \
            and contest_status(contest) == "ended":
        return {"eligible": True, "kind": "winner", "rank": rank, "prize": prize_for_rank(contest, rank)}
    needed = max(1, cert.participation_min_solved) if cert.participation_min_solved else 0
    if needed and stats.get("problems_solved", 0) < needed:
        return {"eligible": False, "kind": None,
                "reason": f"Solve at least {needed} problem(s) to earn a participation certificate"}
    if not stats.get("has_participated"):
        return {"eligible": False, "kind": None,
                "reason": "You haven't made a submission in this contest yet — certificates are issued to participants only"}
    return {"eligible": True, "kind": "participation"}


# ---------------------------------------------------------------------------
# Certificate PDF — a real, text-based single-page PDF (fpdf2), not a
# rasterized image. That keeps the name/contest/date as genuine PDF text
# (verifiable with pypdf's extract_text()), not pixels pretending to be one.
# ---------------------------------------------------------------------------
def generate_certificate_pdf(contest: dict, user_name: str, award: Optional[dict] = None) -> bytes:
    start_dt = _parse_iso(contest["start_at"])
    end_dt = _parse_iso(contest["end_at"])
    issued_dt = now_utc()

    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_auto_page_break(False)
    pdf.add_page()
    W, H = pdf.w, pdf.h
    margin = pdf.l_margin

    # Decorative double border.
    pdf.set_draw_color(30, 41, 59)
    pdf.set_line_width(1.2)
    pdf.rect(8, 8, W - 16, H - 16)
    pdf.set_line_width(0.4)
    pdf.rect(12, 12, W - 24, H - 24)

    def _centered(y: float, text: str, size: int, bold: bool = False, color=(15, 23, 42)):
        pdf.set_xy(margin, y)
        pdf.set_font("Helvetica", "B" if bold else "", size)
        pdf.set_text_color(*color)
        pdf.multi_cell(W - 2 * margin, size * 0.5, text, align="C")

    winner = bool(award and award.get("kind") == "winner")
    _centered(30, "Certificate of Achievement" if winner else "Certificate of Participation", 30, bold=True)
    _centered(58, "This certifies that", 14, color=(90, 90, 90))
    _centered(70, user_name, 26, bold=True)
    if winner:
        tier = (award.get("prize") or {}).get("title")
        place = f"placed #{award['rank']}" + (f" ({tier})" if tier else "")
        _centered(92, f'{place} in "{contest["name"]}"', 14, color=(90, 90, 90))
    else:
        _centered(92, f'successfully participated in "{contest["name"]}"', 14, color=(90, 90, 90))
    _centered(
        104,
        f"held from {start_dt.strftime('%B %d, %Y')} to {end_dt.strftime('%B %d, %Y')}",
        12, color=(120, 120, 120),
    )
    _centered(130, f"Issued on {issued_dt.strftime('%B %d, %Y')}", 12, color=(120, 120, 120))

    return bytes(pdf.output())


# ---------------------------------------------------------------------------
# Stats card PNG — a deterministic, templated image (Pillow): real numbers
# drawn onto a plain background, NOT an AI-generated image. Correctness of
# the numbers matters far more than visual flair here.
# ---------------------------------------------------------------------------
_FONT_CANDIDATES_REGULAR = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
_FONT_CANDIDATES_BOLD = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def _load_font(size: int, bold: bool = False):
    for path in (_FONT_CANDIDATES_BOLD if bold else _FONT_CANDIDATES_REGULAR):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    # No system TTF found (e.g. a minimal Linux CI box) — Pillow's built-in
    # bitmap font still renders real text at a chosen size, just less pretty.
    return ImageFont.load_default(size=size)


def generate_stats_card_png(contest: dict, user_name: str, stats: dict) -> bytes:
    W, H = 1200, 630
    bg = (15, 23, 42)
    accent = (99, 102, 241)
    muted = (148, 163, 184)

    img = Image.new("RGB", (W, H), bg)
    draw = ImageDraw.Draw(img)

    title_font = _load_font(38, bold=True)
    subtitle_font = _load_font(22)
    name_font = _load_font(50, bold=True)
    label_font = _load_font(20)
    value_font = _load_font(42, bold=True)
    footer_font = _load_font(18)

    draw.rectangle([0, 0, W, 10], fill=accent)
    draw.text((60, 46), "Hackathon Contest Stats", font=title_font, fill=(226, 232, 240))
    draw.text((60, 100), (contest.get("name") or "")[:70], font=subtitle_font, fill=muted)
    draw.text((60, 160), user_name[:40], font=name_font, fill=(255, 255, 255))

    rank_display = f"#{stats['team_rank']}" if stats.get("team_rank") else "Unranked"
    topic_value_font = _load_font(30, bold=True) if len(stats.get("strongest_topic") or "") > 10 else value_font
    stat_blocks = [
        ("PROBLEMS SOLVED", f"{stats['problems_solved']} / {stats['total_contest_problems']}", value_font),
        ("TEAM RANK", rank_display, value_font),
        ("STRONGEST TOPIC", (stats.get("strongest_topic") or "N/A")[:18], topic_value_font),
    ]
    x = 60
    box_w, box_h = 350, 150
    for label, value, font in stat_blocks:
        draw.rectangle([x, 270, x + box_w, 270 + box_h], outline=accent, width=3)
        draw.text((x + 20, 292), label, font=label_font, fill=muted)
        draw.text((x + 20, 335), str(value), font=font, fill=(255, 255, 255))
        x += box_w + 30

    draw.text((60, H - 60), f"Team: {stats.get('team_name') or '-'}", font=footer_font, fill=muted)
    draw.text((W - 300, H - 60), f"Contest: {(contest.get('name') or '')[:30]}", font=footer_font, fill=muted)

    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
