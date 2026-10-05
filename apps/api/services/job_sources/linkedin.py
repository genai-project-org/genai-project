"""LinkedIn — public guest job-search endpoint, no login required.

Mirrors the approach documented in the user's other `job-hive` project's README:
`jobs-guest/jobs/api/seeMoreJobPostings/search`, HTML job cards parsed for
`data-entity-urn`, title, company, location, and the apply link. That project
paginates at ~1 req/s; Phase 1 here only needs the first page (up to ~25 cards)
since results get capped and fit-scored downstream anyway.
"""
import logging
from typing import Any, Dict, List
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; IEMA-CareerPipeline/1.0)"}


async def search(keywords: str, location: str = "") -> List[Dict[str, Any]]:
    params = {
        "keywords": keywords,
        "location": location or "India",
        "f_TPR": "r604800",  # posted within the last 7 days
        "sortBy": "DD",
        "start": 0,
    }
    async with httpx.AsyncClient(timeout=15, headers=HEADERS) as http:
        r = await http.get(SEARCH_URL, params=params)
    if r.status_code != 200:
        logger.warning(f"job_sources.linkedin: HTTP {r.status_code}")
        return []

    soup = BeautifulSoup(r.text, "html.parser")
    jobs: List[Dict[str, Any]] = []
    for card in soup.select("li"):
        link_el = card.select_one("a.base-card__full-link, a")
        if not link_el or not link_el.get("href"):
            continue
        title_el = card.select_one(".base-search-card__title")
        company_el = card.select_one(".base-search-card__subtitle")
        location_el = card.select_one(".job-search-card__location")
        if not title_el:
            continue
        jobs.append({
            "title": title_el.get_text(strip=True),
            "company": company_el.get_text(strip=True) if company_el else None,
            "location": location_el.get_text(strip=True) if location_el else None,
            "job_url": link_el["href"].split("?")[0],
        })
    return jobs
