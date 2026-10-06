"""YouTube video links for practice problems — search-and-link only, never
downloaded/rehosted. Uses the official YouTube Data API v3 (free tier,
quota-limited), not any scraping.

YOUTUBE_API_KEY is a placeholder until a real key is provided — every
function here degrades gracefully to an empty result when it's unset, rather
than erroring, so the rest of the app is unaffected either way.
"""
import os
import logging
from typing import Any, Dict, List

import httpx

logger = logging.getLogger(__name__)

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"

# Channels we deliberately bias away from — direct competitors in this exact
# space. We still show results if nothing else ranks, but these are filtered
# out first / pushed to the back rather than handed the top slot.
COMPETITOR_CHANNELS = {
    "take u forward", "takeuforward", "striver",
    "neetcode",
    "codewithharry",
    "apna college",
    "love babbar",
}


def _is_competitor_channel(channel_title: str) -> bool:
    return (channel_title or "").strip().lower() in COMPETITOR_CHANNELS


async def find_solution_videos(problem_title: str, max_results: int = 3) -> List[Dict[str, Any]]:
    """Top `max_results` YouTube videos for `<problem_title> solution`, with
    known-competitor channels de-prioritized (shown last, only if there
    aren't enough non-competitor results to fill max_results).

    Returns [] if YOUTUBE_API_KEY isn't set yet — never raises for that case,
    since this is an enrichment, not a required part of the page."""
    if not YOUTUBE_API_KEY:
        logger.debug("YOUTUBE_API_KEY not set — skipping video lookup for %r", problem_title)
        return []

    query = f"{problem_title} solution"
    params = {
        "key": YOUTUBE_API_KEY,
        "q": query,
        "part": "snippet",
        "type": "video",
        "maxResults": 10,  # over-fetch so filtering competitors still leaves enough
        "relevanceLanguage": "en",
        "safeSearch": "strict",
    }
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(YOUTUBE_SEARCH_URL, params=params)
        resp.raise_for_status()
        items = resp.json().get("items", [])
    except httpx.HTTPError as e:
        logger.warning("YouTube search failed for %r: %s", problem_title, e)
        return []

    videos = []
    for item in items:
        vid = item.get("id", {}).get("videoId")
        snippet = item.get("snippet", {})
        if not vid:
            continue
        videos.append({
            "video_id": vid,
            "url": f"https://www.youtube.com/watch?v={vid}",
            "title": snippet.get("title", ""),
            "channel": snippet.get("channelTitle", ""),
            "thumbnail": (snippet.get("thumbnails", {}).get("medium") or {}).get("url", ""),
            "is_competitor_channel": _is_competitor_channel(snippet.get("channelTitle", "")),
        })

    non_competitor = [v for v in videos if not v["is_competitor_channel"]]
    competitor = [v for v in videos if v["is_competitor_channel"]]
    ordered = non_competitor + competitor  # competitors only fill remaining slots
    return ordered[:max_results]
