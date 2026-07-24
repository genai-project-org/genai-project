"""File upload routes."""
import os
import logging
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from auth import get_current_user
from models import User
from services.storage_service import upload_bytes, get_signed_url, is_configured

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/uploads", tags=["uploads"])

MAX_SIZE = 8 * 1024 * 1024  # 8 MB
ALLOWED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


@router.post("/image")
async def upload_image(file: UploadFile = File(...), user: User = Depends(get_current_user)):
    if not is_configured():
        raise HTTPException(500, "Storage not configured")
    if file.content_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(400, "Unsupported image type. Use PNG, JPEG, WEBP or GIF.")
    # Read up to MAX_SIZE+1 to detect oversize files without buffering entire hostile upload
    data = await file.read(MAX_SIZE + 1)
    if len(data) > MAX_SIZE:
        raise HTTPException(400, "File too large. Max 8MB.")
    if len(data) == 0:
        raise HTTPException(400, "Empty file")
    key = await upload_bytes(data, file.filename or "image.png", file.content_type, folder=f"chat/{user.id}")
    url = get_signed_url(key, expires_in=60 * 60 * 24)  # 24h
    return {
        "key": key,
        "url": url,
        "content_type": file.content_type,
        "size": len(data),
        "filename": file.filename,
    }
