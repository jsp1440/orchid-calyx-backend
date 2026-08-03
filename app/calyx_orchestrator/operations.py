from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .approved_tasks import task_profile, task_provider_status
from .models import CalyxJob, utcnow
from .service import CalyxOrchestrator


def seed_approved_tasks(db: Session, *, owner: str) -> list[CalyxJob]:
    jobs: list[CalyxJob] = []
    for task in task_profile():
        existing = db.scalar(
            select(CalyxJob).where(
                CalyxJob.owner == owner,
                CalyxJob.title == task.title,
                CalyxJob.status.in_(("queued", "running")),
            )
        )
        if existing:
            jobs.append(existing)
            continue
        job = CalyxJob(
            job_type=task.job_type,
            title=task.title,
            request_text=task.request_text,
            owner=owner,
            priority=task.priority,
        )
        db.add(job)
        jobs.append(job)
    db.commit()
    for job in jobs:
        db.refresh(job)
    return jobs


def renew_lease(
    db: Session,
    *,
    owner: str,
    job_id: str,
    worker_id: str,
    lease_token: str,
    lease_seconds: int,
) -> dict:
    now = utcnow()
    updated = (
        db.query(CalyxJob)
        .filter(
            CalyxJob.job_id == job_id,
            CalyxJob.owner == owner,
            CalyxJob.status == "running",
            CalyxJob.lease_owner == worker_id,
            CalyxJob.lease_token == lease_token,
        )
        .update(
            {CalyxJob.lease_expires_at: now + timedelta(seconds=lease_seconds)},
            synchronize_session=False,
        )
    )
    if not updated:
        db.rollback()
        raise PermissionError("STALE_WORKER_LEASE")
    db.commit()
    job = db.get(CalyxJob, job_id)
    if job is None:
        raise LookupError("JOB_NOT_FOUND")
    return {
        "job_id": job.job_id,
        "worker_id": worker_id,
        "lease_expires_at": job.lease_expires_at.isoformat() if job.lease_expires_at else None,
        "renewed": True,
    }


def operational_status(db: Session, *, owner: str) -> dict:
    base = CalyxOrchestrator(db).status(owner=owner)
    provider = task_provider_status()
    queued_priorities = [
        {"job_id": job[0], "priority": job[1], "title": job[2]}
        for job in db.execute(
            select(CalyxJob.job_id, CalyxJob.priority, CalyxJob.title)
            .where(CalyxJob.owner == owner, CalyxJob.status == "queued")
            .order_by(CalyxJob.priority.asc(), CalyxJob.created_at.asc())
            .limit(25)
        ).all()
    ]
    return {
        **base,
        "task_provider": provider,
        "priority_queue": queued_priorities,
        "single_worker_required": True,
        "lease_heartbeat_supported": True,
        "production_activation": False,
    }
