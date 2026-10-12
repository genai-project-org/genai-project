"""Seed (or refresh) a live demo Hack-a-Thon contest.

Usage (from apps/api, with the same .env the API uses):

    python scripts/seed_contest.py                    # live contest, 7 days
    python scripts/seed_contest.py --days 3           # custom window
    python scripts/seed_contest.py --with-leaderboard # + demo teams/solves so
                                                      #   the leaderboard isn't empty

Idempotent: keyed by contest name. Re-running resets the window to "started
1 hour ago, ends in N days" and clears any early stop, so the demo contest is
always live. Landing-page copy is a fixed, hand-written template (no LLM
call), so seeding works offline.

`--with-leaderboard` creates a handful of clearly-labelled demo accounts
(`demo.*@contest-demo.local`, no usable password) with teams and passing
submissions. Re-running replaces them.
"""
import argparse
import asyncio
import os
import sys
import uuid
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import now_iso, now_utc, users_col  # noqa: E402
from services.practice_service import seed_problems, practice_problems_col  # noqa: E402
from services.contest_service import (  # noqa: E402
    contests_col, contest_teams_col, contest_submissions_col, contest_announcements_col, ensure_indexes,
)
from services.contest_settings import ContestSettings, ProblemConfig  # noqa: E402

CONTEST_NAME = "Launch Hack-a-Thon 2026"

# Graduated difficulty from the stock practice bank (always seeded at API
# startup): two warm-ups, then three mediums.
PROBLEM_IDS = [
    "two-sum",
    "valid-palindrome",
    "binary-search",
    "two-sum-ii-sorted",
    "product-of-array-except-self",
]

LANDING_PAGE = {
    "headline": "The Launch Hack-a-Thon: 5 problems, one leaderboard",
    "tagline": "Team up (or go solo) and race through five hand-picked problems in Python, JavaScript, C++ or Java.",
    "highlights": [
        "5 problems, from warm-up to medium",
        "Free entry, free submissions, no credits spent",
        "Teams of 1-3, scored on distinct problems solved",
        "Live leaderboard and a certificate for every participant",
    ],
    "accent": "indigo",
    "layout": "split",
}

# Settings showcased by the demo contest (validated through the same pydantic
# schema the admin UI/API use, so the seed can never drift from the schema).
# Points-based scoring with graded points, partial credit on the hardest
# problem, first-solve + speed bonuses, milestone bonuses, a small wrong-
# submission penalty, a staged unlock (the last problem opens 75 minutes after
# start, i.e. shortly after seeding), prizes, and top-3 winner certificates.
DEMO_SETTINGS = ContestSettings.model_validate({
    "registration": {"mode": "both", "min_team_size": 1, "max_team_size": 3, "access": "public"},
    "scoring": {
        "mode": "points", "partial_scoring": True, "wrong_penalty_points": 5,
        "first_solve_bonus": 20, "speed_bonus_max": 30, "speed_bonus_decay_minutes": 1440,
        "milestone_bonuses": [{"solved": 3, "points": 25}, {"solved": 5, "points": 75}],
        "tie_breakers": ["time", "last_solve", "registered"],
    },
    "leaderboard": {"visibility": "visible", "freeze_minutes": 0},
    "prizes": [
        {"from_rank": 1, "to_rank": 1, "title": "Champion", "prize": "IEMA.ai swag + featured profile badge"},
        {"from_rank": 2, "to_rank": 3, "title": "Podium", "prize": "Certificate of Achievement"},
    ],
    "certificate": {"enabled": True, "winner_top_n": 3, "participation_min_solved": 0},
    "branding": {
        "description": "Five problems, one leaderboard. Solve fast, solve first, earn bonus points.",
        "rules_text": (
            "1. Teams of 1-3. One account per person.\n"
            "2. Points per problem as shown; partial credit for partially passing tests.\n"
            "3. First team to solve a problem earns +20; faster solves earn up to +30 speed bonus.\n"
            "4. Each wrong submission costs 5 points on that problem.\n"
            "5. No sharing code between teams - duplicate solutions are flagged and may be disqualified."
        ),
    },
}).model_dump()

DEMO_PROBLEM_CONFIGS = {
    pid: ProblemConfig.model_validate(cfg).model_dump() for pid, cfg in {
        "two-sum": {"points": 50},
        "valid-palindrome": {"points": 75},
        "binary-search": {"points": 100},
        "two-sum-ii-sorted": {"points": 150, "max_attempts": 10},
        "product-of-array-except-self": {"points": 250, "release_after_minutes": 75, "time_limit_ms": 3000},
    }.items()
}

DEMO_ANNOUNCEMENT = "Welcome to the Launch Hack-a-Thon! The final problem unlocks 75 minutes after the start."

DEMO_TEAMS = [
    # (team name, member names, [(problem_id, minutes after start)])
    ("Null Pointers", ["Aarav Mehta", "Isha Rao"],
     [("two-sum", 6), ("valid-palindrome", 11), ("binary-search", 19), ("two-sum-ii-sorted", 33)]),
    ("Stack Overflowers", ["Kabir Nair", "Meera Iyer", "Rohan Das"],
     [("two-sum", 9), ("valid-palindrome", 15), ("binary-search", 27)]),
    ("Byte Me", ["Sneha Kulkarni"],
     [("two-sum", 14), ("binary-search", 31)]),
    ("Segfault Squad", ["Vikram Singh", "Ananya Pillai"],
     [("two-sum", 22)]),
]


async def seed_contest(days: int) -> dict:
    await seed_problems()  # no-op if the practice bank is already seeded
    await ensure_indexes()

    missing = []
    for pid in PROBLEM_IDS:
        if not await practice_problems_col.find_one({"_id": pid}, {"_id": 1}):
            missing.append(pid)
    if missing:
        raise SystemExit(f"Practice problems not found: {', '.join(missing)}")

    now = now_utc()
    start = (now - timedelta(hours=1)).replace(microsecond=0)
    end = (now + timedelta(days=days)).replace(microsecond=0)
    fields = {
        "problem_ids": PROBLEM_IDS,
        "start_at": start.isoformat(),
        "end_at": end.isoformat(),
        "landing_page": LANDING_PAGE,
        "settings": DEMO_SETTINGS,
        "problem_configs": DEMO_PROBLEM_CONFIGS,
        "state": "published",
        "archived": False,
        "paused_at": None,
        "pauses": [],
        "ended_early": False,
        "updated_at": now_iso(),
    }
    existing = await contests_col.find_one({"name": CONTEST_NAME})
    if existing:
        await contests_col.update_one({"_id": existing["_id"]}, {"$set": fields})
        contest_id = existing["_id"]
        print(f"Refreshed contest '{CONTEST_NAME}' ({contest_id})")
    else:
        contest_id = uuid.uuid4().hex
        await contests_col.insert_one({
            "_id": contest_id, "name": CONTEST_NAME, "created_by": "seed-script",
            "created_at": now_iso(), **fields,
        })
        print(f"Created contest '{CONTEST_NAME}' ({contest_id})")
    await contest_announcements_col.delete_many({"contest_id": contest_id, "created_by": "seed-script"})
    await contest_announcements_col.insert_one({
        "_id": uuid.uuid4().hex, "contest_id": contest_id, "text": DEMO_ANNOUNCEMENT, "pinned": True,
        "created_by": "seed-script", "created_at": now_iso(),
    })
    print(f"  live {fields['start_at']} -> {fields['end_at']}, {len(PROBLEM_IDS)} problems, points-based scoring")
    return {"id": contest_id, "start": start}


async def seed_leaderboard(contest_id: str, start) -> None:
    # Replace any previous demo data (demo accounts only; real users untouched).
    old = [str(u["_id"]) async for u in users_col.find({"email": {"$regex": r"^demo\..*@contest-demo\.local$"}}, {"_id": 1})]
    if old:
        await contest_teams_col.delete_many({"contest_id": contest_id, "member_user_ids": {"$in": old}})
        await contest_submissions_col.delete_many({"contest_id": contest_id, "user_id": {"$in": old}})

    for team_name, members, solves in DEMO_TEAMS:
        ids = []
        for name in members:
            email = f"demo.{name.lower().replace(' ', '.')}@contest-demo.local"
            doc = await users_col.find_one({"email": email}, {"_id": 1})
            if doc:
                ids.append(str(doc["_id"]))
                continue
            res = await users_col.insert_one({
                "email": email, "name": name, "role": "user",
                "password_hash": "!", "created_at": now_iso(),
            })
            ids.append(str(res.inserted_id))
        team_id = uuid.uuid4().hex
        await contest_teams_col.insert_one({
            "_id": team_id, "contest_id": contest_id, "name": team_name,
            "member_user_ids": ids, "created_by": ids[0],
            "is_open": False, "disqualified": False, "created_at": now_iso(),
        })
        for i, (pid, minutes) in enumerate(solves):
            await contest_submissions_col.insert_one({
                "contest_id": contest_id, "team_id": team_id, "user_id": ids[i % len(ids)],
                "problem_id": pid, "language": "python", "code": "# demo submission",
                "passed_count": 1, "total": 1, "all_passed": True,
                "created_at": (start + timedelta(minutes=minutes)).isoformat(),
            })
        print(f"  demo team '{team_name}': {len(solves)} solved")


async def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=7, help="how many days from now the contest stays open")
    ap.add_argument("--with-leaderboard", action="store_true", help="also add demo teams with solves")
    args = ap.parse_args()

    info = await seed_contest(args.days)
    if args.with_leaderboard:
        await seed_leaderboard(info["id"], info["start"])
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
