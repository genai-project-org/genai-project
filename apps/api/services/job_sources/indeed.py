"""Indeed India — JSON-LD job postings first (most stable across markup
changes), falling back to a light HTML card scrape. A Cloudflare 403 is a
per-source failure the orchestrator absorbs, not a whole-search failure.
"""
import json
import logging
from typing import Any, Dict, List
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; IEMA-CareerPipeline/1.0)"}


def _from_json_ld(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    jobs = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except Exception:
            continue
        entries = data if isinstance(data, list) else [data]
        for entry in entries:
            if not isinstance(entry, dict) or entry.get("@type") != "JobPosting":
                continue
            org = entry.get("hiringOrganization") or {}
            loc = entry.get("jobLocation") or {}
            address = loc.get("address") if isinstance(loc, dict) else {}
            jobs.append({
                "title": entry.get("title"),
                "company": org.get("name") if isinstance(org, dict) else None,
                "location": (address or {}).get("addressLocality") if isinstance(address, dict) else None,
                "job_url": entry.get("url"),
            })
    return [j for j in jobs if j.get("title")]


def _from_cards(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    jobs = []
    for card in soup.select(".job_seen_beacon, .jobsearch-SerpJobCard, .cardOutline"):
        title_el = card.select_one("h2 a, a.jcs-JobTitle")
        company_el = card.select_one("[data-testid='company-name'], .companyName")
        location_el = card.select_one("[data-testid='text-location'], .companyLocation")
        if not title_el:
            continue
        href = title_el.get("href") or ""
        jobs.append({
            "title": title_el.get_text(strip=True),
            "company": company_el.get_text(strip=True) if company_el else None,
            "location": location_el.get_text(strip=True) if location_el else None,
            "job_url": f"https://in.indeed.com{href}" if href.startswith("/") else (href or None),
        })
    return jobs


async def search(keywords: str, location: str = "") -> List[Dict[str, Any]]:
    async with httpx.AsyncClient(timeout=15, headers=HEADERS) as http:
        r = await http.get("https://in.indeed.com/jobs", params={"q": keywords, "l": location or "India"})
    if r.status_code != 200:
        logger.warning(f"job_sources.indeed: HTTP {r.status_code}")
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    jobs = _from_json_ld(soup)
    if not jobs:
        jobs = _from_cards(soup)
    return jobs
