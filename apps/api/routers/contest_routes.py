"""Contest Mode routes — admin contest CRUD + lifecycle + scoring controls,
team signup, contest submissions (FREE — see the comment on
`submit_contest_solution` below), leaderboard, announcements, clarifications,
certificate (PDF) and stats-card (PNG) downloads.

Authorization model: ANY signed-in user may browse published contests,
register and submit. EVERY mutating endpoint that manages a contest depends on
`require_admin`, which re-checks the role in the database on each request.

Grading itself is 100% reused from the Practice Engine: `run_submission()` in
`services/practice_service.py` (Piston execution against the problem's real
test cases) is called exactly as `/practice/.../submit` calls it. This module
only adds the contest-shaped bookkeeping around that call.
"""
import logging
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, ValidationError

from auth import get_current_user, require_admin
from db import now_utc, users_col
from models import User
from services.practice_service import get_problem_raw, run_submission, PistonUnavailableError
from services import contest_service as cs
from services.contest_scoring import is_released, release_time
from services.contest_settings import ProblemConfig, TEMPLATES, parse_problem_config, parse_settings
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
    get_user_contest_stats,
    generate_certificate_pdf,
    generate_stats_card_png,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/contest", tags=["contest"])


def _bad(e: Exception) -> HTTPException:
    """400 with a readable message (pydantic errors are flattened to
    `field.path: message`)."""
    if isinstance(e, ValidationError):
        msg = "; ".join(f"{'.'.join(str(p) for p in x['loc'])}: {x['msg']}" for x in e.errors())
        return HTTPException(400, msg)
    return HTTPException(400, str(e))


class CreateContestRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    # ISO-8601 datetimes, e.g. "2026-09-26T18:30:00+00:00". Naive strings
    # (no offset) are treated as UTC — see contest_scoring.parse_iso.
    start_at: str
    end_at: str
    # Omit to use the default 4-problem set (see DEFAULT_CONTEST_PROBLEM_IDS
    # in contest_service.py) drawn from the existing practice_problems bank.
    problem_ids: Optional[List[str]] = None
    # Validated by services.contest_settings.ContestSettings — omit for defaults.
    settings: Optional[Dict[str, Any]] = None
    problem_configs: Optional[Dict[str, Dict[str, Any]]] = None
    state: Literal["draft", "published"] = "published"
    # Set false to skip the LLM copywriting call and use the deterministic
    # landing copy (instant creation).
    ai_landing: bool = True


class UpdateContestRequest(BaseModel):
    name: Optional[str] = None
    start_at: Optional[str] = None
    end_at: Optional[str] = None
    problem_ids: Optional[List[str]] = None
    settings: Optional[Dict[str, Any]] = None  # partial: deep-merged into the stored settings
    problem_configs: Optional[Dict[str, Dict[str, Any]]] = None
    state: Optional[Literal["draft", "published"]] = None


class ProblemEntry(ProblemConfig):
    problem_id: str


class SetProblemsRequest(BaseModel):
    problems: List[ProblemEntry] = Field(min_length=1, max_length=100)


class FromTemplateRequest(BaseModel):
    template_id: str
    name: str = Field(min_length=1, max_length=120)
    start_at: Optional[str] = None


class ExtendRequest(BaseModel):
    minutes: int = Field(ge=1, le=60 * 24 * 14)


class ArchiveRequest(BaseModel):
    archived: bool = True


class DuplicateRequest(BaseModel):
    name: Optional[str] = Field(default=None, max_length=120)


class AdjustmentRequest(BaseModel):
    team_id: str
    kind: Literal["grace", "override"] = "grace"
    points: float = Field(default=0, ge=-1_000_000, le=1_000_000)
    penalty_minutes: float = Field(default=0, ge=-100_000, le=100_000)
    reason: str = Field(min_length=3, max_length=500)


class ReasonRequest(BaseModel):
    reason: str = Field(default="", max_length=500)


class SubmissionOverrideRequest(BaseModel):
    fraction: Optional[float] = None
    invalidated: Optional[bool] = None
    reason: str = Field(min_length=3, max_length=500)


class RejudgeRequest(BaseModel):
    submission_id: Optional[str] = None
    problem_id: Optional[str] = None


class AddParticipantRequest(BaseModel):
    email: str = Field(max_length=254)
    team_id: Optional[str] = None
    team_name: Optional[str] = Field(default=None, max_length=80)


class InviteRequest(BaseModel):
    emails: List[str] = Field(min_length=1, max_length=500)


class AnnouncementRequest(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    pinned: bool = False


class QuestionRequest(BaseModel):
    question: str = Field(min_length=1, max_length=1000)
    problem_id: Optional[str] = None


class AnswerRequest(BaseModel):
    answer: str = Field(min_length=1, max_length=2000)
    public: bool = False


class RevealRequest(BaseModel):
    revealed: bool = True


class CreateTeamRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    # Teammates' emails, NOT including the caller — the caller is added
    # automatically as a member. Leave empty to register solo (a team of 1
    # is valid where the contest's mode allows it).
    member_emails: List[str] = Field(default_factory=list)
    # If true and the team isn't already full, it's listed via
    # GET /{contest_id}/teams/open so a teamless user can find and join it
    # without knowing anyone's email in advance.
    open_to_join: bool = False
    # Only needed for code-protected contests.
    access_code: Optional[str] = Field(default=None, max_length=64)


class JoinTeamRequest(BaseModel):
    access_code: Optional[str] = Field(default=None, max_length=64)


class ContestSubmitRequest(BaseModel):
    code: str = Field(min_length=1, max_length=20000)
    language: Literal["python", "javascript", "cpp", "java"] = "python"


def _contest_out(c: dict) -> dict:
    return {
        "id": c["_id"], "name": c["name"],
        "start_at": c["start_at"], "end_at": c["end_at"],
        "problem_ids": c["problem_ids"],
        "status": contest_status(c),
        "state": c.get("state", "published"),
        "archived": bool(c.get("archived")),
        "paused": bool(c.get("paused_at")),
        "ended_early": bool(c.get("ended_early")),
        "landing_page": c.get("landing_page"),
    }


def _contest_summary(c: dict) -> dict:
    return {
        "id": c["_id"], "name": c["name"],
        "start_at": c["start_at"], "end_at": c["end_at"],
        "status": contest_status(c),
        "state": c.get("state", "published"),
        "archived": bool(c.get("archived")),
        "problem_count": len(c["problem_ids"]),
    }


def _team_out(t: dict) -> dict:
    return {
        "id": t["_id"], "contest_id": t["contest_id"], "name": t["name"],
        "member_user_ids": t["member_user_ids"], "created_by": t["created_by"],
        "is_open": bool(t.get("is_open")),
        "disqualified": bool(t.get("disqualified")),
    }


def _open_team_out(t: dict, max_size: int) -> dict:
    """Deliberately thin — a browsing, not-yet-a-member user only ever sees
    the name, current headcount and remaining capacity, never member
    identities (those stay behind the same-team-only `_team_out` shape)."""
    member_count = len(t["member_user_ids"])
    return {
        "id": t["_id"], "name": t["name"],
        "member_count": member_count,
        "spots_left": max_size - member_count,
        "max_size": max_size,
    }


async def _get_or_404(contest_id: str) -> dict:
    c = await get_contest(contest_id)
    if not c:
        raise HTTPException(404, "Contest not found")
    return c


async def _visible_or_404(contest_id: str, user: User) -> dict:
    """Drafts don't exist as far as non-admins are concerned."""
    c = await _get_or_404(contest_id)
    if c.get("state") == "draft" and user.role != "admin":
        raise HTTPException(404, "Contest not found")
    return c


# ---------------------------------------------------------------------------
# Admin: contest CRUD + templates
# ---------------------------------------------------------------------------
@router.get("/templates")
async def get_templates(admin: User = Depends(require_admin)):
    return {"items": [{k: t[k] for k in ("id", "name", "description", "duration_minutes", "problem_ids")} for t in TEMPLATES]}


@router.post("/from-template")
async def create_from_template_route(req: FromTemplateRequest, admin: User = Depends(require_admin)):
    try:
        contest = await cs.create_from_template(req.template_id, req.name, admin.id, req.start_at)
    except ValueError as e:
        raise _bad(e)
    return _contest_out(contest)


@router.post("/")
async def create_new_contest(req: CreateContestRequest, admin: User = Depends(require_admin)):
    try:
        contest = await create_contest(
            req.name, req.start_at, req.end_at, req.problem_ids, created_by=admin.id,
            settings=req.settings, problem_configs=req.problem_configs, state=req.state, ai_landing=req.ai_landing,
        )
    except ValueError as e:  # includes pydantic ValidationError
        raise _bad(e)
    return _contest_out(contest)


@router.patch("/{contest_id}")
async def patch_contest(contest_id: str, req: UpdateContestRequest, admin: User = Depends(require_admin)):
    await _get_or_404(contest_id)
    try:
        contest = await update_contest(contest_id, req.model_dump(exclude_unset=True), actor=admin.id)
    except ValueError as e:
        raise _bad(e)
    return _contest_out(contest)


@router.delete("/{contest_id}")
async def delete_contest_route(contest_id: str, admin: User = Depends(require_admin)):
    if not await cs.delete_contest(contest_id, actor=admin.id):
        raise HTTPException(404, "Contest not found")
    return {"ok": True}


@router.put("/{contest_id}/problems")
async def put_problems(contest_id: str, req: SetProblemsRequest, admin: User = Depends(require_admin)):
    """Add / edit / remove / reorder problems and their per-problem config —
    allowed at any time, including while the contest is live."""
    await _get_or_404(contest_id)
    try:
        contest = await cs.set_problems(contest_id, [p.model_dump() for p in req.problems], actor=admin.id)
    except ValueError as e:
        raise _bad(e)
    return _contest_out(contest)


@router.post("/{contest_id}/stop")
async def stop_contest_now(contest_id: str, admin: User = Depends(require_admin)):
    """Admin "end now" action — irreversibly ends a live (or upcoming)
    contest immediately, regardless of its scheduled `end_at`. A submission
    attempted right after this call is rejected exactly like one made after
    the original deadline (see contest_status()'s `ended_early` check)."""
    await _get_or_404(contest_id)
    contest = await stop_contest(contest_id, actor=admin.id)
    return _contest_out(contest)


async def _lifecycle(contest_id: str, fn, *args) -> dict:
    await _get_or_404(contest_id)
    try:
        return _contest_out(await fn(contest_id, *args))
    except ValueError as e:
        raise _bad(e)


@router.post("/{contest_id}/start-now")
async def start_contest_now(contest_id: str, admin: User = Depends(require_admin)):
    return await _lifecycle(contest_id, cs.start_now, admin.id)


@router.post("/{contest_id}/pause")
async def pause_contest_route(contest_id: str, admin: User = Depends(require_admin)):
    return await _lifecycle(contest_id, cs.pause_contest, admin.id)


@router.post("/{contest_id}/resume")
async def resume_contest_route(contest_id: str, admin: User = Depends(require_admin)):
    return await _lifecycle(contest_id, cs.resume_contest, admin.id)


@router.post("/{contest_id}/extend")
async def extend_contest_route(contest_id: str, req: ExtendRequest, admin: User = Depends(require_admin)):
    return await _lifecycle(contest_id, cs.extend_contest, req.minutes, admin.id)


@router.post("/{contest_id}/archive")
async def archive_contest_route(contest_id: str, req: ArchiveRequest, admin: User = Depends(require_admin)):
    return await _lifecycle(contest_id, cs.archive_contest, req.archived, admin.id)


@router.post("/{contest_id}/duplicate")
async def duplicate_contest_route(contest_id: str, req: DuplicateRequest, admin: User = Depends(require_admin)):
    await _get_or_404(contest_id)
    try:
        return _contest_out(await cs.duplicate_contest(contest_id, admin.id, req.name))
    except ValueError as e:
        raise _bad(e)


@router.get("/{contest_id}/admin")
async def get_contest_admin(contest_id: str, admin: User = Depends(require_admin)):
    """Everything the admin console edits: full settings (incl. access code),
    per-problem config, invite list and headline counts."""
    c = await _get_or_404(contest_id)
    out = _contest_out(c)
    teams = await cs.list_teams(contest_id)
    out.update({
        "settings": parse_settings(c.get("settings")).model_dump(),
        "problem_configs": {pid: parse_problem_config((c.get("problem_configs") or {}).get(pid)).model_dump()
                            for pid in c["problem_ids"]},
        "invited_emails": c.get("invited_emails") or [],
        "disqualified_user_ids": c.get("disqualified_user_ids") or [],
        "team_count": len(teams),
        "participant_count": sum(len(t["member_user_ids"]) for t in teams),
        "submission_count": await cs.contest_submissions_col.count_documents({"contest_id": contest_id}),
        "server_now": now_utc().isoformat(),
    })
    return out


# ---------------------------------------------------------------------------
# Admin: scoring controls, audit, participants, moderation
# ---------------------------------------------------------------------------
@router.post("/{contest_id}/adjustments")
async def add_adjustment_route(contest_id: str, req: AdjustmentRequest, admin: User = Depends(require_admin)):
    await _get_or_404(contest_id)
    try:
        return await cs.add_adjustment(contest_id, req.team_id, req.kind, req.points, req.penalty_minutes,
                                       req.reason, admin.id)
    except ValueError as e:
        raise _bad(e)


@router.get("/{contest_id}/adjustments")
async def get_adjustments(contest_id: str, admin: User = Depends(require_admin)):
    await _get_or_404(contest_id)
    return {"items": await cs.list_adjustments(contest_id)}


@router.delete("/{contest_id}/adjustments/{adj_id}")
async def delete_adjustment_route(contest_id: str, adj_id: str, admin: User = Depends(require_admin)):
    if not await cs.delete_adjustment(contest_id, adj_id, admin.id):
        raise HTTPException(404, "Adjustment not found")
    return {"ok": True}


@router.get("/{contest_id}/audit")
async def get_audit(contest_id: str, admin: User = Depends(require_admin)):
    return {"items": await cs.list_audit(contest_id)}


@router.get("/{contest_id}/submissions")
async def admin_list_submissions(contest_id: str, problem_id: Optional[str] = None, team_id: Optional[str] = None,
                                 admin: User = Depends(require_admin)):
    await _get_or_404(contest_id)
    return {"items": await cs.list_submissions(contest_id, problem_id, team_id)}


@router.post("/{contest_id}/submissions/{submission_id}/override")
async def override_submission_route(contest_id: str, submission_id: str, req: SubmissionOverrideRequest,
                                    admin: User = Depends(require_admin)):
    try:
        return await cs.override_submission(contest_id, submission_id, req.fraction, req.invalidated,
                                            req.reason, admin.id)
    except ValueError as e:
        raise _bad(e)


@router.post("/{contest_id}/rejudge")
async def rejudge_route(contest_id: str, req: RejudgeRequest, admin: User = Depends(require_admin)):
    await _get_or_404(contest_id)
    try:
        return await cs.rejudge(contest_id, admin.id, req.submission_id, req.problem_id)
    except PistonUnavailableError:
        raise HTTPException(502, "The code runner is temporarily unavailable — nothing was rejudged.")
    except ValueError as e:
        raise _bad(e)


@router.get("/{contest_id}/plagiarism")
async def plagiarism_route(contest_id: str, admin: User = Depends(require_admin)):
    await _get_or_404(contest_id)
    return {"items": await cs.plagiarism_report(contest_id)}


@router.post("/{contest_id}/leaderboard/reveal")
async def reveal_leaderboard(contest_id: str, req: RevealRequest, admin: User = Depends(require_admin)):
    """Lift (or re-apply) the freeze / hidden state for participants."""
    await _get_or_404(contest_id)
    try:
        c = await update_contest(contest_id, {"settings": {"leaderboard": {"revealed": req.revealed}}}, actor=admin.id)
    except ValueError as e:
        raise _bad(e)
    return _contest_out(c)


@router.get("/{contest_id}/participants")
async def admin_participants(contest_id: str, q: str = "", admin: User = Depends(require_admin)):
    await _get_or_404(contest_id)
    return {"items": await cs.list_participants(contest_id, q)}


@router.post("/{contest_id}/participants")
async def admin_add_participant(contest_id: str, req: AddParticipantRequest, admin: User = Depends(require_admin)):
    try:
        team = await cs.add_participant(contest_id, req.email, admin.id, req.team_id, req.team_name)
    except ValueError as e:
        raise _bad(e)
    return _team_out(team)


@router.delete("/{contest_id}/participants/{user_id}")
async def admin_remove_participant(contest_id: str, user_id: str, admin: User = Depends(require_admin)):
    if not await cs.remove_participant(contest_id, user_id, admin.id):
        raise HTTPException(404, "Participant not found")
    return {"ok": True}


@router.delete("/{contest_id}/teams/{team_id}")
async def admin_remove_team(contest_id: str, team_id: str, admin: User = Depends(require_admin)):
    if not await cs.remove_team(contest_id, team_id, admin.id):
        raise HTTPException(404, "Team not found")
    return {"ok": True}


@router.post("/{contest_id}/teams/{team_id}/disqualify")
async def disqualify_team(contest_id: str, team_id: str, req: ReasonRequest, admin: User = Depends(require_admin)):
    try:
        return _team_out(await cs.set_team_disqualified(contest_id, team_id, True, req.reason, admin.id))
    except ValueError as e:
        raise _bad(e)


@router.post("/{contest_id}/teams/{team_id}/reinstate")
async def reinstate_team(contest_id: str, team_id: str, admin: User = Depends(require_admin)):
    try:
        return _team_out(await cs.set_team_disqualified(contest_id, team_id, False, "", admin.id))
    except ValueError as e:
        raise _bad(e)


@router.post("/{contest_id}/participants/{user_id}/disqualify")
async def disqualify_user(contest_id: str, user_id: str, req: ReasonRequest, admin: User = Depends(require_admin)):
    try:
        await cs.set_user_disqualified(contest_id, user_id, True, req.reason, admin.id)
    except ValueError as e:
        raise _bad(e)
    return {"ok": True}


@router.post("/{contest_id}/participants/{user_id}/reinstate")
async def reinstate_user(contest_id: str, user_id: str, admin: User = Depends(require_admin)):
    try:
        await cs.set_user_disqualified(contest_id, user_id, False, "", admin.id)
    except ValueError as e:
        raise _bad(e)
    return {"ok": True}


@router.post("/{contest_id}/invites")
async def bulk_invite_route(contest_id: str, req: InviteRequest, admin: User = Depends(require_admin)):
    try:
        return await cs.bulk_invite(contest_id, req.emails, admin.id)
    except ValueError as e:
        raise _bad(e)


@router.get("/{contest_id}/export/standings.csv")
async def export_standings(contest_id: str, admin: User = Depends(require_admin)):
    await _get_or_404(contest_id)
    return Response(content=await cs.export_standings_csv(contest_id), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="standings-{contest_id}.csv"'})


@router.get("/{contest_id}/export/submissions.csv")
async def export_submissions(contest_id: str, admin: User = Depends(require_admin)):
    await _get_or_404(contest_id)
    return Response(content=await cs.export_submissions_csv(contest_id), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="submissions-{contest_id}.csv"'})


@router.post("/{contest_id}/announcements")
async def post_announcement(contest_id: str, req: AnnouncementRequest, admin: User = Depends(require_admin)):
    await _get_or_404(contest_id)
    try:
        return await cs.create_announcement(contest_id, req.text, req.pinned, admin.id)
    except ValueError as e:
        raise _bad(e)


@router.delete("/{contest_id}/announcements/{ann_id}")
async def remove_announcement(contest_id: str, ann_id: str, admin: User = Depends(require_admin)):
    if not await cs.delete_announcement(contest_id, ann_id, admin.id):
        raise HTTPException(404, "Announcement not found")
    return {"ok": True}


@router.post("/{contest_id}/clarifications/{clar_id}/answer")
async def answer_question(contest_id: str, clar_id: str, req: AnswerRequest, admin: User = Depends(require_admin)):
    try:
        return await cs.answer_clarification(contest_id, clar_id, req.answer, req.public, admin.id)
    except ValueError as e:
        raise _bad(e)


# ---------------------------------------------------------------------------
# Participants: browse contests, view detail
# ---------------------------------------------------------------------------
@router.get("/")
async def get_contests(user: User = Depends(get_current_user)):
    is_admin = user.role == "admin"
    items = await list_contests(include_hidden=is_admin)
    return {"items": [_contest_summary(c) for c in items]}


@router.get("/{contest_id}")
async def get_contest_detail(contest_id: str, user: User = Depends(get_current_user)):
    detail = await get_contest_public(contest_id, user_id=user.id, is_admin=user.role == "admin")
    if not detail:
        raise HTTPException(404, "Contest not found")
    return detail


@router.get("/{contest_id}/announcements")
async def get_announcements(contest_id: str, user: User = Depends(get_current_user)):
    await _visible_or_404(contest_id, user)
    return {"items": await cs.list_announcements(contest_id)}


@router.post("/{contest_id}/clarifications")
async def ask_question(contest_id: str, req: QuestionRequest, user: User = Depends(get_current_user)):
    await _visible_or_404(contest_id, user)
    try:
        return await cs.ask_clarification(contest_id, user.id, user.name, req.question, req.problem_id)
    except ValueError as e:
        raise _bad(e)


@router.get("/{contest_id}/clarifications")
async def get_clarifications(contest_id: str, user: User = Depends(get_current_user)):
    await _visible_or_404(contest_id, user)
    return {"items": await cs.list_clarifications(contest_id, user.id, admin=user.role == "admin")}


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
        team = await create_team(contest_id, req.name, member_ids, created_by=user.id,
                                 open_to_join=req.open_to_join, access_code=req.access_code)
    except ValueError as e:
        raise _bad(e)
    return _team_out(team)


@router.get("/{contest_id}/team/me")
async def get_my_contest_team(contest_id: str, user: User = Depends(get_current_user)):
    await _visible_or_404(contest_id, user)
    team = await get_my_team(contest_id, user.id)
    return {"team": _team_out(team) if team else None}


@router.get("/{contest_id}/teams/open")
async def get_open_teams(contest_id: str, user: User = Depends(get_current_user)):
    """The "join an open team" browse list — for a user with no pre-formed
    squad, this is how they find teammates at all, without knowing anyone's
    email in advance."""
    c = await _visible_or_404(contest_id, user)
    max_size = parse_settings(c.get("settings")).registration.effective_sizes()[1]
    teams = [t for t in await list_open_teams(contest_id) if not t.get("disqualified")]
    return {"items": [_open_team_out(t, max_size) for t in teams]}


@router.post("/{contest_id}/teams/{team_id}/join")
async def join_contest_team(contest_id: str, team_id: str, req: Optional[JoinTeamRequest] = None,
                            user: User = Depends(get_current_user)):
    try:
        team = await join_open_team(contest_id, team_id, user.id, access_code=req.access_code if req else None)
    except ValueError as e:
        raise _bad(e)
    return _team_out(team)


# ---------------------------------------------------------------------------
# Contest submission — the one deliberately-free lane in the whole app.
# ---------------------------------------------------------------------------
@router.post("/{contest_id}/problems/{problem_id}/submit")
async def submit_contest_solution(
    contest_id: str, problem_id: str, req: ContestSubmitRequest, user: User = Depends(get_current_user),
):
    contest = await _visible_or_404(contest_id, user)

    # Real, enforced time window — not just a UI countdown. A submission
    # outside [start_at, end_at] is rejected outright, never silently accepted.
    status_now = contest_status(contest)
    if status_now in ("upcoming", "draft"):
        raise HTTPException(403, f"This contest hasn't started yet — it opens at {contest['start_at']}")
    if status_now == "paused":
        raise HTTPException(403, "The contest is paused by the organisers — submissions reopen when it resumes")
    if status_now == "ended":
        raise HTTPException(403, f"This contest has ended — submissions closed at {contest['end_at']}")

    if problem_id not in contest["problem_ids"]:
        raise HTTPException(400, "This problem is not part of this contest")
    cfg = parse_problem_config((contest.get("problem_configs") or {}).get(problem_id))
    if cfg.hidden:
        raise HTTPException(400, "This problem is not part of this contest")
    if not is_released(contest, cfg, now_utc()):
        rel = release_time(contest, cfg)
        raise HTTPException(403, f"This problem unlocks at {rel.isoformat() if rel else 'a later time'}")

    team = await get_my_team(contest_id, user.id)
    if not team:
        raise HTTPException(400, "Join or create a team for this contest before submitting")
    if team.get("disqualified") or user.id in (contest.get("disqualified_user_ids") or []):
        raise HTTPException(403, "Your team has been disqualified from this contest")

    problem = await get_problem_raw(problem_id)
    if not problem:
        raise HTTPException(404, "Problem not found")
    if req.language not in (problem.get("starter_code") or {}):
        raise HTTPException(400, f"Problem does not support language `{req.language}`")
    if cfg.allowed_languages and req.language not in cfg.allowed_languages:
        raise HTTPException(400, f"This problem only accepts: {', '.join(cfg.allowed_languages)}")

    max_attempts = cs.max_attempts_for(contest, problem_id)
    attempts_used = await cs.count_attempts(contest_id, team["_id"], problem_id)
    if max_attempts and attempts_used >= max_attempts:
        raise HTTPException(403, f"Your team has used all {max_attempts} attempts for this problem")

    # AGENT/REVIEWER NOTE: contest submissions are FREE by deliberate business
    # decision — the hackathon is a free-entry event. Do NOT add a
    # precheck()/spend() call here to "fix" this; regular (non-contest)
    # /practice/.../submit still charges normally and is completely
    # unaffected. There is intentionally no pricing_engine entry for contest
    # submissions (see the comment in DEFAULT_PRICING, services/pricing_engine.py).
    try:
        run_result = await run_submission(
            problem, req.code, req.language,
            time_limit_ms=cfg.time_limit_ms, memory_limit_mb=cfg.memory_limit_mb, visible_indices=cfg.visible_tests,
        )
    except PistonUnavailableError as e:
        logger.warning("Piston unavailable during contest submit: %s", e)
        raise HTTPException(502, "The code runner is temporarily unavailable, so nothing was graded or counted. Please try again in a minute.")
    except ValueError as e:
        raise HTTPException(400, str(e))

    submission = await record_contest_submission(
        contest_id, team["_id"], user.id, problem_id, req.language, req.code, run_result,
    )
    from services.contest_scoring import submission_fraction
    fraction = submission_fraction(submission, cfg, parse_settings(contest.get("settings")).scoring.partial_scoring)

    return {
        "submission_id": submission["_id"],
        "results": run_result["results"],
        "passed_count": run_result["passed_count"],
        "total": run_result["total"],
        "all_passed": run_result["all_passed"],
        "fraction": round(fraction, 4),
        "points_awarded": round(cfg.points * fraction, 2),
        "attempts_used": attempts_used + 1,
        "attempts_left": (max_attempts - attempts_used - 1) if max_attempts else None,
        "credits_used": 0,
        "free": True,
    }


# ---------------------------------------------------------------------------
# Leaderboard — visible to every authenticated user unless the admin hides or
# freezes it (see contest_scoring.leaderboard_view). Never gated behind
# anything paid.
# ---------------------------------------------------------------------------
@router.get("/{contest_id}/leaderboard")
async def get_leaderboard(contest_id: str, user: User = Depends(get_current_user)):
    contest = await _visible_or_404(contest_id, user)
    return await cs.participant_leaderboard(contest, is_admin=user.role == "admin")


@router.get("/{contest_id}/my-stats")
async def get_my_stats(contest_id: str, user: User = Depends(get_current_user)):
    contest = await _visible_or_404(contest_id, user)
    stats = await get_user_contest_stats(contest_id, user.id)
    stats["award"] = cs.certificate_award(contest, stats)
    stats["prize"] = cs.prize_for_rank(contest, stats.get("team_rank")) if contest_status(contest) == "ended" else None
    return stats


# ---------------------------------------------------------------------------
# Certificate (PDF) + stats card (PNG) — issued to anyone who has made at
# least one contest submission (unless the admin raised the bar via the
# certificate options), not only the top finishers.
# ---------------------------------------------------------------------------
@router.get("/{contest_id}/certificate")
async def download_certificate(contest_id: str, user: User = Depends(get_current_user)):
    contest = await _visible_or_404(contest_id, user)
    stats = await get_user_contest_stats(contest_id, user.id)
    award = cs.certificate_award(contest, stats)
    if not award["eligible"]:
        raise HTTPException(404, award["reason"])

    pdf_bytes = generate_certificate_pdf(contest, user.name, award)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="certificate-{contest_id}.pdf"'},
    )


@router.get("/{contest_id}/stats-card")
async def download_stats_card(contest_id: str, user: User = Depends(get_current_user)):
    contest = await _visible_or_404(contest_id, user)
    stats = await get_user_contest_stats(contest_id, user.id)
    if not stats["has_participated"]:
        raise HTTPException(404, "You haven't made a submission in this contest yet")

    png_bytes = generate_stats_card_png(contest, user.name, stats)
    return Response(
        content=png_bytes,
        media_type="image/png",
        headers={"Content-Disposition": f'attachment; filename="stats-card-{contest_id}.png"'},
    )
