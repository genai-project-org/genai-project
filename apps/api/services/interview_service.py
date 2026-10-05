"""Mock Interview — session lifecycle, entitlements, and per-turn orchestration.

Owns `interview_sessions_col` / `interview_turns_col` and the entitlement
collections (`interview_entitlement_grants_col` / `interview_entitlement_tx_col`).
Time-window enforcement is modeled directly on Contest Mode's
`contest_status()` (services/contest_service.py): status is recomputed from
stored timestamps at the point of every action, never trusted from the client.

Interview sessions are a SEPARATE, non-fungible entitlement track from the
wallet/credit system in pricing_engine.py — see the module docstring there
and models.py's RazorpayOrderRequest.pack_kind.

**Configurable interviews**: each `InterviewPack` (models.py) carries a
`config` (round durations, allowed topics/seniority/languages, optional
sub-topics per topic). Buying (or being admin-granted) a pack creates a new
`interview_entitlement_grants_col` doc that SNAPSHOTS that config — so a later
admin edit to the pack never retroactively changes a batch of sessions a
candidate already paid for, and a candidate who owns sessions from two
different packs can pick which one's format to use per interview. At session
creation, the candidate's fine-grained choices (topic, sub-topic, seniority,
language, whether to include the behavioral round) are validated against the
chosen grant's config — see create_session() below.

**Adjustable duration**: a pack's `technical_minutes`/`behavioral_minutes`
are DEFAULTS, not fixed values — a candidate who only has 15 minutes
shouldn't be forced into a 45-minute round they'll have to abandon halfway.
The candidate can shorten or lengthen either round within the global
MIN/MAX_*_MINUTES bounds below (independent of which pack — this is a
scheduling/UX concern, not a monetization lever; packs still gate topics,
languages, seniority and sub-topics, and whether a behavioral round exists
at all).
"""
import logging
import random
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status as http_status
from pymongo.errors import DuplicateKeyError

from db import (
    db, now_iso, now_utc,
    interview_entitlement_grants_col, interview_entitlement_tx_col,
    interview_sessions_col, interview_turns_col, interview_score_events_col,
)
from services import resume_profile_service, interview_agent, speech_service

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-sonnet-5"
HISTORY_TURN_LIMIT = 16  # most-recent turns sent to the agent per call; older ones are summarized
ABANDONED_CREATED_GRACE_MINUTES = 10  # a "created" session untouched this long is swept + refunded
HARD_EXPIRE_HOURS = 2  # defensive net against any session stuck by a crash

ACTIVE_STATUSES = ("created", "technical_in_progress", "behavioral_in_progress")

# A real interviewer speaks first — greets the candidate and asks the first
# question, rather than sitting in silence until the candidate volunteers
# something. Fed to interview_agent.run_turn() as the "user" turn for the
# opening call (see start_session()); NOT persisted as a candidate turn —
# only the resulting interviewer reply is, as transcript turn_index 0.
OPENING_CUE = (
    "[SESSION START] The candidate has just joined and can see and hear you now. "
    "Greet them warmly in 1-2 sentences, briefly set expectations for this round, "
    "then ask your first question directly. Do not wait for them to speak first."
)

SUPPORTED_CODING_LANGUAGES = {"python", "javascript", "cpp", "java"}


def _language_switch_cue(new_language: str) -> str:
    """Fed to the agent exactly like OPENING_CUE — a synthetic "turn" that
    isn't something the candidate said, only the resulting interviewer reply
    gets persisted/returned. See change_language()."""
    return (
        f"[LANGUAGE SWITCH] The candidate just switched their preferred coding language to "
        f"{new_language} using a UI control — they did not say this aloud. Acknowledge the switch "
        "in one short sentence, then call set_code_boilerplate to restate the CURRENT problem's "
        f"starter code in {new_language} (same problem, same difficulty — just translate the "
        "signature/boilerplate, not a new question). If you haven't posed a coding problem yet this "
        "round, just briefly confirm you'll use the new language once you do."
    )

# Candidate-adjustable duration bounds (minutes) — see module docstring.
MIN_TECHNICAL_MINUTES = 15
MAX_TECHNICAL_MINUTES = 90
MIN_BEHAVIORAL_MINUTES = 5
MAX_BEHAVIORAL_MINUTES = 30

# The 5 interviewer personas a candidate can be assigned (photorealistic
# synthetic avatar + a distinct Piper voice each, picked to match the
# persona's character — see the AvatarStage.jsx `INTERVIEWERS` mirror on the
# frontend, which must list these same ids/names/avatar files). `voice_file`
# is a bare filename resolved against PIPER_VOICE_DIR at synth time (see
# speech_service.voice_model_path()).
INTERVIEWERS: List[Dict[str, str]] = [
    {"id": "marcus-steele", "name": "Marcus Steele", "voice_file": "en_US-norman-medium.onnx"},
    {"id": "naomi-reyes", "name": "Naomi Reyes", "voice_file": "en_US-amy-medium.onnx"},
    {"id": "adrian-cole", "name": "Adrian Cole", "voice_file": "en_GB-alan-medium.onnx"},
    {"id": "sophia-lang", "name": "Sophia Lang", "voice_file": "en_US-kristin-medium.onnx"},
    {"id": "tariq-farouk", "name": "Tariq Farouk", "voice_file": "en_US-ryan-high.onnx"},
]
_INTERVIEWERS_BY_ID = {i["id"]: i for i in INTERVIEWERS}


def _pick_interviewer_id(last_interviewer_id: Optional[str]) -> str:
    """Random, but never the same interviewer the candidate got last time —
    per the product decision that back-to-back sessions should feel like a
    different person each time, not necessarily a full round-robin."""
    candidates = [i for i in INTERVIEWERS if i["id"] != last_interviewer_id] or INTERVIEWERS
    return random.choice(candidates)["id"]


def get_interviewer_public(interviewer_id: Optional[str]) -> Optional[Dict[str, str]]:
    info = _INTERVIEWERS_BY_ID.get(interviewer_id)
    return {"id": info["id"], "name": info["name"]} if info else None


# Fallback config for an entitlement grant not tied to a specific pack (e.g. an
# admin grant made with no pack_id) — mirrors InterviewPackConfig's own
# pydantic defaults in models.py so the two never drift apart silently.
DEFAULT_GRANT_CONFIG: Dict[str, Any] = {
    "technical_minutes": 45, "behavioral_minutes": 15,
    "topics": ["dsa", "hld", "lld", "design", "hr"],
    "seniority_levels": ["entry", "mid", "senior"],
    "languages": ["python", "javascript", "cpp", "java"],
    "sub_topics": {},
}


def _parse_iso(s: str) -> datetime:
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


async def ensure_indexes():
    await interview_entitlement_grants_col.create_index([("user_id", 1), ("created_at", 1)])
    await interview_entitlement_grants_col.create_index([("user_id", 1), ("sessions_remaining", 1)])
    await interview_entitlement_tx_col.create_index([("user_id", 1), ("created_at", -1)])
    await interview_sessions_col.create_index([("user_id", 1), ("created_at", -1)])
    await interview_sessions_col.create_index("status")
    # Enforces "at most one active session per candidate" at the DB level —
    # the check-then-act guard in create_session() is only a fast-path/nice
    # error message; this partial unique index is what actually prevents two
    # concurrent POST /sessions calls (double-click, two tabs) from both
    # inserting an active session for the same user.
    await interview_sessions_col.create_index(
        "user_id", unique=True, partialFilterExpression={"status": {"$in": list(ACTIVE_STATUSES)}},
        name="uniq_active_session_per_user",
    )
    await interview_turns_col.create_index([("session_id", 1), ("turn_index", 1)])
    await interview_score_events_col.create_index([("session_id", 1), ("round", 1)])


# ---------------------------------------------------------------------------
# Entitlements — a list of per-pack "grants", NOT a single wallet-style
# counter, so each grant can carry its own snapshotted config. See module
# docstring for why.
# ---------------------------------------------------------------------------
def _grant_to_public(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "grant_id": doc["_id"], "pack_slug": doc.get("pack_slug"), "pack_name": doc.get("pack_name"),
        "config": doc.get("config") or DEFAULT_GRANT_CONFIG,
        "sessions_total": doc.get("sessions_total", 0), "sessions_remaining": doc.get("sessions_remaining", 0),
    }


async def list_entitlement_grants(user_id: str) -> List[Dict[str, Any]]:
    """Every grant this user still has sessions left on — each is a distinct
    purchased/admin-granted "format" they can choose between at session setup."""
    grants = []
    async for doc in interview_entitlement_grants_col.find(
        {"user_id": user_id, "sessions_remaining": {"$gt": 0}}
    ).sort("created_at", 1):
        grants.append(_grant_to_public(doc))
    return grants


async def get_entitlement(user_id: str) -> Dict[str, Any]:
    """`sessions_remaining` is a simple aggregate total (for a plain "N sessions
    left" badge); `grants` is the full per-pack breakdown the setup wizard uses
    to offer a format choice when more than one exists."""
    grants = await list_entitlement_grants(user_id)
    return {
        "sessions_remaining": sum(g["sessions_remaining"] for g in grants),
        "grants": grants,
    }


async def _log_entitlement_tx(user_id: str, tx_type: str, sessions_delta: int, grant_id: Optional[str],
                              ref_id: Optional[str], description: str = "") -> None:
    await interview_entitlement_tx_col.insert_one({
        "user_id": user_id, "type": tx_type, "sessions_delta": sessions_delta,
        "grant_id": grant_id, "ref_id": ref_id, "description": description, "created_at": now_iso(),
    })


async def grant_sessions(user_id: str, sessions: int, *, pack: Optional[Dict[str, Any]] = None,
                         tx_type: str = "purchase", ref_id: Optional[str] = None,
                         description: str = "") -> Dict[str, Any]:
    """Create a NEW entitlement grant snapshotting `pack`'s config (or
    DEFAULT_GRANT_CONFIG if no pack given, e.g. a plain admin grant).
    Deliberately never adds to an existing grant — different grants can have
    different configs and must stay individually trackable/refundable."""
    config = (pack or {}).get("config") or DEFAULT_GRANT_CONFIG
    doc = {
        "_id": uuid.uuid4().hex, "user_id": user_id,
        "pack_id": (pack or {}).get("id") or (pack or {}).get("_id"),
        "pack_slug": (pack or {}).get("slug"),
        "pack_name": (pack or {}).get("name") or "Mock Interview Sessions",
        "config": config, "sessions_total": sessions, "sessions_remaining": sessions,
        "source": tx_type, "created_at": now_iso(), "updated_at": now_iso(),
    }
    await interview_entitlement_grants_col.insert_one(doc)
    await _log_entitlement_tx(user_id, tx_type, sessions, doc["_id"], ref_id, description)
    return _grant_to_public(doc)


async def precheck_and_reserve(user_id: str, grant_id: str) -> str:
    """Atomically consume one session from a SPECIFIC grant. Raises 404 if the
    grant isn't the caller's, 402 if it's exhausted. Returns an entitlement-tx
    id the session doc keeps, so a later refund can reference it."""
    owned = await interview_entitlement_grants_col.find_one({"_id": grant_id, "user_id": user_id})
    if not owned:
        raise HTTPException(404, "Interview pack entitlement not found")
    result = await interview_entitlement_grants_col.find_one_and_update(
        {"_id": grant_id, "user_id": user_id, "sessions_remaining": {"$gt": 0}},
        {"$inc": {"sessions_remaining": -1}, "$set": {"updated_at": now_iso()}},
    )
    if not result:
        raise HTTPException(
            http_status.HTTP_402_PAYMENT_REQUIRED,
            "This interview pack has no sessions remaining — buy another to continue.",
        )
    ref_id = uuid.uuid4().hex
    await _log_entitlement_tx(user_id, "consume", -1, grant_id, ref_id, "Mock interview session started")
    return ref_id


async def refund_session(user_id: str, grant_id: Optional[str], ref_id: Optional[str], description: str) -> None:
    if not grant_id:
        logger.warning(f"interview_service: refund_session called with no grant_id for user {user_id} — skipping")
        return
    await interview_entitlement_grants_col.update_one(
        {"_id": grant_id, "user_id": user_id},
        {"$inc": {"sessions_remaining": 1}, "$set": {"updated_at": now_iso()}},
    )
    await _log_entitlement_tx(user_id, "refund", 1, grant_id, ref_id, description)


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------
async def create_session(
    user_id: str, grant_id: Optional[str], topic: str, seniority: str = "mid",
    is_admin: bool = False, resume_profile_id: Optional[str] = None, sub_topic: Optional[str] = None,
    language: Optional[str] = None, include_behavioral: Optional[bool] = None,
    technical_minutes: Optional[int] = None, behavioral_minutes: Optional[int] = None,
) -> Dict[str, Any]:
    """`grant_id=None` is only valid for an admin (`is_admin=True`) — a
    dev/QA bypass so admins can test the interview flow without needing to
    buy or be granted a pack first. It uses DEFAULT_GRANT_CONFIG's full
    bounds (all topics/seniority/languages, standard durations) and consumes
    no entitlement at all — never happens for a regular candidate, who must
    always spend a real grant. See routers/interview_routes.py's call site
    for where `is_admin` is derived from the authenticated user's role."""
    existing = await interview_sessions_col.find_one({"user_id": user_id, "status": {"$in": ACTIVE_STATUSES}})
    if existing:
        # Recompute from stored timestamps before trusting this as truly
        # active — the background sweep runs on an interval, so a session
        # whose round time has already elapsed but hasn't been swept yet
        # would otherwise cause a spurious 409 here.
        existing = await _advance_time_based_transitions(existing)
        if existing["status"] in ACTIVE_STATUSES:
            raise HTTPException(http_status.HTTP_409_CONFLICT,
                                "You already have an active mock interview session — finish or abandon it first.")

    if grant_id:
        grant = await interview_entitlement_grants_col.find_one({"_id": grant_id, "user_id": user_id})
        if not grant:
            raise HTTPException(404, "Interview pack entitlement not found")
        config = grant.get("config") or DEFAULT_GRANT_CONFIG
    elif is_admin:
        config = DEFAULT_GRANT_CONFIG
    else:
        raise HTTPException(400, "grant_id is required")

    # Validate every candidate-chosen "fine" knob against this grant's
    # (pack-defined) "coarse" bounds — see module docstring.
    if topic not in (config.get("topics") or []):
        raise HTTPException(400, f"This pack doesn't include the '{topic}' topic.")
    if seniority not in (config.get("seniority_levels") or []):
        raise HTTPException(400, f"This pack doesn't offer the '{seniority}' seniority level.")
    allowed_sub_topics = (config.get("sub_topics") or {}).get(topic) or []
    if sub_topic and allowed_sub_topics and sub_topic not in allowed_sub_topics:
        raise HTTPException(400, f"'{sub_topic}' isn't a valid focus area for {topic} on this pack.")
    if language and language not in (config.get("languages") or []):
        raise HTTPException(400, f"This pack doesn't support the '{language}' language.")

    pack_behavioral_minutes = int(config.get("behavioral_minutes", 15))
    if include_behavioral is None:
        include_behavioral = pack_behavioral_minutes > 0
    elif include_behavioral and pack_behavioral_minutes <= 0:
        raise HTTPException(400, "This pack doesn't include a behavioral round.")

    # Duration is candidate-adjustable to fit their actual available time —
    # the pack's config values are only the DEFAULT, not a fixed ceiling. See
    # module docstring.
    final_technical_minutes = int(technical_minutes) if technical_minutes is not None else int(config.get("technical_minutes", 45))
    if not (MIN_TECHNICAL_MINUTES <= final_technical_minutes <= MAX_TECHNICAL_MINUTES):
        raise HTTPException(400, f"Technical round must be between {MIN_TECHNICAL_MINUTES} and {MAX_TECHNICAL_MINUTES} minutes.")

    if include_behavioral:
        final_behavioral_minutes = int(behavioral_minutes) if behavioral_minutes is not None else pack_behavioral_minutes
        if not (MIN_BEHAVIORAL_MINUTES <= final_behavioral_minutes <= MAX_BEHAVIORAL_MINUTES):
            raise HTTPException(400, f"Behavioral round must be between {MIN_BEHAVIORAL_MINUTES} and {MAX_BEHAVIORAL_MINUTES} minutes.")
    else:
        final_behavioral_minutes = 0

    if not resume_profile_id:
        profile = await resume_profile_service.get_profile(user_id)
        resume_profile_id = str(profile["_id"]) if profile else None

    # Consume the entitlement BEFORE inserting the session doc — same
    # "gate before the expensive work" placement pricing_engine.precheck()
    # uses elsewhere in this codebase. Skipped entirely for the admin
    # no-grant bypass — there's nothing to consume.
    entitlement_tx_id = await precheck_and_reserve(user_id, grant_id) if grant_id else None

    last_session = await interview_sessions_col.find_one(
        {"user_id": user_id}, sort=[("created_at", -1)],
    )
    interviewer_id = _pick_interviewer_id((last_session or {}).get("interviewer_id"))

    doc = {
        "_id": uuid.uuid4().hex,
        "user_id": user_id,
        "status": "created",
        "interviewer_id": interviewer_id,
        "topic": topic,
        "sub_topic": sub_topic,
        "seniority": seniority,
        "language": language,
        "include_behavioral": include_behavioral,
        "technical_minutes": final_technical_minutes,
        "behavioral_minutes": final_behavioral_minutes,
        "resume_profile_id": resume_profile_id,
        "provider": "anthropic",
        "model": DEFAULT_MODEL,
        "current_round": "technical",
        "technical_started_at": None,
        "technical_ends_at": None,
        "behavioral_started_at": None,
        "behavioral_ends_at": None,
        "warning_count": 0,
        "paused_at": None,
        "terminated_reason": None,
        "grant_id": grant_id,
        "entitlement_tx_id": entitlement_tx_id,
        "final_report_id": None,
        "llm_call_count": 0,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "ended_at": None,
    }
    try:
        await interview_sessions_col.insert_one(doc)
    except DuplicateKeyError:
        # Lost a genuine race against a concurrent create_session() call for
        # the same user (see the partial unique index in ensure_indexes()) —
        # the entitlement reserved above must be given back since this
        # session never actually starts.
        if grant_id:
            await refund_session(user_id, grant_id, entitlement_tx_id, "Refund: concurrent session create lost the race")
        raise HTTPException(http_status.HTTP_409_CONFLICT,
                            "You already have an active mock interview session — finish or abandon it first.")
    return doc


async def start_session(session_id: str, user_id: str) -> Dict[str, Any]:
    """Generates the interviewer's opening greeting + first question and
    starts the technical clock — this is the interview's real beginning from
    the candidate's perspective (not their first spoken reply, which was the
    old, confusing behavior: silence until the candidate volunteered
    something first). Idempotent — calling it again (e.g. a page refresh)
    replays the existing opening rather than generating a new one or
    re-starting an already-running clock."""
    session = await get_session(session_id, user_id)

    existing_first_turn = await interview_turns_col.find_one({"session_id": session_id, "turn_index": 0})
    if existing_first_turn:
        session = await _advance_time_based_transitions(session)
        return {
            "interviewer_text": existing_first_turn["text"],
            "interviewer_audio_base64": None,  # don't re-synthesize on a refresh/reconnect
            "round": session["current_round"],
            "minutes_remaining": round(_minutes_remaining(session, now_utc()), 1),
            "session_status": session["status"],
            "warning_count": session.get("warning_count", 0),
            "code_boilerplate": existing_first_turn.get("code_boilerplate"),
            "interviewer": get_interviewer_public(session.get("interviewer_id")),
        }

    if session["status"] != "created":
        raise HTTPException(http_status.HTTP_409_CONFLICT, "This session has already started.")

    now = now_utc()
    ends = now + timedelta(minutes=session.get("technical_minutes", 45))
    update = {"status": "technical_in_progress", "technical_started_at": now.isoformat(),
              "technical_ends_at": ends.isoformat(), "updated_at": now_iso()}
    await interview_sessions_col.update_one({"_id": session_id}, {"$set": update})
    session.update(update)

    resume_doc = None
    if session.get("resume_profile_id"):
        resume_doc = await resume_profile_service.get_profile(user_id)

    result = await interview_agent.run_turn(
        session=session, history=[], candidate_text=OPENING_CUE,
        resume_doc=resume_doc, minutes_remaining=session["technical_minutes"], questions_asked=0,
    )

    await interview_turns_col.insert_one({
        "session_id": session_id, "round": "technical", "turn_index": 0,
        "speaker": "interviewer", "modality": "voice", "text": result["interviewer_text"],
        "tool_calls": result["tool_calls"], "code_boilerplate": result.get("code_boilerplate"),
        "created_at": now_iso(),
    })
    await interview_sessions_col.update_one({"_id": session_id}, {"$inc": {"llm_call_count": 1}})

    audio_b64 = None
    try:
        voice_path = speech_service.voice_model_path(
            _INTERVIEWERS_BY_ID.get(session.get("interviewer_id"), {}).get("voice_file", "")
        )
        audio_bytes_out = await speech_service.synthesize(result["interviewer_text"], voice_path)
        if audio_bytes_out:
            import base64
            audio_b64 = base64.b64encode(audio_bytes_out).decode("ascii")
    except Exception:
        logger.exception("interview_service: TTS synth failed for opening, degrading to text-only")

    return {
        "interviewer_text": result["interviewer_text"],
        "interviewer_audio_base64": audio_b64,
        "round": "technical",
        "minutes_remaining": session["technical_minutes"],
        "session_status": "technical_in_progress",
        "warning_count": 0,
        "code_boilerplate": result.get("code_boilerplate"),
        "interviewer": get_interviewer_public(session.get("interviewer_id")),
    }


async def change_language(session_id: str, user_id: str, new_language: str) -> Dict[str, Any]:
    """Mid-round programming-language switch — DSA/technical-round only.
    Updates the session's preferred language, then asks the agent (via the
    same synthetic-cue pattern start_session() uses for the opening greeting)
    to restate the CURRENT problem's boilerplate in the new language, so the
    candidate isn't left coding the rest of it from scratch. Only the
    resulting interviewer reply is persisted as a turn — there's no real
    candidate utterance behind this, it's a UI action."""
    if new_language not in SUPPORTED_CODING_LANGUAGES:
        raise HTTPException(400, f"Unsupported language: {new_language}")

    session = await get_session(session_id, user_id)
    session = await _advance_time_based_transitions(session)
    if session["status"] not in ACTIVE_STATUSES:
        raise HTTPException(http_status.HTTP_409_CONFLICT, "This interview session is no longer active")
    if session.get("topic") != "dsa":
        raise HTTPException(400, "Changing the coding language only applies to DSA interviews")
    if session.get("current_round") != "technical":
        raise HTTPException(400, "The coding language can only be changed during the technical round")

    # Re-validate against the grant's config, same as create_session() does —
    # a pack can restrict which languages it supports.
    if session.get("grant_id"):
        grant = await interview_entitlement_grants_col.find_one({"_id": session["grant_id"]})
        allowed = (grant or {}).get("config", {}).get("languages")
        if allowed and new_language not in allowed:
            raise HTTPException(400, f"This pack doesn't support the '{new_language}' language.")

    if new_language == session.get("language"):
        return {"language": new_language, "interviewer_text": None, "interviewer_audio_base64": None, "code_boilerplate": None}

    await interview_sessions_col.update_one({"_id": session_id}, {"$set": {"language": new_language, "updated_at": now_iso()}})
    session["language"] = new_language

    resume_doc = None
    if session.get("resume_profile_id"):
        resume_doc = await resume_profile_service.get_profile(user_id)

    prior_turns = [t async for t in interview_turns_col.find({"session_id": session_id}).sort("turn_index", 1)]
    history = _turns_to_messages(prior_turns)
    questions_asked = len({
        e["question_index"] async for e in interview_score_events_col.find(
            {"session_id": session_id, "round": "technical"}, {"question_index": 1},
        )
    })
    minutes_remaining = _minutes_remaining(session, now_utc())

    result = await interview_agent.run_turn(
        session=session, history=history, candidate_text=_language_switch_cue(new_language),
        resume_doc=resume_doc, minutes_remaining=minutes_remaining, questions_asked=questions_asked,
    )

    next_index = len(prior_turns)
    await interview_turns_col.insert_one({
        "session_id": session_id, "round": "technical", "turn_index": next_index,
        "speaker": "interviewer", "modality": "voice", "text": result["interviewer_text"],
        "tool_calls": result["tool_calls"], "code_boilerplate": result.get("code_boilerplate"),
        "created_at": now_iso(),
    })
    await interview_sessions_col.update_one({"_id": session_id}, {"$inc": {"llm_call_count": 1}})

    audio_b64 = None
    try:
        voice_path = speech_service.voice_model_path(
            _INTERVIEWERS_BY_ID.get(session.get("interviewer_id"), {}).get("voice_file", "")
        )
        audio_bytes_out = await speech_service.synthesize(result["interviewer_text"], voice_path)
        if audio_bytes_out:
            import base64
            audio_b64 = base64.b64encode(audio_bytes_out).decode("ascii")
    except Exception:
        logger.exception("interview_service: TTS synth failed for language switch, degrading to text-only")

    return {
        "language": new_language,
        "interviewer_text": result["interviewer_text"],
        "interviewer_audio_base64": audio_b64,
        "code_boilerplate": result.get("code_boilerplate"),
    }


async def get_session(session_id: str, user_id: str) -> Dict[str, Any]:
    doc = await interview_sessions_col.find_one({"_id": session_id, "user_id": user_id})
    if not doc:
        raise HTTPException(404, "Interview session not found")
    return doc


def _minutes_remaining(session: Dict[str, Any], now: datetime) -> float:
    round_name = session["current_round"]
    ends_key = f"{round_name}_ends_at"
    ends_at = session.get(ends_key)
    default_minutes = session.get("technical_minutes", 45) if round_name == "technical" else session.get("behavioral_minutes", 15)
    if not ends_at:
        return default_minutes
    # While a blocking 2nd-warning acknowledgment is pending, freeze the
    # displayed remaining time at the moment it was paused rather than
    # letting it keep draining against real wall-clock time — see
    # acknowledge_warning() for where the round clock is actually
    # compensated once the candidate dismisses the dialog.
    effective_now = _parse_iso(session["paused_at"]) if session.get("paused_at") else now
    return max(0.0, (_parse_iso(ends_at) - effective_now).total_seconds() / 60.0)


async def _advance_time_based_transitions(session: Dict[str, Any]) -> Dict[str, Any]:
    """Recompute status from stored timestamps, exactly like Contest Mode's
    contest_status(). Mutates + persists the session doc if a transition is due,
    and returns the (possibly updated) doc.

    A session whose config has `include_behavioral=False` (this pack's format
    has no behavioral round, or the candidate opted out at setup) goes
    straight from technical to completed — never through a phantom
    zero-minute behavioral round.

    Skips entirely while `paused_at` is set (a blocking 2nd-warning
    acknowledgment is pending) — the round clock is frozen for that window
    and only resumes once acknowledge_warning() compensates it, so neither
    this function nor the background sweep should force a time-elapsed
    transition against time the candidate was never actually given."""
    if session.get("paused_at"):
        return session

    now = now_utc()
    status_ = session["status"]

    if status_ == "technical_in_progress" and session.get("technical_ends_at"):
        if now > _parse_iso(session["technical_ends_at"]):
            if session.get("include_behavioral"):
                behavioral_ends = now + timedelta(minutes=session.get("behavioral_minutes", 15))
                update = {
                    "status": "behavioral_in_progress", "current_round": "behavioral",
                    "behavioral_started_at": now.isoformat(), "behavioral_ends_at": behavioral_ends.isoformat(),
                    "updated_at": now_iso(),
                }
                await interview_sessions_col.update_one({"_id": session["_id"]}, {"$set": update})
                session.update(update)
            else:
                await _complete_session(session, reason="time_elapsed")
                session = await interview_sessions_col.find_one({"_id": session["_id"]})

    elif status_ == "behavioral_in_progress" and session.get("behavioral_ends_at"):
        if now > _parse_iso(session["behavioral_ends_at"]):
            await _complete_session(session, reason="time_elapsed")
            session = await interview_sessions_col.find_one({"_id": session["_id"]})

    return session


async def _complete_session(session: Dict[str, Any], reason: str) -> None:
    # Guarded update + only kick off the report if THIS call actually won the
    # transition — without the guard, two concurrent callers (e.g. a status
    # poll's time-elapsed check racing a candidate's own "end now") would
    # both report generate_report() for the same session.
    result = await interview_sessions_col.update_one(
        {"_id": session["_id"], "status": {"$in": ACTIVE_STATUSES}},
        {"$set": {"status": "completed", "ended_at": now_iso(), "updated_at": now_iso(),
                  "terminated_reason": reason}},
    )
    if result.modified_count:
        _kick_off_report(session["_id"])


def _kick_off_report(session_id: str) -> None:
    import asyncio
    from services import interview_report_service
    asyncio.create_task(interview_report_service.generate_report(session_id))


# ---------------------------------------------------------------------------
# Turn orchestration — STT -> agent tool loop -> TTS, all synchronous per call.
# ---------------------------------------------------------------------------
def _turns_to_messages(turns: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    messages = []
    for t in turns[-HISTORY_TURN_LIMIT:]:
        role = "assistant" if t["speaker"] == "interviewer" else "user"
        messages.append({"role": role, "content": t["text"]})
    return messages


async def handle_turn(
    session_id: str, user_id: str, *,
    modality: str, text: str = "", audio_bytes: Optional[bytes] = None,
) -> Dict[str, Any]:
    session = await get_session(session_id, user_id)
    session = await _advance_time_based_transitions(session)

    if session["status"] not in ACTIVE_STATUSES:
        return await _terminal_turn_response(session)

    now = now_utc()
    # First turn of the whole interview starts the technical clock — setup/
    # permission time before this call never eats into the round.
    if session["status"] == "created":
        ends = now + timedelta(minutes=session.get("technical_minutes", 45))
        update = {"status": "technical_in_progress", "technical_started_at": now.isoformat(),
                  "technical_ends_at": ends.isoformat(), "updated_at": now_iso()}
        await interview_sessions_col.update_one({"_id": session["_id"]}, {"$set": update})
        session.update(update)

    candidate_text = text
    if modality == "voice" and audio_bytes:
        try:
            candidate_text = await speech_service.transcribe(audio_bytes)
        except speech_service.SpeechServiceUnavailableError as e:
            raise HTTPException(503, str(e))
    if not candidate_text.strip():
        raise HTTPException(400, "No speech detected / empty answer — please try again.")

    round_name = session["current_round"]
    prior_turns = [t async for t in interview_turns_col.find({"session_id": session["_id"]}).sort("turn_index", 1)]
    history = _turns_to_messages(prior_turns)
    resume_doc = None
    if session.get("resume_profile_id"):
        resume_doc = await resume_profile_service.get_profile(user_id)

    questions_asked = len({
        e["question_index"] async for e in interview_score_events_col.find(
            {"session_id": session["_id"], "round": round_name}, {"question_index": 1},
        )
    })
    minutes_remaining = _minutes_remaining(session, now)

    result = await interview_agent.run_turn(
        session=session, history=history, candidate_text=candidate_text,
        resume_doc=resume_doc, minutes_remaining=minutes_remaining, questions_asked=questions_asked,
    )

    next_index = len(prior_turns)
    await interview_turns_col.insert_one({
        "session_id": session["_id"], "round": round_name, "turn_index": next_index,
        "speaker": "candidate", "modality": modality, "text": candidate_text,
        "tool_calls": [], "created_at": now_iso(),
    })
    await interview_turns_col.insert_one({
        "session_id": session["_id"], "round": round_name, "turn_index": next_index + 1,
        "speaker": "interviewer", "modality": "voice", "text": result["interviewer_text"],
        "tool_calls": result["tool_calls"], "code_boilerplate": result.get("code_boilerplate"),
        "created_at": now_iso(),
    })
    await interview_sessions_col.update_one({"_id": session["_id"]}, {"$inc": {"llm_call_count": 1}})

    # Advisory end_round: only honored once the server-side minimum-questions
    # guardrail is met — the agent's own judgment is a suggestion, not a
    # veto-proof decision. Re-count from interview_score_events_col rather
    # than assuming `questions_asked + 1` (the count from BEFORE this turn's
    # tool loop ran) — the agent may call end_round without having scored a
    # new question this turn (e.g. a clarifying follow-up), in which case the
    # "+1" would over-count and let the round end one question short.
    final_questions_asked = len({
        e["question_index"] async for e in interview_score_events_col.find(
            {"session_id": session["_id"], "round": round_name}, {"question_index": 1},
        )
    })
    min_q = interview_agent.MIN_QUESTIONS_BEFORE_END.get(round_name, 3)
    if result["end_requested"] and final_questions_asked >= min_q:
        if round_name == "technical" and session.get("include_behavioral"):
            ends = now + timedelta(minutes=session.get("behavioral_minutes", 15))
            update = {"status": "behavioral_in_progress", "current_round": "behavioral",
                      "behavioral_started_at": now.isoformat(), "behavioral_ends_at": ends.isoformat(),
                      "updated_at": now_iso()}
            await interview_sessions_col.update_one({"_id": session["_id"]}, {"$set": update})
            session.update(update)
        else:
            # Either the behavioral round just finished, or this session's
            # config has no behavioral round at all (pack format or candidate
            # opt-out) — either way, ending the technical round here means the
            # whole interview is done.
            await _complete_session(session, reason="agent_end_round")
            session = await interview_sessions_col.find_one({"_id": session["_id"]})

    audio_b64 = None
    try:
        voice_path = speech_service.voice_model_path(
            _INTERVIEWERS_BY_ID.get(session.get("interviewer_id"), {}).get("voice_file", "")
        )
        audio_bytes_out = await speech_service.synthesize(result["interviewer_text"], voice_path)
        if audio_bytes_out:
            import base64
            audio_b64 = base64.b64encode(audio_bytes_out).decode("ascii")
    except Exception:
        logger.exception("interview_service: TTS synth failed, degrading to text-only")

    return {
        "transcript": candidate_text,
        "interviewer_text": result["interviewer_text"],
        "interviewer_audio_base64": audio_b64,
        "round": session["current_round"],
        "minutes_remaining": round(_minutes_remaining(session, now_utc()), 1),
        "session_status": session["status"],
        "warning_count": session.get("warning_count", 0),
        "code_boilerplate": result.get("code_boilerplate"),
    }


async def _terminal_turn_response(session: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "transcript": "", "interviewer_text": "", "interviewer_audio_base64": None,
        "round": session["current_round"], "minutes_remaining": 0,
        "session_status": session["status"], "warning_count": session.get("warning_count", 0),
        "code_boilerplate": None,
    }


async def get_status(session_id: str, user_id: str) -> Dict[str, Any]:
    session = await get_session(session_id, user_id)
    session = await _advance_time_based_transitions(session)
    return {
        "session_status": session["status"], "round": session["current_round"],
        "minutes_remaining": round(_minutes_remaining(session, now_utc()), 1),
        "warning_count": session.get("warning_count", 0),
        "final_report_id": session.get("final_report_id"),
        "interviewer": get_interviewer_public(session.get("interviewer_id")),
    }


async def acknowledge_warning(session_id: str, user_id: str) -> Dict[str, Any]:
    """Clears the blocking 2nd-warning dialog AND compensates the current
    round's clock for exactly the time spent on it — `paused_at` is set
    server-side (proctoring_service.record_violation, the moment warning_count
    hits WARNINGS_BEFORE_TERMINATION), so the pause duration is measured by
    the server's own clock, never trusted from the client (same principle as
    every other proctoring signal in this module). Idempotent: calling this
    with no pause pending just returns current status."""
    session = await get_session(session_id, user_id)
    paused_at = session.get("paused_at")
    if not paused_at:
        session = await _advance_time_based_transitions(session)
        return {
            "session_status": session["status"], "round": session["current_round"],
            "minutes_remaining": round(_minutes_remaining(session, now_utc()), 1),
        }

    now = now_utc()
    pause_seconds = max(0.0, (now - _parse_iso(paused_at)).total_seconds())
    round_name = session["current_round"]
    ends_key = f"{round_name}_ends_at"
    update: Dict[str, Any] = {"paused_at": None, "updated_at": now_iso()}
    if session.get(ends_key):
        update[ends_key] = (_parse_iso(session[ends_key]) + timedelta(seconds=pause_seconds)).isoformat()
    await interview_sessions_col.update_one({"_id": session_id}, {"$set": update})
    session.update(update)
    session = await _advance_time_based_transitions(session)
    return {
        "session_status": session["status"], "round": session["current_round"],
        "minutes_remaining": round(_minutes_remaining(session, now_utc()), 1),
    }


async def end_session_early(session_id: str, user_id: str) -> Dict[str, Any]:
    """Candidate-initiated end (e.g. closes the tab intentionally / clicks "end now")."""
    session = await get_session(session_id, user_id)
    session = await _advance_time_based_transitions(session)
    if session["status"] not in ACTIVE_STATUSES:
        return {"session_status": session["status"]}
    has_content = await interview_turns_col.count_documents({"session_id": session_id}) > 0
    if has_content:
        await _complete_session(session, reason="candidate_ended_early")
        return {"session_status": "completed"}

    # Atomic guarded update — two concurrent "end now" calls (fast
    # double-click) on a session with no turns yet must not both flip to
    # "abandoned" and both refund the same consumed session.
    updated = await interview_sessions_col.find_one_and_update(
        {"_id": session_id, "status": {"$in": ACTIVE_STATUSES}},
        {"$set": {"status": "abandoned", "ended_at": now_iso(), "updated_at": now_iso()}},
    )
    if updated:
        await refund_session(user_id, session.get("grant_id"), session.get("entitlement_tx_id"),
                            "Refund: abandoned before any content")
        return {"session_status": "abandoned"}

    # Lost the race to a concurrent call — report whatever it actually left
    # the session as, rather than claim "abandoned" ourselves.
    current = await interview_sessions_col.find_one({"_id": session_id})
    return {"session_status": (current or {}).get("status", "abandoned")}


# ---------------------------------------------------------------------------
# Background sweep — reuses the APScheduler instance already started for the
# Knowledge Engine (see server.py's start_kb_engine); called on the same
# interval rather than standing up new scheduling infrastructure.
# ---------------------------------------------------------------------------
async def sweep_stale_sessions() -> None:
    now = now_utc()

    async for s in interview_sessions_col.find({"status": {"$in": ["technical_in_progress", "behavioral_in_progress"]}}):
        s = await _advance_time_based_transitions(s)

    grace_cutoff = (now - timedelta(minutes=ABANDONED_CREATED_GRACE_MINUTES)).isoformat()
    async for s in interview_sessions_col.find({"status": "created", "created_at": {"$lt": grace_cutoff}}):
        await interview_sessions_col.update_one(
            {"_id": s["_id"], "status": "created"},
            {"$set": {"status": "abandoned", "ended_at": now_iso(), "updated_at": now_iso()}},
        )
        await refund_session(s["user_id"], s.get("grant_id"), s.get("entitlement_tx_id"), "Refund: session never started")

    expire_cutoff = (now - timedelta(hours=HARD_EXPIRE_HOURS)).isoformat()
    async for s in interview_sessions_col.find({"status": {"$in": list(ACTIVE_STATUSES)}, "created_at": {"$lt": expire_cutoff}}):
        await interview_sessions_col.update_one(
            {"_id": s["_id"], "status": {"$in": list(ACTIVE_STATUSES)}},
            {"$set": {"status": "expired", "ended_at": now_iso(), "updated_at": now_iso(),
                      "terminated_reason": "stuck_session_hard_expire"}},
        )
        logger.warning(f"interview_service: hard-expired stuck session {s['_id']}")
