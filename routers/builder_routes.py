"""Code Builder routes — projects, refine, GitHub push, S3 share."""
import os
import uuid
import base64
import hashlib
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
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
from services.pricing_engine import spend
from services.storage_service import upload_bytes, upload_bytes_at_key, get_signed_url, is_configured
from services.data_lake import log_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/builder", tags=["builder"])

CREDIT_BUILDER_CREATE = float(os.environ.get("CREDIT_BUILDER_CREATE", "15"))
CREDIT_BUILDER_REFINE = float(os.environ.get("CREDIT_BUILDER_REFINE", "8"))


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


class RefineRequest(BaseModel):
    instruction: str = Field(min_length=3, max_length=1000)


class SaveFilesRequest(BaseModel):
    files: List[dict]


class GithubPushRequest(BaseModel):
    pat: Optional[str] = None  # If provided, is stored (encrypted). Otherwise reuses saved.
    repo: str = Field(min_length=3, max_length=140)  # "owner/repo"
    commit_message: str = "IEMA.ai Builder push"
    save_pat: bool = True


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
async def list_projects(user: User = Depends(get_current_user)):
    cursor = (
        builder_projects_col.find(
            {"user_id": user.id},
            {"files": 0},  # Don't fetch the large files array
        )
        .sort("updated_at", -1)
        .limit(100)
    )

    items = [_to_public_project(d) async for d in cursor]

    return {"items": items}


@router.post("/projects")
async def create_project(req: CreateProjectRequest, user: User = Depends(get_current_user)):
    result = await generate_project(user.id, req.prompt)
    doc = {
        "user_id": user.id,
        "name": result["name"],
        "description": result["description"],
        "prompt": req.prompt[:2000],
        "files": result["files"],
        "file_count": len(result["files"]),
        "share_key": None,
        "github": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    ins = await builder_projects_col.insert_one(doc)
    doc["_id"] = ins.inserted_id
    was_cached = result.get("cached", False)
    billing = await spend(user.id, "builder_create", skip_charge=was_cached, description=f"Builder: {result['name']}")
    await log_event("builder_create", user_id=user.id,
                    payload={"prompt": req.prompt[:400], "cached": was_cached,
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
    new_files = await refine_project(doc.get("files", []), req.instruction, session_id=f"builder-refine-{project_id}")
    await builder_projects_col.update_one(
        {"_id": ObjectId(project_id)},
        {"$set": {"files": new_files, "file_count": len(new_files), "updated_at": now_iso()}},
    )
    billing = await spend(user.id, "builder_refine", description="Builder refine")
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
    """Return composed single-file HTML for iframe preview."""
    doc = await _load_project(user.id, project_id)
    html = compose_preview_html(doc.get("files", []))
    return {"html": html}


@router.post("/projects/{project_id}/share")
async def share_project(project_id: str, user: User = Depends(get_current_user)):
    """Publish preview HTML to S3 and return a shareable signed URL (7-day)."""
    if not is_configured():
        raise HTTPException(500, "Storage not configured")
    doc = await _load_project(user.id, project_id)
    html = compose_preview_html(doc.get("files", []))
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


@router.post("/projects/{project_id}/github/push")
async def github_push(project_id: str, req: GithubPushRequest, user: User = Depends(get_current_user)):
    """Push all project files to GitHub. PAT may be supplied per-call and saved encrypted per user."""
    doc = await _load_project(user.id, project_id)
    # Resolve PAT
    pat = req.pat
    if not pat:
        # Load from user record
        from db import users_col
        u = await users_col.find_one({"_id": ObjectId(user.id)}, {"github_pat": 1})
        enc = (u or {}).get("github_pat")
        if not enc:
            raise HTTPException(400, "No GitHub PAT saved. Provide one in `pat` and set save_pat=true.")
        try:
            pat = _decrypt(enc)
        except Exception:
            raise HTTPException(400, "Stored PAT could not be decrypted. Please re-enter.")

    if req.save_pat and req.pat:
        # Validate PAT lightly before persisting so /github/status never lies.
        async with httpx.AsyncClient(timeout=10) as http_check:
            r_check = await http_check.get(
                "https://api.github.com/user",
                headers={"Authorization": f"Bearer {req.pat}", "Accept": "application/vnd.github+json",
                         "User-Agent": "iema-ai-builder"},
            )
            if r_check.status_code == 200:
                from db import users_col
                await users_col.update_one(
                    {"_id": ObjectId(user.id)},
                    {"$set": {"github_pat": _encrypt(req.pat)}},
                )
            else:
                raise HTTPException(400, f"GitHub rejected PAT ({r_check.status_code}). Not saved.")

    if "/" not in req.repo:
        raise HTTPException(400, "repo must be in `owner/repo` form")

    headers = {"Authorization": f"Bearer {pat}", "Accept": "application/vnd.github+json", "User-Agent": "iema-ai-builder"}
    pushed = []
    errors = []
    async with httpx.AsyncClient(timeout=30, headers=headers) as http:
        for f in doc.get("files", []):
            path = f["path"].lstrip("/")
            api_url = f"https://api.github.com/repos/{req.repo}/contents/{path}"
            # Look up existing sha
            sha = None
            r = await http.get(api_url)
            if r.status_code == 200:
                sha = r.json().get("sha")
            elif r.status_code not in (404,):
                errors.append({"path": path, "error": f"lookup {r.status_code}"})
                continue
            payload = {
                "message": req.commit_message,
                "content": base64.b64encode(f["content"].encode("utf-8")).decode("ascii"),
            }
            if sha:
                payload["sha"] = sha
            put = await http.put(api_url, json=payload)
            if put.status_code in (200, 201):
                pushed.append(path)
            else:
                errors.append({"path": path, "error": f"{put.status_code}: {put.text[:120]}"})

    await builder_projects_col.update_one(
        {"_id": ObjectId(project_id)},
        {"$set": {"github": {"repo": req.repo, "last_pushed_at": now_iso()}, "updated_at": now_iso()}},
    )
    await log_event("builder_github_push", user_id=user.id,
                    payload={"project_id": project_id, "repo": req.repo,
                             "pushed": len(pushed), "errors": len(errors)})
    return {"pushed": pushed, "errors": errors, "repo_url": f"https://github.com/{req.repo}"}


@router.get("/github/status")
async def github_status(user: User = Depends(get_current_user)):
    from db import users_col
    u = await users_col.find_one({"_id": ObjectId(user.id)}, {"github_pat": 1})
    return {"connected": bool((u or {}).get("github_pat"))}


@router.delete("/github/disconnect")
async def github_disconnect(user: User = Depends(get_current_user)):
    from db import users_col
    await users_col.update_one({"_id": ObjectId(user.id)}, {"$unset": {"github_pat": ""}})
    return {"ok": True}
