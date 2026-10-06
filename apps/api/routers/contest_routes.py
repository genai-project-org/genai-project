"""Contest Mode routes — admin contest CRUD, team signup, contest submissions
(FREE — see the comment on `submit_contest_solution` below), leaderboard,
certificate (PDF) and stats-card (PNG) downloads.

Grading itself is 100% reused from the Practice Engine: `run_submission()` in
`services/practice_service.py` (Piston execution against the problem's real
test cases) is called exactly as `/practice/.../submit` calls it. This module
only adds the contest-shaped bookkeeping around that call.
"""
import logging
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from auth import get_current_user, require_admin
from db import users_col
from models import User
from services.practice_service import get_problem_raw, run_submission, PistonUnavailableError
from services.contest_service import (
    create_contest,
    get_contest,
    list_contests,
    update_contest,
    stop_contest,
    contest_status,
    get_contest_public,
    create_team,
    get_my_team,
    list_open_teams,
    join_open_team,
    record_contest_submission,
    compute_leaderboard,
    get_user_contest_stats,
    generate_certificate_pdf,
    generate_stats_card_png,
    MAX_TEAM_SIZE,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/contest", tags=["contest"])


class CreateContestRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    # ISO-8601 datetimes, e.g. "2026-09-26T18:30:00+00:00". Naive strings
    # (no offset) are treated as UTC — see contest_service._parse_iso.
    start_at: str
    end_at: str
    # Omit to use the default 4-problem set (see DEFAULT_CONTEST_PROBLEM_IDS
    # in contest_service.py) drawn from the existing practice_problems bank.
    problem_ids: Optional[List[str]] = None


class UpdateContestRequest(BaseModel):
    name: Optional[str] = None
    start_at: Optional[str] = None
    end_at: Optional[str] = None
    problem_ids: Optional[List[str]] = None


class CreateTeamRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    # Teammates' emails, NOT including the caller — the caller is added
    # automatically as a member. Leave empty to register solo (a team of 1
    # is valid, not an error) — see MIN_TEAM_SIZE in contest_service.py.
    member_emails: List[str] = Field(default_factory=list)
    # If true and the team isn't already full, it's listed via
    # GET /{contest_id}/teams/open so a teamless user can find and join it
    # without knowing anyone's email in advance.
    open_to_join: bool = False


class ContestSubmitRequest(BaseModel):
    code: str = Field(min_length=1, max_length=20000)
    language: Literal["python", "javascript", "cpp", "java"] = "python"


def _contest_out(c: dict) -> dict:
    return {
        "id": c["_id"], "name": c["name"],
        "start_at": c["start_at"], "end_at": c["end_at"],
        "problem_ids": c["problem_ids"],
        "status": contest_status(c),
        "ended_early": bool(c.get("ended_early")),
        "landing_page": c.get("landing_page"),
    }


def _contest_summary(c: dict) -> dict:
    return {
        "id": c["_id"], "name": c["name"],
        "start_at": c["start_at"], "end_at": c["end_at"],
        "status": contest_status(c),
        "problem_count": len(c["problem_ids"]),
    }


def _team_out(t: dict) -> dict:
    return {
        "id": t["_id"], "contest_id": t["contest_id"], "name": t["name"],
        "member_user_ids": t["member_user_ids"], "created_by": t["created_by"],
        "is_open": bool(t.get("is_open")),
    }


def _open_team_out(t: dict) -> dict:
    """Deliberately thin — a browsing, not-yet-a-member user only ever sees
    the name, current headcount and remaining capacity, never member
    identities (those stay behind the same-team-only `_team_out` shape)."""
    member_count = len(t["member_user_ids"])
    return {
        "id": t["_id"], "name": t["name"],
        "member_count": member_count,
        "spots_left": MAX_TEAM_SIZE - member_count,
    }


# ---------------------------------------------------------------------------
# Admin: contest CRUD
# ---------------------------------------------------------------------------
@router.post("/")
async def create_new_contest(req: CreateContestRequest, admin: User = Depends(require_admin)):
    try:
        contest = await create_contest(req.name, req.start_at, req.end_at, req.problem_ids, created_by=admin.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _contest_out(contest)


@router.patch("/{contest_id}")
async def patch_contest(contest_id: str, req: UpdateContestRequest, admin: User = Depends(require_admin)):
    if not await get_contest(contest_id):
        raise HTTPException(404, "Contest not found")
    try:
        contest = await update_contest(contest_id, req.model_dump(exclude_unset=True))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _contest_out(contest)


@router.post("/{contest_id}/stop")
async def stop_contest_now(contest_id: str, admin: User = Depends(require_admin)):
    """Admin "end now" action — irreversibly ends a live (or upcoming)
    contest immediately, regardless of its scheduled `end_at`. A submission
    attempted right after this call is rejected exactly like one made after
    the original deadline (see contest_status()'s `ended_early` check)."""
    if not await get_contest(contest_id):
        raise HTTPException(404, "Contest not found")
    contest = await stop_contest(contest_id)
    return _contest_out(contest)


# ---------------------------------------------------------------------------
# Participants: browse contests, view detail
# ---------------------------------------------------------------------------
@router.get("/")
async def get_contests(user: User = Depends(get_current_user)):
    items = await list_contests()
    return {"items": [_contest_summary(c) for c in items]}


@router.get("/{contest_id}")
async def get_contest_detail(contest_id: str, user: User = Depends(get_current_user)):
    detail = await get_contest_public(contest_id, user_id=user.id)
    if not detail:
        raise HTTPException(404, "Contest not found")
    return detail


# ---------------------------------------------------------------------------
# Teams
# ---------------------------------------------------------------------------
@router.post("/{contest_id}/teams")
async def create_contest_team(contest_id: str, req: CreateTeamRequest, user: User = Depends(get_current_user)):
    member_ids = []
    for email in req.member_emails:
        doc = await users_col.find_one({"email": email.strip().lower()})
        if not doc:
            raise HTTPException(400, f"No user found with email `{email}`")
        member_ids.append(str(doc["_id"]))

    try:
        team = await create_team(contest_id, req.name, member_ids, created_by=user.id, open_to_join=req.open_to_join)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _team_out(team)


@router.get("/{contest_id}/team/me")
async def get_my_contest_team(contest_id: str, user: User = Depends(get_current_user)):
    if not await get_contest(contest_id):
        raise HTTPException(404, "Contest not found")
    team = await get_my_team(contest_id, user.id)
    return {"team": _team_out(team) if team else None}


@router.get("/{contest_id}/teams/open")
async def get_open_teams(contest_id: str, user: User = Depends(get_current_user)):
    """The "join an open team" browse list — for a user with no pre-formed
    squad, this is how they find teammates at all, without knowing anyone's
    email in advance."""
    if not await get_contest(contest_id):
        raise HTTPException(404, "Contest not found")
    teams = await list_open_teams(contest_id)
    return {"items": [_open_team_out(t) for t in teams]}


@router.post("/{contest_id}/teams/{team_id}/join")
async def join_contest_team(contest_id: str, team_id: str, user: User = Depends(get_current_user)):
    try:
        team = await join_open_team(contest_id, team_id, user.id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return _team_out(team)


# ---------------------------------------------------------------------------
# Contest submission — the one deliberately-free lane in the whole app.
# ---------------------------------------------------------------------------
@router.post("/{contest_id}/problems/{problem_id}/submit")
async def submit_contest_solution(
    contest_id: str, problem_id: str, req: ContestSubmitRequest, user: User = Depends(get_current_user),
):
    contest = await get_contest(contest_id)
    if not contest:
        raise HTTPException(404, "Contest not found")

    # Real, enforced time window — not just a UI countdown. A submission
    # outside [start_at, end_at] is rejected outright, never silently accepted.
    status_now = contest_status(contest)
    if status_now == "upcoming":
        raise HTTPException(403, f"This contest hasn't started yet — it opens at {contest['start_at']}")
    if status_now == "ended":
        raise HTTPException(403, f"This contest has ended — submissions closed at {contest['end_at']}")

    if problem_id not in contest["problem_ids"]:
        raise HTTPException(400, "This problem is not part of this contest")

    team = await get_my_team(contest_id, user.id)
    if not team:
        raise HTTPException(400, "Join or create a team for this contest before submitting")

    problem = await get_problem_raw(problem_id)
    if not problem:
        raise HTTPException(404, "Problem not found")
    if req.language not in (problem.get("starter_code") or {}):
        raise HTTPException(400, f"Problem does not support language `{req.language}`")

    # AGENT/REVIEWER NOTE: contest submissions are FREE by deliberate business
    # decision — the hackathon is a free-entry event. Do NOT add a
    # precheck()/spend() call here to "fix" this; regular (non-contest)
    # /practice/.../submit still charges normally and is completely
    # unaffected. There is intentionally no pricing_engine entry for contest
    # submissions (see the comment in DEFAULT_PRICING, services/pricing_engine.py).
    try:
        run_result = await run_submission(problem, req.code, req.language)
    except PistonUnavailableError as e:
        raise HTTPException(502, f"Code execution service unavailable: {e}")
    except ValueError as e:
        raise HTTPException(400, str(e))

    submission = await record_contest_submission(
        contest_id, team["_id"], user.id, problem_id, req.language, req.code, run_result,
    )

    return {
        "submission_id": submission["_id"],
        "results": run_result["results"],
        "passed_count": run_result["passed_count"],
        "total": run_result["total"],
        "all_passed": run_result["all_passed"],
        "credits_used": 0,
        "free": True,
    }


# ---------------------------------------------------------------------------
# Leaderboard — public within the contest to every authenticated user, full
# list always included (never gated behind anything paid — only optional
# "deeper" stuff is ever gated elsewhere in this app, never placement).
# ---------------------------------------------------------------------------
@router.get("/{contest_id}/leaderboard")
async def get_leaderboard(contest_id: str, user: User = Depends(get_current_user)):
    if not await get_contest(contest_id):
        raise HTTPException(404, "Contest not found")
    rows = await compute_leaderboard(contest_id)
    return {"items": rows, "top5": rows[:5]}


@router.get("/{contest_id}/my-stats")
async def get_my_stats(contest_id: str, user: User = Depends(get_current_user)):
    if not await get_contest(contest_id):
        raise HTTPException(404, "Contest not found")
    return await get_user_contest_stats(contest_id, user.id)


# ---------------------------------------------------------------------------
# Certificate (PDF) + stats card (PNG) — issued to anyone who has made at
# least one contest submission, not only the top finishers.
# ---------------------------------------------------------------------------
@router.get("/{contest_id}/certificate")
async def download_certificate(contest_id: str, user: User = Depends(get_current_user)):
    contest = await get_contest(contest_id)
    if not contest:
        raise HTTPException(404, "Contest not found")
    stats = await get_user_contest_stats(contest_id, user.id)
    if not stats["has_participated"]:
        raise HTTPException(404, "You haven't made a submission in this contest yet — certificates are issued to participants only")

    pdf_bytes = generate_certificate_pdf(contest, user.name)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="certificate-{contest_id}.pdf"'},
    )


@router.get("/{contest_id}/stats-card")
async def download_stats_card(contest_id: str, user: User = Depends(get_current_user)):
    contest = await get_contest(contest_id)
    if not contest:
        raise HTTPException(404, "Contest not found")
    stats = await get_user_contest_stats(contest_id, user.id)
    if not stats["has_participated"]:
        raise HTTPException(404, "You haven't made a submission in this contest yet")

    png_bytes = generate_stats_card_png(contest, user.name, stats)
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="stats-card-{contest_id}.png"'},
    )
