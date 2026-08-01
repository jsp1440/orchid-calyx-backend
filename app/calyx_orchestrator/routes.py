from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import verify_owner_or_api_key

from .models import CalyxJob
from .service import CalyxOrchestrator, READ_ONLY_JOB_TYPES

router = APIRouter(prefix="/orchestrator", tags=["calyx-orchestrator"])

DbDependency = Annotated[Session, Depends(get_db)]
AuthDependency = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_type: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=240)
    request: str = Field(min_length=1, max_length=12000)
    priority: int = Field(default=100, ge=1, le=1000)
    dependency_job_id: str | None = None


def _owner(auth: dict[str, Any]) -> str:
    owner = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not owner:
        raise HTTPException(401, detail={"code": "AUTHENTICATED_OWNER_REQUIRED"})
    return owner


@router.get("/status")
def status(auth: AuthDependency, db: DbDependency) -> dict:
    return CalyxOrchestrator(db).status(owner=_owner(auth))


@router.post("/seed-overnight", status_code=201)
def seed_overnight(auth: AuthDependency, db: DbDependency) -> dict:
    jobs = CalyxOrchestrator(db).seed_overnight(owner=_owner(auth))
    return {
        "mode": "preproduction",
        "activated": False,
        "jobs": [CalyxOrchestrator.job_dict(job) for job in jobs],
        "message": "Jobs are durable and queued; a separately enabled preproduction worker is required to execute them.",
    }


@router.post("/jobs", status_code=201)
def create_job(payload: JobRequest, auth: AuthDependency, db: DbDependency) -> dict:
    if payload.job_type not in READ_ONLY_JOB_TYPES:
        raise HTTPException(422, detail={"code": "JOB_TYPE_NOT_ALLOWED"})
    if payload.dependency_job_id and db.get(CalyxJob, payload.dependency_job_id) is None:
        raise HTTPException(404, detail={"code": "DEPENDENCY_JOB_NOT_FOUND"})
    job = CalyxJob(
        job_type=payload.job_type,
        title=payload.title,
        request_text=payload.request,
        owner=_owner(auth),
        priority=payload.priority,
        dependency_job_id=payload.dependency_job_id,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return CalyxOrchestrator.job_dict(job)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, auth: AuthDependency, db: DbDependency) -> dict:
    job = db.get(CalyxJob, job_id)
    if job is None or job.owner != _owner(auth):
        raise HTTPException(404, detail={"code": "JOB_NOT_FOUND"})
    if job.status not in {"queued", "blocked_approval"}:
        raise HTTPException(409, detail={"code": "JOB_NOT_CANCELLABLE"})
    job.status = "cancelled"
    db.commit()
    db.refresh(job)
    return CalyxOrchestrator.job_dict(job)
