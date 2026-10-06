"""TimesJobs — POST search API, per `job-hive`'s documented endpoint/shape."""
import logging
from typing import Any, Dict, List
import httpx

logger = logging.getLogger(__name__)

SEARCH_URL = "https://tjapi.timesjobs.com/search/api/v1/search/jobs/list"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; IEMA-CareerPipeline/1.0)", "Content-Type": "application/json"}


async def search(keywords: str, location: str = "") -> List[Dict[str, Any]]:
    body = {"keyword": keywords, "location": location or "", "page": 1, "size": 20}
    async with httpx.AsyncClient(timeout=15, headers=HEADERS) as http:
        r = await http.post(SEARCH_URL, json=body)
    if r.status_code != 200:
        logger.warning(f"job_sources.timesjobs: HTTP {r.status_code}")
        return []
    try:
        data = r.json()
    except Exception:
        return []
    raw_list = data.get("jobs") or data.get("jobList") or data.get("data") or []
    jobs = []
    for j in raw_list:
        if not isinstance(j, dict):
            continue
        jobs.append({
            "title": j.get("title") or j.get("jobTitle"),
            "company": j.get("company") or j.get("companyName"),
            "location": j.get("location") or j.get("jobLocation"),
            "job_url": j.get("jobDetailUrl") or j.get("jobURL") or j.get("url"),
        })
    return [j for j in jobs if j.get("title") and j.get("job_url")]
