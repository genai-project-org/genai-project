"""Unit tests for the pure contest scoring engine (services/contest_scoring.py)
and the settings schema (services/contest_settings.py). No DB, no network:
contests/teams/submissions are plain dicts, so every scoring rule — ICPC
penalty, points mode, step/bonus points, negative marking, partial credit,
grace marks, overrides, tie-breakers, pauses, freeze and disqualification —
is checked in isolation.
"""
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from services import contest_scoring as sc
from services.contest_settings import ContestSettings, ProblemConfig, parse_settings, validate_settings_patch

pytestmark = pytest.mark.unit

START = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def at(minutes):
    return (START + timedelta(minutes=minutes)).isoformat()


def make_contest(settings=None, configs=None, problems=("p1", "p2", "p3"), duration=120, **extra):
    return {
        "_id": "c1", "start_at": at(0), "end_at": at(duration), "problem_ids": list(problems),
        "settings": settings or {}, "problem_configs": configs or {}, **extra,
    }


def team(tid, created=0, name=None):
    return {"_id": tid, "name": name or tid, "member_user_ids": [f"u-{tid}"], "created_at": at(created)}


_n = [0]


def sub(tid, pid, minutes, ok=True, flags=None, **extra):
    _n[0] += 1
    flags = flags if flags is not None else ([True, True] if ok else [False, False])
    return {
        "_id": f"s{_n[0]}", "team_id": tid, "user_id": f"u-{tid}", "problem_id": pid, "created_at": at(minutes),
        "all_passed": all(flags), "passed_count": sum(flags), "total": len(flags), "passed_flags": flags, **extra,
    }


def standings(contest, teams, subs, adjustments=(), as_of=None):
    return sc.compute_standings(contest, teams, subs, adjustments, as_of=as_of)


def by_id(rows):
    return {r["team_id"]: r for r in rows}


# ---------------------------------------------------------------------------
# Defaults == original behaviour
# ---------------------------------------------------------------------------
def test_default_ranking_is_most_solved_then_least_total_time():
    c = make_contest()
    rows = standings(c, [team("A"), team("B"), team("C")], [
        sub("A", "p1", 10), sub("A", "p2", 30),          # 2 solved, 40 min
        sub("B", "p1", 5), sub("B", "p2", 20),           # 2 solved, 25 min -> beats A
        sub("C", "p1", 1),                               # 1 solved
    ])
    assert [r["team_id"] for r in rows] == ["B", "A", "C"]
    assert [r["rank"] for r in rows] == [1, 2, 3]
    assert by_id(rows)["B"]["total_time_seconds"] == 25 * 60


def test_unsolved_only_counts_after_full_pass_and_later_subs_ignored():
    c = make_contest()
    rows = standings(c, [team("A")], [sub("A", "p1", 5), sub("A", "p1", 50, ok=False)])
    assert rows[0]["problems_solved"] == 1
    assert rows[0]["total_time_seconds"] == 5 * 60


# ---------------------------------------------------------------------------
# ICPC penalty
# ---------------------------------------------------------------------------
def test_icpc_penalty_minutes_per_wrong_reorders_standings():
    c = make_contest({"scoring": {"mode": "icpc", "penalty_minutes_per_wrong": 20}})
    rows = standings(c, [team("A"), team("B")], [
        sub("A", "p1", 10, ok=False), sub("A", "p1", 11, ok=False), sub("A", "p1", 12),  # 12 + 2*20 = 52
        sub("B", "p1", 40),                                                              # 40
    ])
    r = by_id(rows)
    assert r["A"]["penalty_seconds"] == 52 * 60
    assert r["B"]["penalty_seconds"] == 40 * 60
    assert [x["team_id"] for x in rows] == ["B", "A"]


def test_icpc_wrong_attempts_on_unsolved_problem_cost_nothing():
    c = make_contest({"scoring": {"penalty_minutes_per_wrong": 20}})
    rows = standings(c, [team("A")], [sub("A", "p1", 5, ok=False), sub("A", "p1", 6, ok=False)])
    assert rows[0]["penalty_seconds"] == 0 and rows[0]["problems_solved"] == 0


# ---------------------------------------------------------------------------
# Points mode: base points, partial credit, negative marking, bonuses
# ---------------------------------------------------------------------------
def test_points_mode_uses_per_problem_points():
    c = make_contest({"scoring": {"mode": "points"}}, {"p1": {"points": 50}, "p2": {"points": 200}})
    rows = standings(c, [team("A"), team("B")], [sub("A", "p1", 1), sub("B", "p2", 90)])
    assert [r["team_id"] for r in rows] == ["B", "A"]  # 200 beats 50 despite being slower
    assert by_id(rows)["B"]["score"] == 200


def test_partial_scoring_respects_test_weights():
    c = make_contest({"scoring": {"mode": "points"}}, {"p1": {"points": 100, "test_weights": [1, 3]}})
    rows = standings(c, [team("A")], [sub("A", "p1", 5, flags=[False, True])])
    assert rows[0]["score"] == 75.0  # passed the weight-3 test of 4 total weight
    assert rows[0]["problems_solved"] == 0  # not a full solve


def test_partial_scoring_can_be_disabled():
    c = make_contest({"scoring": {"mode": "points", "partial_scoring": False}}, {"p1": {"points": 100}})
    rows = standings(c, [team("A")], [sub("A", "p1", 5, flags=[True, False])])
    assert rows[0]["score"] == 0


def test_best_partial_attempt_counts():
    c = make_contest({"scoring": {"mode": "points"}}, {"p1": {"points": 100}})
    rows = standings(c, [team("A")], [
        sub("A", "p1", 1, flags=[True, False]), sub("A", "p1", 2, flags=[False, False]),
    ])
    assert rows[0]["score"] == 50.0


def test_negative_marking_subtracts_per_wrong_before_solve_and_floors_at_zero():
    c = make_contest({"scoring": {"mode": "points", "wrong_penalty_points": 10}}, {"p1": {"points": 100}, "p2": {"points": 100}})
    rows = standings(c, [team("A")], [
        sub("A", "p1", 1, ok=False), sub("A", "p1", 2, ok=False), sub("A", "p1", 3),  # 100 - 20
        sub("A", "p2", 4, ok=False),                                                  # 0 - 10 -> floored
    ])
    r = rows[0]["per_problem"]
    assert r[0]["points"] == 80 and r[1]["points"] == 0
    assert rows[0]["score"] == 80


def test_first_solve_bonus_goes_only_to_earliest_solver():
    c = make_contest({"scoring": {"mode": "points", "first_solve_bonus": 25}}, {"p1": {"points": 100}})
    rows = standings(c, [team("A"), team("B")], [sub("B", "p1", 3), sub("A", "p1", 9)])
    r = by_id(rows)
    assert r["B"]["score"] == 125 and r["A"]["score"] == 100


def test_speed_bonus_decays_linearly_over_window():
    c = make_contest(
        {"scoring": {"mode": "points", "speed_bonus_max": 40, "speed_bonus_decay_minutes": 60}}, {"p1": {"points": 100}},
    )
    rows = standings(c, [team("A"), team("B"), team("C")], [
        sub("A", "p1", 0), sub("B", "p1", 30), sub("C", "p1", 90),
    ])
    r = by_id(rows)
    assert r["A"]["score"] == 140      # instant: full bonus
    assert r["B"]["score"] == 120      # halfway through decay window
    assert r["C"]["score"] == 100      # past the window: no bonus


def test_per_problem_bonus_override_beats_global():
    c = make_contest({"scoring": {"mode": "points", "first_solve_bonus": 10}}, {"p1": {"points": 0, "first_solve_bonus": 99}})
    rows = standings(c, [team("A")], [sub("A", "p1", 1)])
    assert rows[0]["score"] == 99


def test_milestone_bonuses_are_cumulative_thresholds():
    c = make_contest({"scoring": {"mode": "points", "milestone_bonuses": [{"solved": 2, "points": 10}, {"solved": 3, "points": 30}]}},
                     {"p1": {"points": 10}, "p2": {"points": 10}, "p3": {"points": 10}})
    rows = standings(c, [team("A"), team("B")], [
        sub("A", "p1", 1), sub("A", "p2", 2), sub("A", "p3", 3), sub("B", "p1", 1), sub("B", "p2", 2),
    ])
    r = by_id(rows)
    assert r["A"]["score"] == 30 + 10 + 30
    assert r["B"]["score"] == 20 + 10


# ---------------------------------------------------------------------------
# Grace marks, overrides, tie-breakers
# ---------------------------------------------------------------------------
def test_global_grace_applies_only_to_teams_that_submitted():
    c = make_contest({"scoring": {"mode": "points", "global_grace_points": 5}}, {"p1": {"points": 10}})
    rows = standings(c, [team("A"), team("B")], [sub("A", "p1", 1)])
    r = by_id(rows)
    assert r["A"]["score"] == 15
    assert r["B"]["score"] == 0


def test_manual_grace_and_override_adjustments():
    c = make_contest({"scoring": {"mode": "points"}}, {"p1": {"points": 100}})
    t = [team("A"), team("B")]
    s = [sub("A", "p1", 1), sub("B", "p1", 2)]
    adj = [
        {"team_id": "B", "kind": "grace", "points": 30, "penalty_minutes": 0, "created_at": at(5)},
    ]
    r = by_id(standings(c, t, s, adj))
    assert r["B"]["score"] == 130 and r["A"]["score"] == 100
    adj.append({"team_id": "A", "kind": "override", "points": 500, "created_at": at(6)})
    r = by_id(standings(c, t, s, adj))
    assert r["A"]["score"] == 500 and r["A"]["bonus"]["overridden"] is True


def test_grace_minutes_reduce_icpc_penalty():
    c = make_contest({"scoring": {"mode": "icpc", "penalty_minutes_per_wrong": 20}})
    t = [team("A")]
    s = [sub("A", "p1", 10, ok=False), sub("A", "p1", 20)]  # 20 + 20 = 40 min
    adj = [{"team_id": "A", "kind": "grace", "points": 0, "penalty_minutes": 15, "created_at": at(30)}]
    assert standings(c, t, s, adj)[0]["penalty_seconds"] == 25 * 60


def test_tie_breaker_last_solve_then_registration():
    # Equal score; B reached its last solve earlier.
    c = make_contest({"scoring": {"mode": "points", "tie_breakers": ["last_solve"]}}, {"p1": {"points": 10}, "p2": {"points": 10}})
    rows = standings(c, [team("A"), team("B")], [
        sub("A", "p1", 1), sub("A", "p2", 50), sub("B", "p1", 20), sub("B", "p2", 30),
    ])
    assert [r["team_id"] for r in rows] == ["B", "A"]
    # No difference at all -> earlier registration wins, deterministically.
    c2 = make_contest({"scoring": {"mode": "points", "tie_breakers": ["registered"]}})
    rows = standings(c2, [team("late", created=9), team("early", created=1)], [])
    assert [r["team_id"] for r in rows] == ["early", "late"]


# ---------------------------------------------------------------------------
# Pauses, disqualification, freeze
# ---------------------------------------------------------------------------
def test_paused_time_is_not_charged_to_participants():
    c = make_contest(pauses=[{"start": at(10), "end": at(40)}])
    rows = standings(c, [team("A")], [sub("A", "p1", 50)])
    assert rows[0]["total_time_seconds"] == 20 * 60


def test_disqualified_team_never_ranks_and_disqualified_user_subs_are_ignored():
    c = make_contest(disqualified_user_ids=["u-C"])
    dq = {**team("A"), "disqualified": True}
    rows = standings(c, [dq, team("B"), team("C")], [sub("A", "p1", 1), sub("B", "p1", 9), sub("C", "p1", 2)])
    r = by_id(rows)
    assert r["A"]["rank"] is None and r["A"]["disqualified"] is True
    assert rows[-1]["team_id"] == "A"  # disqualified teams are listed last
    assert r["B"]["rank"] == 1
    assert r["C"]["problems_solved"] == 0  # its only submission came from a disqualified user


def test_invalidated_submission_is_ignored_and_fraction_override_applies():
    c = make_contest({"scoring": {"mode": "points"}}, {"p1": {"points": 100}})
    rows = standings(c, [team("A"), team("B")], [
        sub("A", "p1", 1, invalidated=True), sub("B", "p1", 1, ok=False, fraction_override=0.4),
    ])
    r = by_id(rows)
    assert r["A"]["score"] == 0 and r["B"]["score"] == 40


def test_freeze_hides_late_submissions_from_the_frozen_board():
    c = make_contest({"leaderboard": {"freeze_minutes": 30}}, duration=120)
    t = [team("A"), team("B")]
    s = [sub("A", "p1", 10), sub("B", "p1", 100)]  # B solves inside the last 30 minutes
    view = sc.leaderboard_view(c, START + timedelta(minutes=100))
    assert view["frozen"] is True and view["as_of"] == START + timedelta(minutes=90)
    frozen = by_id(standings(c, t, s, as_of=view["as_of"]))
    assert frozen["B"]["problems_solved"] == 0 and frozen["A"]["problems_solved"] == 1
    live = by_id(standings(c, t, s))
    assert live["B"]["problems_solved"] == 1


def test_leaderboard_view_rules():
    now = START + timedelta(minutes=60)
    assert sc.leaderboard_view(make_contest(), now) == {"hidden": False, "frozen": False, "as_of": None}
    assert sc.leaderboard_view(make_contest({"leaderboard": {"visibility": "hidden"}}), now)["hidden"] is True
    after_end = make_contest({"leaderboard": {"visibility": "after_end"}})
    assert sc.leaderboard_view(after_end, now)["hidden"] is True
    assert sc.leaderboard_view(after_end, START + timedelta(minutes=121))["hidden"] is False
    # Freeze lifts at the end by default, but stays frozen when unfreeze_at_end is off until revealed.
    sticky = make_contest({"leaderboard": {"freeze_minutes": 30, "unfreeze_at_end": False}})
    assert sc.leaderboard_view(sticky, START + timedelta(minutes=125))["frozen"] is True
    revealed = make_contest({"leaderboard": {"freeze_minutes": 30, "unfreeze_at_end": False, "revealed": True}})
    assert sc.leaderboard_view(revealed, START + timedelta(minutes=125))["frozen"] is False
    lifts = make_contest({"leaderboard": {"freeze_minutes": 30}})
    assert sc.leaderboard_view(lifts, START + timedelta(minutes=125))["frozen"] is False


def test_release_time_absolute_and_relative():
    c = make_contest()
    rel = ProblemConfig(release_after_minutes=30)
    assert sc.release_time(c, rel) == START + timedelta(minutes=30)
    assert not sc.is_released(c, rel, START + timedelta(minutes=29))
    assert sc.is_released(c, rel, START + timedelta(minutes=30))
    assert sc.is_released(c, ProblemConfig(), START)
    absolute = ProblemConfig(release_at=at(15))
    assert not sc.is_released(c, absolute, START + timedelta(minutes=14))


def test_duplicate_code_detection_ignores_whitespace_and_comments():
    a = sub("A", "p1", 1, code="def f(x):\n    return x+1  # inc\n")
    b = sub("B", "p1", 2, code="def f(x): return x + 1\n")
    c = sub("C", "p1", 3, code="def f(x): return x * 2\n")
    groups = sc.find_duplicate_groups([a, b, c])
    assert len(groups) == 1 and set(groups[0]["team_ids"]) == {"A", "B"}


# ---------------------------------------------------------------------------
# Settings schema
# ---------------------------------------------------------------------------
def test_empty_settings_reproduce_legacy_defaults():
    s = parse_settings(None)
    assert s.scoring.mode == "icpc" and s.scoring.penalty_minutes_per_wrong == 0
    assert s.registration.effective_sizes() == (1, 3)
    assert s.registration.access == "public" and s.leaderboard.visibility == "visible"


def test_settings_validation_rejects_bad_values():
    with pytest.raises(ValidationError):
        ContestSettings.model_validate({"registration": {"min_team_size": 4, "max_team_size": 2}})
    with pytest.raises(ValidationError):
        ContestSettings.model_validate({"registration": {"access": "code"}})  # no code given
    with pytest.raises(ValidationError):
        ContestSettings.model_validate({"branding": {"banner_url": "javascript:alert(1)"}})
    with pytest.raises(ValidationError):
        ContestSettings.model_validate({"prizes": [{"from_rank": 3, "to_rank": 1, "title": "x"}]})
    with pytest.raises(ValidationError):
        ContestSettings.model_validate({"scoring": {"mode": "bogus"}})


def test_settings_patch_deep_merges_and_validates():
    base = ContestSettings().model_dump()
    merged = validate_settings_patch(base, {"scoring": {"mode": "points"}})
    assert merged["scoring"]["mode"] == "points" and merged["registration"]["max_team_size"] == 3
    with pytest.raises(ValidationError):
        validate_settings_patch(merged, {"scoring": {"first_solve_bonus": -1}})


def test_solo_and_team_mode_effective_sizes():
    assert ContestSettings.model_validate({"registration": {"mode": "solo"}}).registration.effective_sizes() == (1, 1)
    assert ContestSettings.model_validate({"registration": {"mode": "team", "max_team_size": 4}}).registration.effective_sizes() == (2, 4)
