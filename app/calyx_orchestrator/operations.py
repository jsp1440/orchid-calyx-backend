from __future__ import annotations

from collections import Counter
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .approved_tasks import task_profile, task_provider_status
from .models import CalyxJob, utcnow
from .persisted_scheduler import persisted_schedule_status
from .program_models import CalyxProgram, CalyxProgramJob
from .service import CalyxOrchestrator

GLOBAL_ENGINEERING_SLOT_LIMIT = 6
REPOSITORY_ENGINEERING_SLOT_LIMIT = 2


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


def _engineering_program_status(db: Session, *, owner: str) -> dict:
    programs = db.scalars(
        select(CalyxProgram)
        .where(CalyxProgram.owner == owner)
        .order_by(CalyxProgram.created_at.desc())
    ).all()
    program_ids = [program.program_id for program in programs]
    jobs: list[CalyxProgramJob] = []
    if program_ids:
        jobs = db.scalars(
            select(CalyxProgramJob)
            .where(CalyxProgramJob.program_id.in_(program_ids))
            .order_by(CalyxProgramJob.created_at.asc())
        ).all()

    active = [job for job in jobs if job.status == "running"]
    queued = [job for job in jobs if job.status == "queued"]
    waiting = [job for job in jobs if job.status == "waiting"]
    blocked = [job for job in jobs if job.status == "blocked"]
    repository_usage = Counter(job.repository for job in active)

    blockers = [
        {
            "program_id": job.program_id,
            "job_key": job.job_key,
            "role_key": job.role_key,
            "repository": job.repository,
            "branch": job.branch,
            "blocker": job.blocker or "UNSPECIFIED_BLOCKER",
            "human_action": job.human_action or "Review the authoritative program job evidence.",
        }
        for job in blocked
    ]

    return {
        "program_counts": dict(Counter(program.status for program in programs)),
        "job_counts": dict(Counter(job.status for job in jobs)),
        "active_slots": {
            "used": len(active),
            "available": max(0, GLOBAL_ENGINEERING_SLOT_LIMIT - len(active)),
            "limit": GLOBAL_ENGINEERING_SLOT_LIMIT,
        },
        "repository_slots": [
            {
                "repository": repository,
                "used": count,
                "available": max(0, REPOSITORY_ENGINEERING_SLOT_LIMIT - count),
                "limit": REPOSITORY_ENGINEERING_SLOT_LIMIT,
            }
            for repository, count in sorted(repository_usage.items())
        ],
        "active_jobs": [
            {
                "program_id": job.program_id,
                "job_key": job.job_key,
                "role_key": job.role_key,
                "repository": job.repository,
                "branch": job.branch,
                "mutating": job.mutating,
                "orchestrator_job_id": job.orchestrator_job_id,
            }
            for job in active
        ],
        "queued_jobs": len(queued),
        "dependency_waiting_jobs": len(waiting),
        "blockers": blockers,
        "exact_human_actions": sorted(
            {item["human_action"] for item in blockers if item.get("human_action")}
        ),
        "schedule": persisted_schedule_status(db, owner=owner),
        "recent_programs": [
            {
                "program_id": program.program_id,
                "title": program.title,
                "status": program.status,
                "paused": program.paused,
                "max_active_jobs": program.max_active_jobs,
                "created_at": program.created_at.isoformat() if program.created_at else None,
                "completed_at": program.completed_at.isoformat() if program.completed_at else None,
            }
            for program in programs[:25]
        ],
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
        "engineering_programs": _engineering_program_status(db, owner=owner),
        "single_worker_required": False,
        "lease_heartbeat_supported": True,
        "production_activation": False,
    }
