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
import json
import logging
import uuid
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fpdf import FPDF
from PIL import Image, ImageDraw, ImageFont

from db import db, now_iso, now_utc, users_col
from services.practice_service import practice_problems_col, get_problem_public, get_problem_raw
from services.llm_client import LlmChat, UserMessage
from services.builder_service import _extract_json

logger = logging.getLogger(__name__)

contests_col = db["contests"]
contest_teams_col = db["contest_teams"]
contest_submissions_col = db["contest_submissions"]

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


async def generate_landing_page(name: str, problems: List[dict], start_at: str, end_at: str) -> dict:
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


def _parse_iso(s: str) -> datetime:
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


async def ensure_indexes():
    await contests_col.create_index([("start_at", 1)])
    await contest_teams_col.create_index([("contest_id", 1)])
    await contest_submissions_col.create_index([("contest_id", 1), ("team_id", 1)])
    await contest_submissions_col.create_index([("contest_id", 1), ("user_id", 1), ("problem_id", 1)])


# ---------------------------------------------------------------------------
# Contest CRUD
# ---------------------------------------------------------------------------
def contest_status(contest: dict, now: Optional[datetime] = None) -> str:
    """"upcoming" | "live" | "ended" — the real, enforced source of truth for
    whether a submission should be accepted (see routers/contest_routes.py).

    An admin-triggered `stop_contest()` sets `ended_early: True`, which this
    checks FIRST and unconditionally returns "ended" for — regardless of what
    `start_at`/`end_at` say — so a manual stop takes effect immediately and
    can never be raced by comparing against a not-yet-passed timestamp."""
    if contest.get("ended_early"):
        return "ended"
    now = now or now_utc()
    start = _parse_iso(contest["start_at"])
    end = _parse_iso(contest["end_at"])
    if now < start:
        return "upcoming"
    if now > end:
        return "ended"
    return "live"


async def stop_contest(contest_id: str) -> Optional[dict]:
    """Admin "end now" action — immediately ends a contest regardless of its
    scheduled `end_at`. Irreversible from the participant's point of view:
    once stopped, contest_status() always reports "ended" for this contest
    (see the flag check above), so a submission attempted right after this
    call is rejected exactly like one made after the original deadline."""
    stamp = now_iso()
    await contests_col.update_one(
        {"_id": contest_id},
        {"$set": {"ended_early": True, "end_at": stamp, "updated_at": stamp}},
    )
    return await get_contest(contest_id)


async def create_contest(
    name: str, start_at: str, end_at: str, problem_ids: Optional[List[str]], created_by: str,
) -> dict:
    start_dt = _parse_iso(start_at)
    end_dt = _parse_iso(end_at)
    if end_dt <= start_dt:
        raise ValueError("end_at must be after start_at")

    ids = list(problem_ids) if problem_ids else list(DEFAULT_CONTEST_PROBLEM_IDS)
    if not ids:
        raise ValueError("A contest needs at least one problem")
    # Validate every id refers to a real, already-seeded practice problem —
    # never silently accept a typo'd id that would 404 for every contestant
    # the moment they open the contest.
    found_docs = {}
    async for d in practice_problems_col.find({"_id": {"$in": ids}}, {"_id": 1, "title": 1, "difficulty": 1}):
        found_docs[d["_id"]] = d
    missing = [i for i in ids if i not in found_docs]
    if missing:
        raise ValueError(f"Unknown problem id(s): {', '.join(missing)}")

    landing_page = await generate_landing_page(
        name, [found_docs[pid] for pid in ids], start_dt.isoformat(), end_dt.isoformat(),
    )

    doc = {
        "_id": uuid.uuid4().hex,
        "name": name,
        "problem_ids": ids,
        "start_at": start_dt.isoformat(),
        "end_at": end_dt.isoformat(),
        "created_by": created_by,
        "landing_page": landing_page,
        "ended_early": False,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await contests_col.insert_one(doc)
    return doc


async def get_contest(contest_id: str) -> Optional[dict]:
    return await contests_col.find_one({"_id": contest_id})


async def list_contests() -> List[dict]:
    items = []
    async for d in contests_col.find({}).sort("start_at", -1):
        items.append(d)
    return items


async def update_contest(contest_id: str, updates: Dict[str, Any]) -> Optional[dict]:
    allowed = {"name", "start_at", "end_at", "problem_ids"}
    clean = {k: v for k, v in updates.items() if k in allowed and v is not None}
    if "start_at" in clean:
        clean["start_at"] = _parse_iso(clean["start_at"]).isoformat()
    if "end_at" in clean:
        clean["end_at"] = _parse_iso(clean["end_at"]).isoformat()
    if "problem_ids" in clean:
        found = {d["_id"] async for d in practice_problems_col.find({"_id": {"$in": clean["problem_ids"]}}, {"_id": 1})}
        missing = [i for i in clean["problem_ids"] if i not in found]
        if missing:
            raise ValueError(f"Unknown problem id(s): {', '.join(missing)}")
    if not clean:
        return await get_contest(contest_id)
    clean["updated_at"] = now_iso()
    await contests_col.update_one({"_id": contest_id}, {"$set": clean})
    return await get_contest(contest_id)


async def get_contest_public(contest_id: str, user_id: Optional[str] = None) -> Optional[dict]:
    """Participant-facing contest detail: the problem set (public shape, same
    as /practice/problems/{id} summaries) plus the caller's own team, if any.
    Never includes another user's team info — only the caller's."""
    contest = await get_contest(contest_id)
    if not contest:
        return None
    problems = []
    for pid in contest["problem_ids"]:
        p = await get_problem_public(pid)
        if p:
            problems.append({"id": p["id"], "title": p["title"], "difficulty": p["difficulty"], "tags": p["tags"]})
    out = {
        "id": contest["_id"],
        "name": contest["name"],
        "start_at": contest["start_at"],
        "end_at": contest["end_at"],
        "status": contest_status(contest),
        "ended_early": bool(contest.get("ended_early")),
        "problems": problems,
        # Structured, pre-generated (never regenerated per view) copy for the
        # not-yet-registered landing page — see generate_landing_page() above.
        "landing_page": contest.get("landing_page"),
    }
    if user_id:
        team = await get_my_team(contest["_id"], user_id)
        out["my_team"] = _team_public(team) if team else None
    return out


def _team_public(t: dict) -> dict:
    return {
        "id": t["_id"], "contest_id": t["contest_id"], "name": t["name"],
        "member_user_ids": t["member_user_ids"], "created_by": t["created_by"],
        "is_open": bool(t.get("is_open")),
        "created_at": t["created_at"],
    }


# ---------------------------------------------------------------------------
# Teams — 1-3 members (solo participation is allowed), one team per contest
# per user. Three distinct ways to end up on a team, all landing here or in
# join_open_team() below:
#   1. Create a team and invite named teammates by email (member_user_ids).
#   2. Register solo (member_user_ids=[]) — a team of 1 is valid, not an error.
#      Optionally mark it `open_to_join` so others can find and join it.
#   3. Browse list_open_teams() and join_open_team() into an existing team
#      someone else created, without knowing anyone's email in advance.
# ---------------------------------------------------------------------------
async def get_my_team(contest_id: str, user_id: str) -> Optional[dict]:
    return await contest_teams_col.find_one({"contest_id": contest_id, "member_user_ids": user_id})


async def create_team(
    contest_id: str, name: str, member_user_ids: List[str], created_by: str, open_to_join: bool = False,
) -> dict:
    contest = await get_contest(contest_id)
    if not contest:
        raise ValueError("Contest not found")
    if contest_status(contest) == "ended":
        raise ValueError("This contest has already ended — no new teams can be formed")

    members = list(dict.fromkeys(member_user_ids))  # de-dup, preserve order
    if created_by not in members:
        members.insert(0, created_by)
    if not (MIN_TEAM_SIZE <= len(members) <= MAX_TEAM_SIZE):
        raise ValueError(f"A team must have {MIN_TEAM_SIZE}-{MAX_TEAM_SIZE} members (got {len(members)})")

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
        "is_open": bool(open_to_join) and len(members) < MAX_TEAM_SIZE,
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
    items = []
    async for d in contest_teams_col.find({"contest_id": contest_id, "is_open": True}):
        if len(d["member_user_ids"]) < MAX_TEAM_SIZE:
            items.append(d)
    return items


async def join_open_team(contest_id: str, team_id: str, user_id: str) -> dict:
    """A solo (or otherwise teamless) user joins an existing open team
    directly — no email/invite needed."""
    contest = await get_contest(contest_id)
    if not contest:
        raise ValueError("Contest not found")
    if contest_status(contest) == "ended":
        raise ValueError("This contest has already ended — no new teams can be joined")

    if await get_my_team(contest_id, user_id):
        raise ValueError("You are already on a team for this contest")

    team = await contest_teams_col.find_one({"_id": team_id, "contest_id": contest_id})
    if not team:
        raise ValueError("Team not found")
    if not team.get("is_open"):
        raise ValueError("This team is not open to new members")
    if len(team["member_user_ids"]) >= MAX_TEAM_SIZE:
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
    if len(updated["member_user_ids"]) > MAX_TEAM_SIZE:
        # Lost a race against another joiner who filled the last slot first —
        # roll back and surface a clear, actionable error.
        await contest_teams_col.update_one({"_id": team_id}, {"$pull": {"member_user_ids": user_id}})
        raise ValueError("This team just filled up — pick another open team")

    # A team that just reached capacity stops being listed as open.
    if len(updated["member_user_ids"]) >= MAX_TEAM_SIZE:
        await contest_teams_col.update_one({"_id": team_id}, {"$set": {"is_open": False}})
        updated["is_open"] = False
    return updated


# ---------------------------------------------------------------------------
# Contest submissions — separate ledger from practice_submissions (see module
# docstring). NEVER charges credits; the caller (routers/contest_routes.py)
# must not call precheck()/spend() for this path.
# ---------------------------------------------------------------------------
async def record_contest_submission(
    contest_id: str, team_id: str, user_id: str, problem_id: str,
    language: str, code: str, run_result: Dict[str, Any],
) -> dict:
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
        "created_at": now_iso(),
    }
    ins = await contest_submissions_col.insert_one(doc)
    doc["_id"] = str(ins.inserted_id)
    return doc


# ---------------------------------------------------------------------------
# Leaderboard
# ---------------------------------------------------------------------------
async def compute_leaderboard(contest_id: str) -> List[dict]:
    contest = await get_contest(contest_id)
    if not contest:
        return []
    start_dt = _parse_iso(contest["start_at"])
    teams = await list_teams(contest_id)

    # Earliest passing submission per (team, problem), across ALL members —
    # the team is credited with a problem the moment ANY member first solves it.
    best_by_team_problem: Dict[tuple, datetime] = {}
    async for s in contest_submissions_col.find({"contest_id": contest_id, "all_passed": True}):
        key = (s["team_id"], s["problem_id"])
        t = _parse_iso(s["created_at"])
        if key not in best_by_team_problem or t < best_by_team_problem[key]:
            best_by_team_problem[key] = t

    rows = []
    for team in teams:
        solved_times = [t for (tid, pid), t in best_by_team_problem.items() if tid == team["_id"]]
        problems_solved = len(solved_times)
        total_time_seconds = sum(max(0.0, (t - start_dt).total_seconds()) for t in solved_times)
        rows.append({
            "team_id": team["_id"],
            "team_name": team["name"],
            "member_user_ids": team["member_user_ids"],
            "problems_solved": problems_solved,
            "total_time_seconds": round(total_time_seconds),
            "team_created_at": team["created_at"],
        })

    # Rank: most problems solved first; ties broken by LOWER total
    # time-to-solve (ICPC-style — the team that finished its solved set
    # fastest ranks higher); a final tie-break on team creation time keeps
    # ordering fully deterministic on an exact tie.
    rows.sort(key=lambda r: (-r["problems_solved"], r["total_time_seconds"], r["team_created_at"]))
    for i, r in enumerate(rows):
        r["rank"] = i + 1
        del r["team_created_at"]  # internal tie-break key only, not part of the public shape

    # Batch-resolve member display names for the frontend.
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

    return rows


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
    team_rank, team_name = None, None
    if team:
        team_name = team["name"]
        leaderboard = await compute_leaderboard(contest_id)
        for row in leaderboard:
            if row["team_id"] == team["_id"]:
                team_rank = row["rank"]
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
        "first_submission_at": user_subs[0]["created_at"] if user_subs else None,
        "last_submission_at": user_subs[-1]["created_at"] if user_subs else None,
        # Certificates/stats cards are issued to anyone with >=1 contest
        # submission, not just people who passed — "participation", not
        # "success".
        "has_participated": len(user_subs) > 0,
    }


# ---------------------------------------------------------------------------
# Certificate PDF — a real, text-based single-page PDF (fpdf2), not a
# rasterized image. That keeps the name/contest/date as genuine PDF text
# (verifiable with pypdf's extract_text()), not pixels pretending to be one.
# ---------------------------------------------------------------------------
def generate_certificate_pdf(contest: dict, user_name: str) -> bytes:
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

    _centered(30, "Certificate of Participation", 30, bold=True)
    _centered(58, "This certifies that", 14, color=(90, 90, 90))
    _centered(70, user_name, 26, bold=True)
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
