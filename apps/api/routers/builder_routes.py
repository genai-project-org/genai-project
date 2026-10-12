"""Code Builder routes — projects, refine, GitHub push, S3 share."""
import os
import re
import uuid
import secrets
import base64
import hashlib
import logging
from typing import List, Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from bson import ObjectId
import httpx
from cryptography.fernet import Fernet
from auth import get_current_user
from models import User
from db import db, now_iso
from services.builder_service import (
    generate_project, refine_project, compose_preview_html, builder_projects_col
)
from db import db as _db
builder_templates_col = _db["builder_templates"]
from services.credit_service import has_credits, deduct_credits
from services.pricing_engine import spend, precheck
from services.storage_service import upload_bytes, upload_bytes_at_key, get_signed_url, is_configured
from services.data_lake import log_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/builder", tags=["builder"])

CREDIT_BUILDER_CREATE = float(os.environ.get("CREDIT_BUILDER_CREATE", "15"))
CREDIT_BUILDER_REFINE = float(os.environ.get("CREDIT_BUILDER_REFINE", "8"))

# Pricing keys per builder kind — resolved through pricing_col so admins can edit them.
_PRICE_KEY = {
    "static": {"create": "builder_create", "refine": "builder_refine"},
    "react": {"create": "builder_dyn_create", "refine": "builder_dyn_refine"},
}


def _price_key(kind: str, action: str) -> str:
    return _PRICE_KEY.get(kind, _PRICE_KEY["static"])[action]


def _kind_filter(kind: str) -> dict:
    """Projects created before `kind` existed are static, so match missing too."""
    if kind == "static":
        return {"$or": [{"kind": "static"}, {"kind": {"$exists": False}}]}
    return {"kind": kind}


# ---- PAT encryption -----------------------------------------------------
def _fernet() -> Fernet:
    secret = os.environ.get("JWT_SECRET", "")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def _encrypt(plain: str) -> str:
    return _fernet().encrypt(plain.encode()).decode()


def _decrypt(cipher: str) -> str:
    return _fernet().decrypt(cipher.encode()).decode()


# ---- request models -----------------------------------------------------
class CreateProjectRequest(BaseModel):
    prompt: str = Field(min_length=8, max_length=2000)
    kind: Literal["static", "react"] = "static"


class RefineRequest(BaseModel):
    instruction: str = Field(min_length=3, max_length=1000)


class ShareRequest(BaseModel):
    # react projects are bundled in the browser (the server has no JS toolchain),
    # so the client hands us the composed HTML. Ignored for static projects.
    html: Optional[str] = Field(default=None, max_length=2_000_000)


class SaveFilesRequest(BaseModel):
    files: List[dict]


class GithubPushRequest(BaseModel):
    pat: Optional[str] = None  # If provided, is stored (encrypted). Otherwise reuses saved.
    repo: str = Field(min_length=1, max_length=140)  # "name" or "owner/repo"
    commit_message: Optional[str] = None  # auto-generated from the project history when empty
    save_pat: bool = True
    private: bool = True


# ---- helpers ------------------------------------------------------------
def _to_public_project(doc: dict) -> dict:
    doc = dict(doc)
    doc["id"] = str(doc.pop("_id"))
    return doc


async def _load_project(user_id: str, project_id: str) -> dict:
    try:
        doc = await builder_projects_col.find_one({"_id": ObjectId(project_id), "user_id": user_id})
    except Exception:
        doc = None
    if not doc:
        raise HTTPException(404, "Project not found")
    return doc


# ---- routes -------------------------------------------------------------
@router.get("/templates")
async def list_templates():
    """Public — no auth. Landing-page gallery."""
    cursor = builder_templates_col.find({}, {"files": 0}).sort("order", 1)
    items = []
    async for d in cursor:
        d["id"] = str(d.pop("_id"))
        items.append(d)
    return {"items": items}


@router.get("/templates/{slug}")
async def get_template(slug: str):
    doc = await builder_templates_col.find_one({"slug": slug})
    if not doc:
        raise HTTPException(404, "Template not found")
    doc["id"] = str(doc.pop("_id"))
    return doc


@router.get("/templates/{slug}/preview")
async def template_preview(slug: str):
    """Public — used by landing page iframe."""
    doc = await builder_templates_col.find_one({"slug": slug})
    if not doc:
        raise HTTPException(404, "Template not found")
    html = compose_preview_html(doc.get("files", []))
    return {"html": html, "name": doc.get("name"), "description": doc.get("description")}


@router.post("/templates/{slug}/use")
async def use_template(slug: str, user: User = Depends(get_current_user)):
    """Clone a template into the user's projects (FREE — pre-cached)."""
    tpl = await builder_templates_col.find_one({"slug": slug})
    if not tpl:
        raise HTTPException(404, "Template not found")
    doc = {
        "user_id": user.id,
        "name": tpl["name"],
        "description": tpl.get("description", ""),
        "prompt": f"[template: {slug}]",
        "files": tpl.get("files", []),
        "share_key": None,
        "github": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    ins = await builder_projects_col.insert_one(doc)
    doc["_id"] = ins.inserted_id
    return {"project": _to_public_project(doc)}


@router.get("/projects")
async def list_projects(
    user: User = Depends(get_current_user),
    kind: Literal["static", "react", "all"] = Query("all"),
):
    query = {"user_id": user.id}
    if kind != "all":
        query.update(_kind_filter(kind))
    cursor = (
        builder_projects_col.find(
            query,
            {"files": 0},  # Don't fetch the large files array
        )
        .sort("updated_at", -1)
        .limit(100)
    )

    items = [_to_public_project(d) async for d in cursor]

    return {"items": items}


@router.post("/projects")
async def create_project(req: CreateProjectRequest, user: User = Depends(get_current_user)):
    # gate=... enforces the usage window right before the LLM call (cache misses only),
    # so an over-window user gets 429 without burning an LLM call or orphaning a project.
    create_key = _price_key(req.kind, "create")
    result = await generate_project(
        user.id, req.prompt,
        gate=lambda: precheck(user.id, create_key),
        kind=req.kind,
    )
    was_cached = result.get("cached", False)
    billing = await spend(user.id, create_key, skip_charge=was_cached, description=f"Builder: {result['name']}")
    doc = {
        "user_id": user.id,
        "name": result["name"],
        "description": result["description"],
        "prompt": req.prompt[:2000],
        "kind": req.kind,
        "files": result["files"],
        "file_count": len(result["files"]),
        "share_key": None,
        "github": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    ins = await builder_projects_col.insert_one(doc)
    doc["_id"] = ins.inserted_id
    await log_event("builder_create", user_id=user.id,
                    payload={"prompt": req.prompt[:400], "cached": was_cached, "kind": req.kind,
                             "name": result["name"], "files": len(result["files"])})
    return {"project": _to_public_project(doc), "cached": was_cached,
            "credits_used": billing["credits_used"], "balance": billing["balance"]}


@router.get("/projects/{project_id}")
async def get_project(project_id: str, user: User = Depends(get_current_user)):
    doc = await _load_project(user.id, project_id)
    return _to_public_project(doc)


@router.patch("/projects/{project_id}/files")
async def save_files(project_id: str, req: SaveFilesRequest, user: User = Depends(get_current_user)):
    """Manual file edits — FREE (no LLM)."""
    doc = await _load_project(user.id, project_id)
    files = [
        {
            "path": (f.get("path") or "")[:200],
            "content": (f.get("content") or "")[:60000],
            "language": (f.get("language") or "html")[:20],
        }
        for f in req.files[:30] if f.get("path")
    ]
    await builder_projects_col.update_one(
        {"_id": ObjectId(project_id)},
        {"$set": {"files": files, "file_count": len(files), "updated_at": now_iso()}},
    )
    return {"ok": True, "files": files}


@router.post("/projects/{project_id}/refine")
async def refine(project_id: str, req: RefineRequest, user: User = Depends(get_current_user)):
    doc = await _load_project(user.id, project_id)
    kind = doc.get("kind", "static")
    refine_key = _price_key(kind, "refine")
    await precheck(user.id, refine_key)  # gate before the LLM call
    new_files = await refine_project(doc.get("files", []), req.instruction,
                                    session_id=f"builder-refine-{project_id}", kind=kind)
    billing = await spend(user.id, refine_key, description="Builder refine")
    await builder_projects_col.update_one(
        {"_id": ObjectId(project_id)},
        {"$set": {"files": new_files, "file_count": len(new_files), "updated_at": now_iso()},
         "$push": {"history": {"instruction": req.instruction[:500], "at": now_iso()}}},
    )
    await log_event("builder_refine", user_id=user.id,
                    payload={"project_id": project_id, "instruction": req.instruction[:400]})
    return {"files": new_files, "credits_used": billing["credits_used"], "balance": billing["balance"]}


@router.delete("/projects/{project_id}")
async def delete_project(project_id: str, user: User = Depends(get_current_user)):
    try:
        await builder_projects_col.delete_one({"_id": ObjectId(project_id), "user_id": user.id})
    except Exception:
        pass
    return {"ok": True}


@router.get("/projects/{project_id}/preview")
async def preview(project_id: str, user: User = Depends(get_current_user)):
    """Return composed single-file HTML for iframe preview (static projects only)."""
    doc = await _load_project(user.id, project_id)
    kind = doc.get("kind", "static")
    if kind != "static":
        # react projects are bundled in the browser; there is nothing to compose here.
        return {"html": "", "kind": kind}
    html = compose_preview_html(doc.get("files", []))
    return {"html": html, "kind": kind}


@router.post("/projects/{project_id}/share")
async def share_project(project_id: str, request: Request, req: ShareRequest = ShareRequest(),
                        user: User = Depends(get_current_user)):
    """Publish preview HTML to S3 and return a shareable signed URL (7-day)."""
    doc = await _load_project(user.id, project_id)
    if doc.get("kind", "static") == "static":
        html = compose_preview_html(doc.get("files", []))
    else:
        if not req.html:
            raise HTTPException(400, "Dynamic projects must send the bundled `html` to share.")
        html = req.html
    if not is_configured():
        # No S3 bucket: keep the shared page in Mongo and serve it from /builder/shared/{token}.
        token = doc.get("share_token") or secrets.token_urlsafe(12)
        await builder_projects_col.update_one(
            {"_id": ObjectId(project_id)},
            {"$set": {"share_token": token, "share_html": html, "updated_at": now_iso()}},
        )
        origin = str(request.headers.get("origin") or "").rstrip("/") or os.environ.get("APP_URL", "").rstrip("/")
        await log_event("builder_share", user_id=user.id, payload={"project_id": project_id, "store": "db"})
        return {"share_url": f"{origin}/api/builder/shared/{token}"}
    key = doc.get("share_key")
    if not key:
        key = await upload_bytes(html.encode("utf-8"), f"builder-{uuid.uuid4().hex}.html", "text/html", folder=f"builder/{user.id}")
    else:
        # Overwrite the existing S3 object so the share URL serves the latest HTML
        await upload_bytes_at_key(key, html.encode("utf-8"), "text/html")
    # Always store key + refresh signed URL
    await builder_projects_col.update_one(
        {"_id": ObjectId(project_id)},
        {"$set": {"share_key": key, "updated_at": now_iso()}},
    )
    url = get_signed_url(key, expires_in=60 * 60 * 24 * 7)
    await log_event("builder_share", user_id=user.id, payload={"project_id": project_id})
    return {"share_url": url}


@router.get("/shared/{token}", include_in_schema=False)
async def shared_page(token: str):
    """Public view of a shared build. Served in a CSP sandbox (scripts allowed, no same-origin
    access) so generated code can never read the viewer's IEMA.ai session."""
    doc = await builder_projects_col.find_one({"share_token": token}, {"share_html": 1})
    if not doc or not doc.get("share_html"):
        raise HTTPException(404, "Shared page not found")
    return HTMLResponse(
        doc["share_html"],
        headers={"Content-Security-Policy": "sandbox allow-scripts allow-forms allow-popups allow-modals",
                 "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"},
    )


async def _github_token(user_id: str) -> Optional[str]:
    """OAuth token from the user's GitHub connector (preferred); falls back to a PAT saved earlier."""
    from services.mcp.oauth_service import get_valid_access_token
    try:
        return await get_valid_access_token(user_id, "github")
    except Exception:
        pass
    from db import users_col
    u = await users_col.find_one({"_id": ObjectId(user_id)}, {"github_pat": 1})
    enc = (u or {}).get("github_pat")
    if enc:
        try:
            return _decrypt(enc)
        except Exception:
            return None
    return None


_GH_HEADERS = {"Accept": "application/vnd.github+json", "User-Agent": "iema-ai-builder"}
_OLD_DEFAULT_MSG = "IEMA.ai Builder push"


def _commit_type(text: str) -> str:
    t = text.lower()
    if re.match(r"\s*(please\s+)?(add|create|implement|build|support|allow|include|introduce|make a|new)\b", t):
        return "feat"
    if re.search(r"\b(fix|bug|error|broken|crash|issue|wrong)\b", t):
        return "fix"
    if re.search(r"\b(refactor|rename|clean ?up|restructure|simplif)", t):
        return "refactor"
    if re.search(r"\b(readme|docs?|comment)\b", t):
        return "docs"
    if re.search(r"\b(style|color|colour|theme|font|layout|spacing|dark|light|responsive|css|design|animation|look)\b", t):
        return "style"
    return "feat"


def _one_line(text: str, limit: int = 60) -> str:
    t = re.sub(r"\s+", " ", (text or "")).strip().rstrip(".!?")
    if len(t) > limit:
        t = t[:limit].rsplit(" ", 1)[0].rstrip(",;:-") + "…"
    return (t[:1].lower() + t[1:]) if t else t


def build_commit_message(doc: dict, first_push: bool, pending: list) -> str:
    """Conventional-commit style message from the project's own history (no LLM call)."""
    name = (doc.get("name") or "project").strip()
    if first_push or not (doc.get("github") or {}).get("last_pushed_at"):
        subject = f"feat: initial version of {name}"[:72]
        body = f"Generated with IEMA.ai Builder from the prompt:\n\n{(doc.get('prompt') or '')[:300].strip()}"
        if pending:
            body += "\n\nRefinements included:\n" + "\n".join(f"- {_one_line(h['instruction'], 100)}" for h in pending[-10:])
        return f"{subject}\n\n{body}".strip()
    if not pending:
        return f"chore: sync {name} from IEMA.ai Builder"
    latest = pending[-1]["instruction"]
    subject = f"{_commit_type(latest)}: {_one_line(latest)}"
    if len(pending) > 1:
        subject = f"{_commit_type(latest)}: {_one_line(latest, 48)} (+{len(pending) - 1} more)"
    body = "\n".join(f"- {_one_line(h['instruction'], 100)}" for h in pending[-10:])
    return f"{subject}\n\nChanges since the last push:\n{body}"


async def _single_commit(http, repo: str, files: list, message: str) -> Optional[dict]:
    """Commit every file in ONE commit via the Git Data API. Returns None if the repo has no
    commits yet (the caller falls back to the Contents API)."""
    base = f"https://api.github.com/repos/{repo}"
    info = await http.get(base)
    branch = (info.json() or {}).get("default_branch", "main") if info.status_code == 200 else "main"
    ref = await http.get(f"{base}/git/ref/heads/{branch}")
    if ref.status_code != 200:
        return None
    head = ref.json()["object"]["sha"]
    commit = await http.get(f"{base}/git/commits/{head}")
    base_tree = commit.json()["tree"]["sha"]
    tree = []
    for f in files:
        blob = await http.post(f"{base}/git/blobs", json={
            "content": base64.b64encode(f["content"].encode("utf-8")).decode("ascii"), "encoding": "base64"})
        if blob.status_code not in (200, 201):
            raise HTTPException(502, f"GitHub rejected a file upload ({blob.status_code}).")
        tree.append({"path": f["path"].lstrip("/"), "mode": "100644", "type": "blob", "sha": blob.json()["sha"]})
    new_tree = await http.post(f"{base}/git/trees", json={"base_tree": base_tree, "tree": tree})
    if new_tree.status_code not in (200, 201):
        raise HTTPException(502, f"GitHub could not build the commit ({new_tree.status_code}).")
    if new_tree.json()["sha"] == base_tree:
        return {"unchanged": True, "paths": [t["path"] for t in tree]}
    new_commit = await http.post(f"{base}/git/commits", json={
        "message": message, "tree": new_tree.json()["sha"], "parents": [head]})
    if new_commit.status_code not in (200, 201):
        raise HTTPException(502, f"GitHub could not create the commit ({new_commit.status_code}).")
    upd = await http.patch(f"{base}/git/refs/heads/{branch}", json={"sha": new_commit.json()["sha"]})
    if upd.status_code != 200:
        raise HTTPException(502, f"GitHub could not update {branch} ({upd.status_code}).")
    return {"unchanged": False, "paths": [t["path"] for t in tree], "commit": new_commit.json()["sha"]}


@router.post("/projects/{project_id}/github/push")
async def github_push(project_id: str, req: GithubPushRequest, user: User = Depends(get_current_user)):
    """Push all project files to GitHub in a single commit, using the user's connected GitHub
    account (OAuth). `repo` may be a bare name (created under the user's account if missing)
    or `owner/repo`. The commit message is generated from the project's history unless given."""
    doc = await _load_project(user.id, project_id)
    token = await _github_token(user.id)
    if not token:
        raise HTTPException(400, "Connect your GitHub account first.")
    headers = {**_GH_HEADERS, "Authorization": f"Bearer {token}"}
    repo_in = (req.repo or "").strip().strip("/")
    if not repo_in:
        raise HTTPException(400, "Enter a repository name.")

    gh = doc.get("github") or {}
    history = doc.get("history") or []
    pending = history[int(gh.get("history_len", 0)):] if gh.get("last_pushed_at") else history
    custom = (req.commit_message or "").strip()
    message = custom if custom and custom != _OLD_DEFAULT_MSG else build_commit_message(doc, not gh.get("last_pushed_at"), pending)

    pushed, errors, created, unchanged = [], [], False, False
    async with httpx.AsyncClient(timeout=30, headers=headers) as http:
        if "/" in repo_in:
            repo = repo_in
        else:
            me = await http.get("https://api.github.com/user")
            if me.status_code != 200:
                raise HTTPException(400, "GitHub connection is not valid anymore. Please reconnect GitHub.")
            repo = f"{me.json()['login']}/{repo_in}"
        chk = await http.get(f"https://api.github.com/repos/{repo}")
        if chk.status_code == 404:
            owner, name = repo.split("/", 1)
            me = await http.get("https://api.github.com/user")
            payload = {"name": name, "private": bool(req.private), "auto_init": True,
                       "description": f"Built with IEMA.ai: {doc.get('name', '')}"[:200]}
            if me.status_code == 200 and me.json().get("login", "").lower() == owner.lower():
                mk = await http.post("https://api.github.com/user/repos", json=payload)
            else:
                mk = await http.post(f"https://api.github.com/orgs/{owner}/repos", json=payload)
            if mk.status_code not in (200, 201):
                raise HTTPException(400, f"Could not create repository: {mk.status_code} {mk.text[:140]}")
            created = True
        elif chk.status_code != 200:
            raise HTTPException(400, f"GitHub says {chk.status_code} for {repo}. Check the repository name and your access.")

        files = doc.get("files", [])
        res = await _single_commit(http, repo, files, message)
        if res is not None:
            unchanged = res["unchanged"]
            pushed = [] if unchanged else res["paths"]
        else:
            # Repository has no commits yet: the Contents API creates the first commit(s).
            for f in files:
                path = f["path"].lstrip("/")
                api_url = f"https://api.github.com/repos/{repo}/contents/{path}"
                put = await http.put(api_url, json={
                    "message": message,
                    "content": base64.b64encode(f["content"].encode("utf-8")).decode("ascii")})
                if put.status_code in (200, 201):
                    pushed.append(path)
                else:
                    errors.append({"path": path, "error": f"{put.status_code}: {put.text[:120]}"})

    await builder_projects_col.update_one(
        {"_id": ObjectId(project_id)},
        {"$set": {"github": {"repo": repo, "last_pushed_at": now_iso(), "history_len": len(history)},
                  "updated_at": now_iso()}},
    )
    await log_event("builder_github_push", user_id=user.id,
                    payload={"project_id": project_id, "repo": repo, "created": created,
                             "pushed": len(pushed), "errors": len(errors), "unchanged": unchanged})
    return {"pushed": pushed, "errors": errors, "repo": repo, "created": created, "unchanged": unchanged,
            "commit_message": None if unchanged else message.split("\n", 1)[0], "repo_url": f"https://github.com/{repo}"}


@router.get("/github/status")
async def github_status(user: User = Depends(get_current_user)):
    token = await _github_token(user.id)
    if not token:
        return {"connected": False}
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.get("https://api.github.com/user", headers={**_GH_HEADERS, "Authorization": f"Bearer {token}"})
        if r.status_code == 200:
            return {"connected": True, "login": r.json().get("login")}
    except Exception:
        pass
    return {"connected": False}


@router.delete("/github/disconnect")
async def github_disconnect(user: User = Depends(get_current_user)):
    from db import users_col
    from services.mcp.oauth_service import mcp_connections_col
    await users_col.update_one({"_id": ObjectId(user.id)}, {"$unset": {"github_pat": ""}})
    await mcp_connections_col.delete_one({"user_id": user.id, "connector_id": "github"})
    return {"ok": True}
