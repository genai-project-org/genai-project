"""Multi-board job search — direct scraping, no login, no email-alert dependency.

Mirrors the adapter-per-file + isolated-failure design of the user's other
`job-hive` project (src/lib/jobs/sources/*.ts): each board is its own module
exposing `async def search(keywords, location) -> list[dict]`, run concurrently
here so one board's failure or rate-limit never blocks the others.
"""
import asyncio
import logging
from typing import Any, Dict, List

from . import linkedin, naukri, indeed, timesjobs

logger = logging.getLogger(__name__)

_ADAPTERS = [
    ("linkedin", linkedin.search),
    ("naukri", naukri.search),
    ("indeed", indeed.search),
    ("timesjobs", timesjobs.search),
]


async def search_all(keywords: str, location: str = "") -> Dict[str, Any]:
    """Run every board concurrently. Returns normalized results plus a
    per-source status so a caller (or the UI) can show which boards worked."""

    async def _run(name: str, fn) -> tuple:
        try:
            results = await fn(keywords, location)
            return name, results, ("ok" if results else "empty")
        except Exception:
            logger.exception(f"job_sources.{name}: search failed")
            return name, [], "failed"

    outcomes = await asyncio.gather(*[_run(name, fn) for name, fn in _ADAPTERS])

    all_results: List[Dict[str, Any]] = []
    sources: Dict[str, str] = {}
    for name, results, status in outcomes:
        sources[name] = status
        for r in results:
            if not r.get("job_url"):
                continue
            r.setdefault("source_board", name)
            all_results.append(r)
    return {"results": all_results, "sources": sources}
