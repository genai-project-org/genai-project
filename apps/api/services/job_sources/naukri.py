"""Naukri — JSON search API first, public HTML results as fallback.

Mirrors `job-hive`'s adapter: tries the `jobapi/v3/search` endpoint with the
`appid`/`systemid` headers it uses publicly; if that comes back gated
(recaptcha challenge), falls back to scraping the public HTML search page
instead of failing the whole board.
"""
import logging
from typing import Any, Dict, List
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

API_URL = "https://www.naukri.com/jobapi/v3/search"
HTML_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; IEMA-CareerPipeline/1.0)"}
API_HEADERS = {**HTML_HEADERS, "appid": "109", "systemid": "Naukri"}


def _slugify(text: str) -> str:
    return "-".join((text or "").lower().split())


async def _search_api(keywords: str, location: str) -> List[Dict[str, Any]]:
    params = {"noOfResults": 20, "urlType": "search_by_key_loc", "searchType": "adv",
              "keyword": keywords, "location": location, "pageNo": 1}
    async with httpx.AsyncClient(timeout=15, headers=API_HEADERS) as http:
        r = await http.get(API_URL, params=params)
    if r.status_code != 200:
        raise ValueError(f"HTTP {r.status_code}")
    data = r.json()
    if isinstance(data, dict) and "recaptcha" in str(data).lower():
        raise ValueError("recaptcha required")
    jobs = []
    for j in data.get("jobDetails", []) or []:
        jobs.append({
            "title": j.get("title"),
            "company": j.get("companyName"),
            "location": j.get("placeholders", {}).get("location") if isinstance(j.get("placeholders"), dict) else j.get("location"),
            "job_url": j.get("jdURL") or j.get("staticUrl"),
        })
    return [j for j in jobs if j.get("title") and j.get("job_url")]


async def _search_html(keywords: str, location: str) -> List[Dict[str, Any]]:
    # Naukri's search page is a Next.js app that streams its initial HTML with
    # an empty `jobDetails: []` and fetches results client-side after
    # hydration (confirmed live: the server-rendered payload never contains
    # job cards). This selector-based scrape is a best-effort placeholder for
    # if that ever changes; today it will typically return [] and the board
    # shows as "empty" rather than crash the whole search, exactly as
    # designed for a board that won't cooperate with a plain HTTP GET.
    slug = f"{_slugify(keywords)}-jobs"
    if location:
        slug += f"-in-{_slugify(location)}"
    async with httpx.AsyncClient(timeout=15, headers=HTML_HEADERS) as http:
        r = await http.get(f"https://www.naukri.com/{slug}")
    if r.status_code != 200:
        return []
    soup = BeautifulSoup(r.text, "html.parser")
    jobs = []
    for card in soup.select("article, .jobTuple, [class*='cust-job']"):
        title_el = card.select_one("a[class*='title'], a")
        company_el = card.select_one("[class*='comp-name'], [class*='company']")
        location_el = card.select_one("[class*='loc']")
        if not title_el or not title_el.get("href"):
            continue
        jobs.append({
            "title": title_el.get_text(strip=True),
            "company": company_el.get_text(strip=True) if company_el else None,
            "location": location_el.get_text(strip=True) if location_el else None,
            "job_url": title_el["href"].split("?")[0],
        })
    return jobs


async def search(keywords: str, location: str = "") -> List[Dict[str, Any]]:
    try:
        return await _search_api(keywords, location)
    except Exception as e:
        logger.info(f"job_sources.naukri: API path failed ({e}), falling back to HTML")
        return await _search_html(keywords, location)
