"""Code Builder — LLM-driven multi-file project scaffolder with caching.

Cost-optimization strategy:
- One LLM call per project creation returning full JSON project (files).
- Refine mode sends only the current file bundle + instruction (1 LLM call).
- (user_id, prompt hash) cached — identical prompts reuse the last result for free.
- Generated apps target static HTML/CSS/JS (with Tailwind + React via CDN) so
  they render in an <iframe srcDoc> without any hosting.
"""
import os
import json
import re
import hashlib
import logging
from typing import List, Dict, Any, Optional
from services.llm_client import LlmChat, UserMessage
from db import db, now_iso
from services.knowledge_retriever import retrieve, store as kb_store
from services.settings_service import get_setting

logger = logging.getLogger(__name__)

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")
BUILDER_MODEL = os.environ.get("BUILDER_MODEL", "claude-haiku-4-5-20251001")

builder_projects_col = db["builder_projects"]
builder_cache_col = db["builder_cache"]

GEN_SYSTEM_PROMPT = (
    "You are IEMA Code Builder — a senior full-stack engineer that ships tiny, self-contained web apps.\n"
    "Constraints for every response:\n"
    "1. Output ONLY a strict JSON object (no markdown fences, no prose).\n"
    "2. Schema: {\"name\": str, \"description\": str, \"files\": [{\"path\": str, \"content\": str, \"language\": str}]}\n"
    "3. Prefer a single-file `index.html` that uses Tailwind CDN and vanilla JS or React via unpkg.\n"
    "4. Keep total code under 400 lines. No external build steps. No package managers.\n"
    "5. `path` uses forward slashes. `language` is one of: html, css, javascript, jsx, json, markdown.\n"
    "6. Never include placeholder TODOs — the code must run as-is when opened in a browser.\n"
    "7. If the user asks for backend, generate a minimal `README.md` file explaining how to run and a plausible `server.js` — but always ALSO include a working static frontend `index.html`."
)

REFINE_SYSTEM_PROMPT = (
    "You are IEMA Code Builder in REFINE mode. The user will provide an existing project's files and an instruction.\n"
    "Respond with a JSON object matching {\"files\": [{\"path\", \"content\", \"language\"}]} containing the FULL new file set\n"
    "(include unchanged files too). No markdown, no prose. Preserve name/description unless the user asks to rename."
)


def _hash_prompt(user_id: str, prompt: str) -> str:
    return hashlib.sha256(f"{user_id}::{prompt.strip().lower()}".encode()).hexdigest()


def _extract_json(text: str) -> Dict[str, Any]:
    """Strip potential markdown fences and parse first JSON object."""
    text = text.strip()
    # Try direct
    try:
        return json.loads(text)
    except Exception:
        pass
    # Strip fences
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    # Fallback: find first { ... last }
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        return json.loads(text[start:end + 1])
    raise ValueError("LLM did not return JSON")


async def generate_project(user_id: str, prompt: str, gate=None) -> Dict[str, Any]:
    """Retrieve-first project generation. `gate` (if given) is awaited right before
    the expensive LLM call — used to enforce usage limits only on a cache miss, so
    cached hits stay free."""
    # (1) Data lake — cross-user semantic reuse
    if await get_setting("kb_enabled", True):
        hit = await retrieve("builder_generate", prompt, user_id=user_id)
        if hit and isinstance(hit["response"], dict):
            return {"cached": True, "source": "kb", "match": hit["match"], "score": hit["score"], **hit["response"]}

    # (2) Per-user legacy cache
    key = _hash_prompt(user_id, prompt)
    cached = await builder_cache_col.find_one({"_id": key})
    if cached:
        return {"cached": True, "source": "cache", **cached["payload"]}
    if gate:
        await gate()
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"builder-gen-{key[:10]}",
        system_message=GEN_SYSTEM_PROMPT,
    ).with_model("anthropic", BUILDER_MODEL)
    resp = await chat.send_message(UserMessage(text=prompt))
    content = resp if isinstance(resp, str) else getattr(resp, "content", str(resp))
    data = _extract_json(content)
    # Normalize
    data.setdefault("name", "Untitled")
    data.setdefault("description", prompt[:120])
    data.setdefault("files", [])
    payload = {
        "name": data["name"][:80],
        "description": data["description"][:200],
        "files": [
            {
                "path": f.get("path", "index.html")[:200],
                "content": f.get("content", "")[:60000],
                "language": f.get("language", "html")[:20],
            }
            for f in data["files"][:20]
        ],
    }
    await builder_cache_col.update_one(
        {"_id": key},
        {"$set": {"payload": payload, "created_at": now_iso()}},
        upsert=True,
    )
    await kb_store("builder_generate", prompt, payload, user_id=user_id,
                   meta={"file_count": len(payload["files"]), "name": payload["name"]})
    return {"cached": False, "source": "llm", **payload}


async def refine_project(existing_files: List[Dict[str, Any]], instruction: str, session_id: str) -> List[Dict[str, Any]]:
    """Refine an existing file set. Returns the new full file list."""
    files_summary = json.dumps({"files": existing_files}, ensure_ascii=False)
    text = (
        "Existing project files (JSON):\n" + files_summary +
        "\n\nInstruction from user:\n" + instruction
    )
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=session_id,
        system_message=REFINE_SYSTEM_PROMPT,
    ).with_model("anthropic", BUILDER_MODEL)
    resp = await chat.send_message(UserMessage(text=text))
    content = resp if isinstance(resp, str) else getattr(resp, "content", str(resp))
    data = _extract_json(content)
    files = data.get("files", [])
    return [
        {
            "path": f.get("path", "index.html")[:200],
            "content": f.get("content", "")[:60000],
            "language": f.get("language", "html")[:20],
        }
        for f in files[:20]
    ]


def compose_preview_html(files: List[Dict[str, Any]]) -> str:
    """Build a single self-contained HTML string from the project's files.

    Strategy:
    - If an `index.html` exists, inline all sibling .css and .js by rewriting
      the corresponding <link> and <script src=""> tags.
    - Otherwise, wrap the first .html/.js file in a minimal HTML shell.
    """
    by_path = {f["path"]: f["content"] for f in files}
    index = by_path.get("index.html") or by_path.get("Index.html")
    if not index:
        # Fallback: try any html file
        html_files = [f for f in files if f["path"].endswith(".html")]
        if html_files:
            index = html_files[0]["content"]
        else:
            return "<!doctype html><html><body><pre>No index.html in this project.</pre></body></html>"

    def _inline_link(m):
        href = m.group(1)
        content = by_path.get(href) or by_path.get(href.lstrip("./"))
        if content is None:
            return m.group(0)
        return f"<style>\n{content}\n</style>"

    def _inline_script(m):
        src = m.group(1)
        content = by_path.get(src) or by_path.get(src.lstrip("./"))
        if content is None:
            return m.group(0)
        return f"<script>\n{content}\n</script>"

    index = re.sub(r'<link[^>]+href=[\"\'](?!https?://)([^\"\']+)[\"\'][^>]*>', _inline_link, index)
    index = re.sub(r'<script[^>]+src=[\"\'](?!https?://)([^\"\']+)[\"\'][^>]*></script>', _inline_script, index)
    return index
