from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import verify_owner_or_api_key

from .autonomy_routes import router as autonomy_router
from .models import CalyxJob
from .operations import operational_status, renew_lease, seed_approved_tasks
from .portfolio_routes import router as portfolio_router
from .program_routes import router as program_router
from .sandbox_supervisor_routes import router as sandbox_supervisor_router
from .service import (
    AUTONOMY_POLICY_CLASSES,
    READ_ONLY_JOB_TYPES,
    CalyxOrchestrator,
)

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
    policy_class: str = Field(default="read_only_research", max_length=40)
    max_attempts: int = Field(default=3, ge=1, le=10)
    deadline_at: datetime | None = None


class HeartbeatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    worker_id: str = Field(min_length=1, max_length=240)
    lease_token: str = Field(min_length=1, max_length=240)
    lease_seconds: int = Field(default=300, ge=60, le=3600)


def _owner(auth: dict[str, Any]) -> str:
    owner = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not owner:
        raise HTTPException(401, detail={"code": "AUTHENTICATED_OWNER_REQUIRED"})
    return owner


@router.get("/status")
def status(auth: AuthDependency, db: DbDependency) -> dict:
    return operational_status(db, owner=_owner(auth))


@router.post("/seed-overnight", status_code=201)
def seed_overnight(auth: AuthDependency, db: DbDependency) -> dict:
    jobs = seed_approved_tasks(db, owner=_owner(auth))
    return {
        "mode": "preproduction",
        "activated": False,
        "provider": "reviewed-static-v2",
        "jobs": [CalyxOrchestrator.job_dict(job) for job in jobs],
        "message": "Reviewed read-only jobs are durable and queued; a separately enabled preproduction worker is required to execute them.",
    }


@router.post("/jobs/{job_id}/heartbeat")
def heartbeat(
    job_id: str,
    payload: HeartbeatRequest,
    auth: AuthDependency,
    db: DbDependency,
) -> dict:
    try:
        return renew_lease(
            db,
            owner=_owner(auth),
            job_id=job_id,
            worker_id=payload.worker_id,
            lease_token=payload.lease_token,
            lease_seconds=payload.lease_seconds,
        )
    except PermissionError as exc:
        raise HTTPException(409, detail={"code": str(exc)}) from exc


@router.post("/jobs", status_code=201)
def create_job(payload: JobRequest, auth: AuthDependency, db: DbDependency) -> dict:
    if payload.job_type not in READ_ONLY_JOB_TYPES:
        raise HTTPException(422, detail={"code": "JOB_TYPE_NOT_ALLOWED"})
    if payload.policy_class not in AUTONOMY_POLICY_CLASSES:
        raise HTTPException(422, detail={"code": "POLICY_CLASS_NOT_ALLOWED"})
    owner = _owner(auth)
    if payload.dependency_job_id:
        dependency = db.get(CalyxJob, payload.dependency_job_id)
        if dependency is None or dependency.owner != owner:
            raise HTTPException(404, detail={"code": "DEPENDENCY_JOB_NOT_FOUND"})
    job = CalyxJob(
        job_type=payload.job_type,
        title=payload.title,
        request_text=payload.request,
        owner=owner,
        priority=payload.priority,
        dependency_job_id=payload.dependency_job_id,
        policy_class=payload.policy_class,
        max_attempts=payload.max_attempts,
        deadline_at=payload.deadline_at,
        approval_required=payload.policy_class in {"review_required", "owner_only"},
        approval_class=payload.policy_class if payload.policy_class in {"review_required", "owner_only"} else None,
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
    job.next_attempt_at = None
    db.commit()
    db.refresh(job)
    return CalyxOrchestrator.job_dict(job)


@router.post("/jobs/{job_id}/requeue")
def requeue_dead_letter(job_id: str, auth: AuthDependency, db: DbDependency) -> dict:
    try:
        job = CalyxOrchestrator(db).requeue_dead_letter(owner=_owner(auth), job_id=job_id)
    except LookupError as exc:
        raise HTTPException(404, detail={"code": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(409, detail={"code": str(exc)}) from exc
    return CalyxOrchestrator.job_dict(job)


router.include_router(program_router)
router.include_router(autonomy_router)
router.include_router(portfolio_router)
router.include_router(sandbox_supervisor_router)
