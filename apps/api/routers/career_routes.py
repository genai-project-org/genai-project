"""Career Intelligence routes."""
import os
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from auth import get_current_user
from models import User
from services.career_service import search_jobs, get_or_generate_learning_path
from services.pricing_engine import spend
from services.data_lake import log_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/career", tags=["career"])


class JobSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=120)
    location: str = Field(default="", max_length=120)
    page: int = Field(default=1, ge=1, le=10)


class LearningPathRequest(BaseModel):
    role: str = Field(min_length=2, max_length=120)
    skills: List[str] = Field(default_factory=list, max_length=20)


@router.post("/jobs")
async def jobs_search(req: JobSearchRequest, user: User = Depends(get_current_user)):
    data = await search_jobs(req.query, req.location, req.page)
    await log_event("career_job_search", user_id=user.id,
                    payload={"q": req.query, "loc": req.location, "count": data.get("count", 0),
                             "source": data.get("source")})
    return data


@router.post("/learning-path")
async def learning_path(req: LearningPathRequest, user: User = Depends(get_current_user)):
    result = await get_or_generate_learning_path(req.role, req.skills, user_id=user.id)
    was_fresh = not result.get("cached", False)
    billing = await spend(
        user.id, "career_learning_path",
        skip_charge=not was_fresh,
        description="Learning path generation",
    )
    result["credits_used"] = billing["credits_used"]
    result["balance"] = billing["balance"]
    await log_event("career_learning_path", user_id=user.id,
                    payload={"role": req.role, "skills": req.skills, "cached": result.get("cached", False)})
    return result
