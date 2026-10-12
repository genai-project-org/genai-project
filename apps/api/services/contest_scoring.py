"""Pure (no DB, no I/O) scoring + standings engine for contests, so every rule
is unit-testable and the leaderboard / CSV export / certificates all share one
implementation. `contest_service.compute_leaderboard()` just loads documents
and calls `compute_standings()`.

Rules (all driven by `ContestSettings`, see contest_settings.py):

* A submission's *fraction* is the weighted share of test cases it passed
  (`ProblemConfig.test_weights`, default weight 1 each). With
  `partial_scoring` off it is 1.0 only when every test passed.
* A problem is *solved* when a submission reaches fraction 1.0. Submissions
  after the first full solve are ignored.
* Elapsed time is wall-clock since `start_at` minus any admin pauses.
* Per problem (points): base*best_fraction + speed bonus + first-solve bonus
  - wrong_penalty_points * wrong attempts before the solve; floored at 0.
  Speed bonus decays linearly from its max to 0 over the decay window.
* ICPC penalty: sum over solved problems of (elapsed + penalty_minutes *
  wrong attempts before the solve), minus any grace minutes.
* Team score = problem points + milestone bonuses (each threshold reached
  adds its points) + global grace (only teams with >=1 submission) + manual
  adjustments. A manual "override" replaces the computed score entirely.
* Ranking: `icpc` -> most solved, then least penalty; `points` -> highest
  score; then `tie_breakers` in order; finally team creation time.
* Disqualified teams (or submissions by disqualified users) never rank.
* `as_of` freezes the board: submissions after that instant are invisible.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

from services.contest_settings import ProblemConfig, parse_problem_config, parse_settings

EPS = 1e-9


def parse_iso(s: str) -> datetime:
    d = datetime.fromisoformat(s)
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


def pause_overlap_seconds(contest: dict, t: datetime) -> float:
    """Total seconds the contest was paused between its start and `t`."""
    start = parse_iso(contest["start_at"])
    total = 0.0
    for p in contest.get("pauses") or []:
        try:
            ps = parse_iso(p["start"])
            pe = parse_iso(p["end"]) if p.get("end") else t
        except Exception:
            continue
        lo, hi = max(ps, start), min(pe, t)
        if hi > lo:
            total += (hi - lo).total_seconds()
    return total


def elapsed_seconds(contest: dict, t: datetime) -> float:
    start = parse_iso(contest["start_at"])
    return max(0.0, (t - start).total_seconds() - pause_overlap_seconds(contest, t))


def release_time(contest: dict, cfg: ProblemConfig) -> Optional[datetime]:
    """When a problem unlocks (None = available from the start)."""
    if cfg.release_at:
        try:
            return parse_iso(cfg.release_at)
        except Exception:
            return None
    if cfg.release_after_minutes:
        return parse_iso(contest["start_at"]) + timedelta(minutes=cfg.release_after_minutes)
    return None


def is_released(contest: dict, cfg: ProblemConfig, now: datetime) -> bool:
    r = release_time(contest, cfg)
    return r is None or now >= r


def submission_fraction(sub: dict, cfg: ProblemConfig, partial: bool = True) -> float:
    if sub.get("fraction_override") is not None:
        return max(0.0, min(1.0, float(sub["fraction_override"])))
    all_passed = bool(sub.get("all_passed"))
    if not partial:
        return 1.0 if all_passed else 0.0
    flags = sub.get("passed_flags")
    if flags:
        weights = cfg.test_weights or []
        ws = [weights[i] if i < len(weights) else 1.0 for i in range(len(flags))]
        tw = sum(ws)
        if tw <= 0:
            return 1.0 if all_passed else 0.0
        return sum(w for w, ok in zip(ws, flags) if ok) / tw
    if all_passed:
        return 1.0
    total = sub.get("total") or 0
    return (sub.get("passed_count", 0) / total) if total else 0.0


def normalized_code_hash(code: str) -> str:
    """Whitespace/comment-insensitive fingerprint used for the cheap duplicate
    (plagiarism) flag. Not a real similarity engine — exact-match after
    stripping comments, whitespace and case."""
    c = re.sub(r"(#.*?$|//.*?$)", "", code or "", flags=re.MULTILINE)
    c = re.sub(r"/\*.*?\*/", "", c, flags=re.DOTALL)
    c = re.sub(r"\s+", "", c).lower()
    return hashlib.sha1(c.encode()).hexdigest()


def compute_standings(
    contest: dict,
    teams: List[dict],
    subs: Iterable[dict],
    adjustments: Iterable[dict] = (),
    as_of: Optional[datetime] = None,
) -> List[dict]:
    """Return one row per team, ranked. Disqualified teams are included with
    `disqualified: True` and `rank: None` after all ranked teams."""
    settings = parse_settings(contest.get("settings"))
    sc = settings.scoring
    problem_ids: List[str] = list(contest.get("problem_ids") or [])
    configs = {pid: parse_problem_config((contest.get("problem_configs") or {}).get(pid)) for pid in problem_ids}
    start = parse_iso(contest["start_at"])
    end = parse_iso(contest["end_at"])
    duration_min = max(1.0, (end - start).total_seconds() / 60.0)
    dq_users = set(contest.get("disqualified_user_ids") or [])
    team_by_id = {t["_id"]: t for t in teams}

    ordered = sorted(
        (s for s in subs if s["problem_id"] in configs and s["team_id"] in team_by_id and not s.get("invalidated")),
        key=lambda s: (s["created_at"], str(s.get("_id", ""))),
    )

    # (team, problem) -> state
    state: Dict[tuple, dict] = {}
    for s in ordered:
        if s.get("user_id") in dq_users:
            continue
        t = parse_iso(s["created_at"])
        if as_of is not None and t > as_of:
            continue
        key = (s["team_id"], s["problem_id"])
        st = state.setdefault(key, {
            "attempts": 0, "wrong": 0, "best": 0.0, "solved": False, "solved_at": None, "elapsed": None, "t": None,
        })
        if st["solved"]:
            continue
        cfg = configs[s["problem_id"]]
        frac = submission_fraction(s, cfg, sc.partial_scoring)
        st["attempts"] += 1
        st["best"] = max(st["best"], frac)
        if frac >= 1.0 - EPS:
            st["solved"] = True
            st["t"] = t
            st["elapsed"] = elapsed_seconds(contest, t)
        else:
            st["wrong"] += 1

    # First solver per problem (non-DQ teams only).
    first_solver: Dict[str, tuple] = {}
    for (tid, pid), st in state.items():
        if st["solved"] and not team_by_id[tid].get("disqualified"):
            cur = first_solver.get(pid)
            if cur is None or st["t"] < cur[0]:
                first_solver[pid] = (st["t"], tid)

    adj_by_team: Dict[str, List[dict]] = {}
    for a in adjustments:
        adj_by_team.setdefault(a["team_id"], []).append(a)

    rows = []
    for team in teams:
        tid = team["_id"]
        solved = 0
        points = 0.0
        penalty = 0.0
        total_time = 0.0
        last_solve: Optional[float] = None
        per_problem = []
        any_sub = False
        for pid in problem_ids:
            cfg = configs[pid]
            st = state.get((tid, pid))
            if not st:
                per_problem.append({"problem_id": pid, "attempts": 0, "wrong": 0, "solved": False, "points": 0, "fraction": 0})
                continue
            any_sub = True
            p_points = cfg.points * st["best"]
            if st["solved"]:
                solved += 1
                el = st["elapsed"]
                total_time += el
                penalty += el + st["wrong"] * sc.penalty_minutes_per_wrong * 60
                last_solve = el if last_solve is None else max(last_solve, el)
                sb_max = cfg.speed_bonus_max if cfg.speed_bonus_max is not None else sc.speed_bonus_max
                if sb_max:
                    window = sc.speed_bonus_decay_minutes or duration_min
                    p_points += sb_max * max(0.0, 1.0 - (el / 60.0) / window)
                fsb = cfg.first_solve_bonus if cfg.first_solve_bonus is not None else sc.first_solve_bonus
                if fsb and first_solver.get(pid, (None, None))[1] == tid:
                    p_points += fsb
            p_points -= st["wrong"] * sc.wrong_penalty_points
            p_points = max(0.0, p_points)
            points += p_points
            per_problem.append({
                "problem_id": pid, "attempts": st["attempts"], "wrong": st["wrong"], "solved": st["solved"],
                "points": round(p_points, 2), "fraction": round(st["best"], 4),
                "solved_at_seconds": round(st["elapsed"]) if st["solved"] else None,
            })

        milestone = sum(m.points for m in sc.milestone_bonuses if solved >= m.solved)
        grace_points = sc.global_grace_points if any_sub else 0.0
        grace_minutes = sc.global_grace_minutes if any_sub and solved else 0
        adj_points = 0.0
        adj_minutes = 0.0
        override = None
        for a in sorted(adj_by_team.get(tid, []), key=lambda a: a.get("created_at", "")):
            if a.get("kind") == "override":
                override = float(a.get("points", 0))
            else:
                adj_points += float(a.get("points", 0))
                adj_minutes += float(a.get("penalty_minutes", 0))
        score = points + milestone + grace_points + adj_points
        if override is not None:
            score = override
        penalty = max(0.0, penalty - (grace_minutes + adj_minutes) * 60) if solved else max(0.0, penalty)

        rows.append({
            "team_id": tid,
            "team_name": team["name"],
            "member_user_ids": team["member_user_ids"],
            "problems_solved": solved,
            "total_time_seconds": round(total_time),
            "penalty_seconds": round(penalty),
            "score": round(score, 2),
            "last_solve_seconds": round(last_solve) if last_solve is not None else None,
            "per_problem": per_problem,
            "bonus": {
                "milestone": round(milestone, 2), "grace": round(grace_points + adj_points, 2),
                "overridden": override is not None,
            },
            "disqualified": bool(team.get("disqualified")),
            "_created": team.get("created_at", ""),
        })

    def sort_key(r):
        if sc.mode == "points":
            primary = (-r["score"],)
        else:
            primary = (-r["problems_solved"], r["penalty_seconds"])
        extra = []
        for tb in sc.tie_breakers:
            if tb == "time":
                extra.append(r["penalty_seconds"])
            elif tb == "solved":
                extra.append(-r["problems_solved"])
            elif tb == "last_solve":
                extra.append(r["last_solve_seconds"] if r["last_solve_seconds"] is not None else float("inf"))
            elif tb == "score":
                extra.append(-r["score"])
            elif tb == "registered":
                extra.append(r["_created"])
        return primary + tuple(extra) + (r["_created"], r["team_id"])

    ranked = sorted((r for r in rows if not r["disqualified"]), key=sort_key)
    dq = sorted((r for r in rows if r["disqualified"]), key=lambda r: r["_created"])
    for i, r in enumerate(ranked):
        r["rank"] = i + 1
    for r in dq:
        r["rank"] = None
    out = ranked + dq
    for r in out:
        del r["_created"]
    return out


def find_duplicate_groups(subs: Iterable[dict]) -> List[dict]:
    """Passing submissions from DIFFERENT teams with identical normalised
    code on the same problem — a cheap copy/paste flag for admins to review."""
    buckets: Dict[tuple, Dict[str, dict]] = {}
    for s in subs:
        if not s.get("all_passed"):
            continue
        h = normalized_code_hash(s.get("code", ""))
        b = buckets.setdefault((s["problem_id"], h), {})
        b.setdefault(s["team_id"], s)
    groups = []
    for (pid, h), by_team in buckets.items():
        if len(by_team) > 1:
            groups.append({
                "problem_id": pid,
                "team_ids": list(by_team.keys()),
                "submission_ids": [str(x.get("_id")) for x in by_team.values()],
            })
    return groups


def leaderboard_view(contest: dict, now: datetime) -> Dict[str, Any]:
    """What a PARTICIPANT may see right now: {hidden, frozen, as_of}.
    Admins bypass this (they always see live standings)."""
    lb = parse_settings(contest.get("settings")).leaderboard
    end = parse_iso(contest["end_at"])
    ended = bool(contest.get("ended_early")) or now > end
    if lb.revealed:
        return {"hidden": False, "frozen": False, "as_of": None}
    if lb.visibility == "hidden":
        return {"hidden": True, "frozen": False, "as_of": None}
    if lb.visibility == "after_end" and not ended:
        return {"hidden": True, "frozen": False, "as_of": None}
    if lb.freeze_minutes:
        freeze_at = end - timedelta(minutes=lb.freeze_minutes)
        if (not ended and now >= freeze_at) or (ended and not lb.unfreeze_at_end):
            return {"hidden": False, "frozen": True, "as_of": freeze_at}
    return {"hidden": False, "frozen": False, "as_of": None}
