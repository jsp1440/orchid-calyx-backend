from __future__ import annotations

import hashlib
import json
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from app.calyx_agent.service import CalyxAgentService

from .models import CalyxFinding, CalyxJob, utcnow

READ_ONLY_JOB_TYPES = {
    "capability_inventory",
    "brain_audit",
    "mission_control_audit",
    "journalism_readiness",
    "archive_readiness",
    "harvester_readiness",
    "deployment_readiness",
    "build_specification",
}

OVERNIGHT_PROFILE = (
    (10, "capability_inventory", "Inventory merged Continuum capabilities", "Audit current capabilities, open work, and readiness gaps."),
    (20, "brain_audit", "Audit Brain and Knowledge Graph", "Audit the Brain, Knowledge Graph, reasoning, evidence, and publication chain."),
    (30, "mission_control_audit", "Audit Mission Control", "Inspect Mission Control observability, failures, blocked approvals, and missing status surfaces."),
    (40, "journalism_readiness", "Audit Calyx journalism", "Inspect journalism evidence, persistence, generation, and publication readiness."),
    (50, "archive_readiness", "Audit institutional archive", "Inspect archive durability, ingestion, provenance, and operational readiness."),
    (60, "harvester_readiness", "Audit harvesters", "Inspect harvester health, coverage, duplication, scheduling, and missing connectors."),
    (70, "deployment_readiness", "Audit release readiness", "Inspect migrations, configuration, tests, worker readiness, and release blockers."),
)


class CalyxOrchestrator:
    def __init__(self, db: Session, agent: CalyxAgentService | None = None) -> None:
        self.db = db
        self.agent = agent or CalyxAgentService()

    def seed_overnight(self, *, owner: str) -> list[CalyxJob]:
        jobs: list[CalyxJob] = []
        for priority, job_type, title, request_text in OVERNIGHT_PROFILE:
            existing = self.db.scalar(
                select(CalyxJob).where(
                    CalyxJob.owner == owner,
                    CalyxJob.job_type == job_type,
                    CalyxJob.status.in_(("queued", "running")),
                )
            )
            if existing:
                jobs.append(existing)
                continue
            job = CalyxJob(
                job_type=job_type,
                title=title,
                request_text=request_text,
                owner=owner,
                priority=priority,
            )
            self.db.add(job)
            jobs.append(job)
        self.db.commit()
        for job in jobs:
            self.db.refresh(job)
        return jobs

    def claim(self, *, worker_id: str, lease_seconds: int = 180) -> CalyxJob | None:
        now = utcnow()
        claimable = or_(
            CalyxJob.status == "queued",
            and_(
                CalyxJob.status == "running",
                CalyxJob.lease_expires_at.is_not(None),
                CalyxJob.lease_expires_at <= now,
            ),
        )
        candidates = self.db.scalars(
            select(CalyxJob)
            .where(
                claimable,
                CalyxJob.approval_required.is_(False),
                CalyxJob.attempt_count < CalyxJob.max_attempts,
                or_(
                    CalyxJob.dependency_job_id.is_(None),
                    CalyxJob.dependency_job_id.in_(
                        select(CalyxJob.job_id).where(CalyxJob.status == "completed")
                    ),
                ),
            )
            .order_by(CalyxJob.priority.asc(), CalyxJob.created_at.asc())
            .limit(10)
        ).all()
        for job in candidates:
            token = str(uuid4())
            row_claimable = or_(
                CalyxJob.status == "queued",
                and_(
                    CalyxJob.status == "running",
                    CalyxJob.lease_expires_at.is_not(None),
                    CalyxJob.lease_expires_at <= now,
                ),
            )
            updated = (
                self.db.query(CalyxJob)
                .filter(
                    and_(
                        CalyxJob.job_id == job.job_id,
                        row_claimable,
                        CalyxJob.attempt_count < CalyxJob.max_attempts,
                    )
                )
                .update(
                    {
                        CalyxJob.status: "running",
                        CalyxJob.lease_owner: worker_id,
                        CalyxJob.lease_token: token,
                        CalyxJob.lease_expires_at: now + timedelta(seconds=lease_seconds),
                        CalyxJob.attempt_count: CalyxJob.attempt_count + 1,
                        CalyxJob.error_code: None,
                    },
                    synchronize_session=False,
                )
            )
            if updated:
                self.db.commit()
                return self.db.get(CalyxJob, job.job_id)
            self.db.rollback()
        return None

    def execute(self, job: CalyxJob, *, worker_id: str, lease_token: str) -> CalyxJob:
        if job.job_type not in READ_ONLY_JOB_TYPES:
            return self._fail(job, worker_id, lease_token, "JOB_TYPE_NOT_ALLOWED")
        if job.lease_owner != worker_id or job.lease_token != lease_token:
            raise PermissionError("STALE_WORKER_LEASE")
        response = self.agent.handle(
            actor=job.owner,
            request_text=job.request_text,
            use_provider=True,
        )
        payload = response.to_dict()
        if payload.get("approval_required"):
            job.status = "blocked_approval"
            job.approval_required = True
            job.approval_class = payload.get("steps", [{}])[0].get("action_class")
        else:
            job.status = "completed"
            job.completed_at = utcnow()
            self._record_findings(job, payload)
        job.result_json = json.dumps(payload, sort_keys=True, default=str)
        job.lease_owner = None
        job.lease_token = None
        job.lease_expires_at = None
        self.db.commit()
        self.db.refresh(job)
        return job

    def _record_findings(self, job: CalyxJob, payload: dict) -> None:
        warnings = payload.get("uncertainties") or []
        if not warnings:
            warnings = ["No critical failure was reported; review prepared recommendations and evidence."]
        for warning in warnings:
            fingerprint = hashlib.sha256(f"{job.job_type}:{warning}".encode()).hexdigest()
            existing = self.db.scalar(select(CalyxFinding).where(CalyxFinding.fingerprint == fingerprint))
            if existing:
                existing.updated_at = utcnow()
                existing.status = "active"
                continue
            self.db.add(
                CalyxFinding(
                    job_id=job.job_id,
                    fingerprint=fingerprint,
                    subsystem=job.job_type,
                    severity="medium",
                    title=job.title,
                    summary=str(warning),
                    recommendation="Review the governed Calyx result and prepare a bounded follow-up build.",
                    provenance_json=json.dumps(
                        {
                            "request_id": payload.get("request_id"),
                            "provider": payload.get("provider"),
                            "provider_model": payload.get("provider_model"),
                            "tool_results": payload.get("tool_results", []),
                        },
                        sort_keys=True,
                        default=str,
                    ),
                )
            )

    def _fail(self, job: CalyxJob, worker_id: str, lease_token: str, code: str) -> CalyxJob:
        if job.lease_owner != worker_id or job.lease_token != lease_token:
            raise PermissionError("STALE_WORKER_LEASE")
        job.error_code = code
        job.status = "failed" if job.attempt_count >= job.max_attempts else "queued"
        job.lease_owner = None
        job.lease_token = None
        job.lease_expires_at = None
        self.db.commit()
        self.db.refresh(job)
        return job

    def status(self, *, owner: str) -> dict:
        jobs = self.db.scalars(
            select(CalyxJob).where(CalyxJob.owner == owner).order_by(CalyxJob.created_at.desc())
        ).all()
        findings = self.db.scalars(
            select(CalyxFinding)
            .join(CalyxJob, CalyxFinding.job_id == CalyxJob.job_id)
            .where(CalyxJob.owner == owner)
            .order_by(CalyxFinding.updated_at.desc())
            .limit(100)
        ).all()
        counts: dict[str, int] = {}
        for job in jobs:
            counts[job.status] = counts.get(job.status, 0) + 1
        return {
            "queue": counts,
            "active_jobs": [self.job_dict(job) for job in jobs if job.status == "running"],
            "blocked_approvals": [self.job_dict(job) for job in jobs if job.status == "blocked_approval"],
            "recent_jobs": [self.job_dict(job) for job in jobs[:50]],
            "findings": [self.finding_dict(item) for item in findings],
        }

    @staticmethod
    def job_dict(job: CalyxJob) -> dict:
        return {
            "job_id": job.job_id,
            "job_type": job.job_type,
            "title": job.title,
            "status": job.status,
            "priority": job.priority,
            "approval_required": job.approval_required,
            "approval_class": job.approval_class,
            "attempt_count": job.attempt_count,
            "created_at": job.created_at.isoformat() if job.created_at else None,
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
            "error_code": job.error_code,
        }

    @staticmethod
    def finding_dict(item: CalyxFinding) -> dict:
        return {
            "finding_id": item.finding_id,
            "job_id": item.job_id,
            "subsystem": item.subsystem,
            "severity": item.severity,
            "title": item.title,
            "summary": item.summary,
            "recommendation": item.recommendation,
            "confidence": item.confidence,
            "status": item.status,
            "updated_at": item.updated_at.isoformat() if item.updated_at else None,
        }
