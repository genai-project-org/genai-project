"""Single source of truth for everything an admin can customise on a contest.

`ContestSettings` is stored (as a plain dict) on the contest document under
`settings`; per-problem knobs live under `problem_configs` keyed by problem id
(`ProblemConfig`). Both are validated here and ONLY here — routes and the
service call `parse_settings()` / `ProblemConfig` and never hand-roll checks.

Backwards compatibility: every field has a default that reproduces the
behaviour contests had before this schema existed (ICPC-style ranking by
distinct problems solved then total time, free public registration for teams
of 1-3, always-visible leaderboard, certificates for any participant). A
contest document with no `settings` key therefore behaves exactly as before.
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Language = Literal["python", "javascript", "cpp", "java"]
ALL_LANGUAGES: List[str] = ["python", "javascript", "cpp", "java"]
TieBreaker = Literal["time", "solved", "last_solve", "score", "registered"]

CONTEST_STATES = ("draft", "published")


def _safe_url(v: Optional[str]) -> Optional[str]:
    """Only http(s) (or empty) — a banner URL is rendered into an <img>/CSS
    url(), so `javascript:`/`data:` schemes are never accepted."""
    if v is None:
        return None
    v = v.strip()
    if not v:
        return None
    if not (v.startswith("https://") or v.startswith("http://")):
        raise ValueError("banner_url must start with http:// or https://")
    return v[:1000]


class _Base(BaseModel):
    model_config = ConfigDict(extra="ignore")


class RegistrationSettings(_Base):
    open: bool = True  # manual master switch (admin can close registration any time)
    open_at: Optional[str] = None  # ISO; None = open as soon as the contest is published
    close_at: Optional[str] = None  # ISO; None = open until the contest ends
    cap: int = Field(default=0, ge=0, le=1_000_000)  # max participants (users); 0 = unlimited
    mode: Literal["solo", "team", "both"] = "both"
    min_team_size: int = Field(default=1, ge=1, le=10)
    max_team_size: int = Field(default=3, ge=1, le=10)
    access: Literal["public", "invite_only", "code"] = "public"
    access_code: Optional[str] = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _check(self):
        if self.min_team_size > self.max_team_size:
            raise ValueError("min_team_size cannot exceed max_team_size")
        if self.access == "code" and not (self.access_code or "").strip():
            raise ValueError("access_code is required when access is 'code'")
        return self

    def effective_sizes(self) -> tuple:
        """(min, max) team size after applying the solo/team/both mode."""
        if self.mode == "solo":
            return 1, 1
        if self.mode == "team":
            return max(2, self.min_team_size), max(2, self.max_team_size)
        return self.min_team_size, self.max_team_size


class MilestoneBonus(_Base):
    solved: int = Field(ge=1, le=1000)  # bonus once the team has solved >= this many problems
    points: float = Field(ge=-100000, le=100000)


class ScoringSettings(_Base):
    mode: Literal["icpc", "points"] = "icpc"
    penalty_minutes_per_wrong: int = Field(default=0, ge=0, le=10_000)  # ICPC time penalty
    wrong_penalty_points: float = Field(default=0, ge=0, le=100_000)  # negative marking per wrong submission
    partial_scoring: bool = True  # per-test weights give partial credit (points mode)
    first_solve_bonus: float = Field(default=0, ge=0, le=100_000)
    speed_bonus_max: float = Field(default=0, ge=0, le=100_000)  # linearly decays to 0
    speed_bonus_decay_minutes: int = Field(default=0, ge=0, le=100_000)  # 0 = contest duration
    milestone_bonuses: List[MilestoneBonus] = Field(default_factory=list, max_length=50)
    global_grace_points: float = Field(default=0, ge=-100_000, le=100_000)
    global_grace_minutes: int = Field(default=0, ge=0, le=100_000)  # credited off every penalty
    max_attempts: int = Field(default=0, ge=0, le=10_000)  # per problem per team, 0 = unlimited
    tie_breakers: List[TieBreaker] = Field(default_factory=lambda: ["time", "last_solve", "registered"])
    plagiarism_check: bool = True

    @field_validator("tie_breakers")
    @classmethod
    def _dedupe(cls, v):
        return list(dict.fromkeys(v))


class LeaderboardSettings(_Base):
    visibility: Literal["visible", "hidden", "after_end"] = "visible"
    freeze_minutes: int = Field(default=0, ge=0, le=100_000)
    unfreeze_at_end: bool = True  # False = stays frozen after the end until an admin reveals it
    revealed: bool = False  # admin "reveal now": lifts freeze/after_end hiding permanently


class PrizeTier(_Base):
    from_rank: int = Field(ge=1, le=100_000)
    to_rank: int = Field(ge=1, le=100_000)
    title: str = Field(min_length=1, max_length=80)
    prize: str = Field(default="", max_length=200)

    @model_validator(mode="after")
    def _order(self):
        if self.to_rank < self.from_rank:
            raise ValueError("prize tier to_rank must be >= from_rank")
        return self


class CertificateSettings(_Base):
    enabled: bool = True
    winner_top_n: int = Field(default=0, ge=0, le=100_000)  # top N teams get an "Achievement" certificate
    participation_min_solved: int = Field(default=0, ge=0, le=1000)  # 0 = any submission
    issue_after: Literal["anytime", "ended"] = "anytime"


class BrandingSettings(_Base):
    banner_url: Optional[str] = None
    description: str = Field(default="", max_length=2000)
    rules_text: str = Field(default="", max_length=10_000)
    headline: str = Field(default="", max_length=100)  # overrides the generated landing headline
    tagline: str = Field(default="", max_length=220)

    @field_validator("banner_url")
    @classmethod
    def _url(cls, v):
        return _safe_url(v)


class ContestSettings(_Base):
    registration: RegistrationSettings = Field(default_factory=RegistrationSettings)
    scoring: ScoringSettings = Field(default_factory=ScoringSettings)
    leaderboard: LeaderboardSettings = Field(default_factory=LeaderboardSettings)
    prizes: List[PrizeTier] = Field(default_factory=list, max_length=20)
    certificate: CertificateSettings = Field(default_factory=CertificateSettings)
    branding: BrandingSettings = Field(default_factory=BrandingSettings)
    clarifications_enabled: bool = True


class ProblemConfig(_Base):
    points: float = Field(default=100, ge=0, le=100_000)
    time_limit_ms: Optional[int] = Field(default=None, ge=100, le=30_000)
    memory_limit_mb: Optional[int] = Field(default=None, ge=16, le=4096)
    allowed_languages: Optional[List[Language]] = None  # None = every language the problem supports
    test_weights: Optional[List[float]] = None  # by test-case index; missing entries weigh 1
    visible_tests: Optional[List[int]] = None  # test indices whose input/expected are shown; None = samples only
    release_at: Optional[str] = None  # absolute staged unlock
    release_after_minutes: Optional[int] = Field(default=None, ge=0, le=1_000_000)  # unlock N min after start
    max_attempts: Optional[int] = Field(default=None, ge=0, le=10_000)  # None = inherit scoring.max_attempts
    first_solve_bonus: Optional[float] = Field(default=None, ge=0, le=100_000)
    speed_bonus_max: Optional[float] = Field(default=None, ge=0, le=100_000)
    hidden: bool = False  # admin can hide a problem entirely (unpublished) without removing it

    @field_validator("test_weights")
    @classmethod
    def _weights(cls, v):
        if v is None:
            return v
        if len(v) > 500 or any(w < 0 or w > 1_000_000 for w in v):
            raise ValueError("test_weights must be >= 0")
        return v


def parse_settings(raw: Optional[Dict[str, Any]]) -> ContestSettings:
    """Tolerant read for stored docs: anything invalid/missing falls back to
    defaults so an old or hand-edited document can never 500 a request."""
    try:
        return ContestSettings.model_validate(raw or {})
    except Exception:
        return ContestSettings()


def parse_problem_config(raw: Optional[Dict[str, Any]]) -> ProblemConfig:
    try:
        return ProblemConfig.model_validate(raw or {})
    except Exception:
        return ProblemConfig()


def deep_merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def validate_settings_patch(existing: Optional[Dict[str, Any]], patch: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a partial settings patch into the stored one and validate the
    result strictly (raises pydantic.ValidationError -> HTTP 422/400)."""
    merged = deep_merge(existing or {}, patch or {})
    return ContestSettings.model_validate(merged).model_dump()


def default_settings_dict() -> Dict[str, Any]:
    return ContestSettings().model_dump()


# ---------------------------------------------------------------------------
# Quick-create templates. Problem ids are resolved against the real bank at
# creation time (unknown ids are dropped), so a template never breaks if the
# bank changes.
# ---------------------------------------------------------------------------
TEMPLATES: List[Dict[str, Any]] = [
    {
        "id": "sprint-1h",
        "name": "1-hour ICPC sprint",
        "description": "Solo or teams, 4 easy problems, ICPC ranking with 20-minute wrong-answer penalty, leaderboard freezes for the last 10 minutes.",
        "duration_minutes": 60,
        "problem_ids": ["two-sum", "contains-duplicate", "valid-anagram", "best-time-to-buy-sell-stock"],
        "settings": {
            "registration": {"mode": "both", "max_team_size": 3},
            "scoring": {"mode": "icpc", "penalty_minutes_per_wrong": 20},
            "leaderboard": {"freeze_minutes": 10},
        },
        "problem_config": {"points": 100},
    },
    {
        "id": "points-weekend",
        "name": "Weekend points contest",
        "description": "5 problems with graded points, speed + first-solve bonuses, partial credit and a small wrong-submission penalty.",
        "duration_minutes": 48 * 60,
        "problem_ids": ["two-sum", "valid-palindrome", "binary-search", "two-sum-ii-sorted", "product-of-array-except-self"],
        "settings": {
            "scoring": {
                "mode": "points", "wrong_penalty_points": 5, "first_solve_bonus": 20,
                "speed_bonus_max": 30, "speed_bonus_decay_minutes": 1440,
                "milestone_bonuses": [{"solved": 3, "points": 25}, {"solved": 5, "points": 75}],
                "tie_breakers": ["time", "last_solve", "registered"],
            },
            "prizes": [
                {"from_rank": 1, "to_rank": 1, "title": "Champion", "prize": "Trophy + certificate"},
                {"from_rank": 2, "to_rank": 3, "title": "Runner-up", "prize": "Certificate"},
            ],
            "certificate": {"winner_top_n": 3},
        },
        "point_ladder": [50, 100, 150, 200, 250],
    },
    {
        "id": "team-3h",
        "name": "3-hour team contest",
        "description": "Teams of 2-3 only, ICPC scoring, 3 attempts cap per problem, registration closes when the contest starts.",
        "duration_minutes": 180,
        "problem_ids": ["valid-palindrome", "binary-search", "two-sum-ii-sorted", "product-of-array-except-self"],
        "settings": {
            "registration": {"mode": "team", "min_team_size": 2, "max_team_size": 3},
            "scoring": {"mode": "icpc", "penalty_minutes_per_wrong": 10, "max_attempts": 0},
            "leaderboard": {"freeze_minutes": 30, "unfreeze_at_end": False},
        },
    },
    {
        "id": "invite-only",
        "name": "Invite-only mock round",
        "description": "Private contest: only invited emails can register. Points-based, leaderboard revealed after the end.",
        "duration_minutes": 90,
        "problem_ids": ["two-sum", "valid-anagram", "binary-search"],
        "settings": {
            "registration": {"access": "invite_only", "mode": "solo"},
            "scoring": {"mode": "points"},
            "leaderboard": {"visibility": "after_end"},
        },
        "point_ladder": [100, 150, 250],
    },
]


def get_template(template_id: str) -> Optional[Dict[str, Any]]:
    return next((t for t in TEMPLATES if t["id"] == template_id), None)
