from __future__ import annotations

import json
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .engineering_core import EngineeringAdmissionPolicy, EngineeringWorkIdentity
from .models import utcnow
from .persisted_scheduler import project_persisted_schedule
from .program_models import CalyxProgram, CalyxProgramJob
from .program_repository import PersistentProgramRepository


class PersistentProgramWorker:
    """Claims and completes released engineering jobs under durable leases."""

    def __init__(self, db: Session, policy: EngineeringAdmissionPolicy | None = None) -> None:
        self.db = db
        self.policy = policy or EngineeringAdmissionPolicy()

    def claim(
        self,
        *,
        worker_id: str,
        lease_seconds: int = 300,
        owner: str | None = None,
    ) -> CalyxProgramJob | None:
        now = utcnow()
        self.recover_expired_leases(now=now, owner=owner)
        try:
            persisted_schedule = project_persisted_schedule(self.db, owner=owner)
        except ValueError:
            return None
        runnable_rank = {
            program_job_id: rank
            for rank, program_job_id in enumerate(persisted_schedule.runnable_program_job_ids)
        }
        if not runnable_rank:
            return None

        query = (
            select(CalyxProgramJob)
            .join(CalyxProgram, CalyxProgram.program_id == CalyxProgramJob.program_id)
            .where(
                CalyxProgram.status == "running",
                CalyxProgram.paused.is_(False),
                CalyxProgramJob.status == "queued",
                CalyxProgramJob.outcome.is_(None),
                CalyxProgramJob.attempt_count < CalyxProgramJob.max_attempts,
                CalyxProgramJob.program_job_id.in_(tuple(runnable_rank)),
            )
            .limit(50)
        )
        if owner is not None:
            query = query.where(CalyxProgram.owner == owner)
        candidates = self.db.scalars(query).all()
        candidates.sort(key=lambda item: runnable_rank[item.program_job_id])

        active_query = select(CalyxProgramJob).join(
            CalyxProgram, CalyxProgram.program_id == CalyxProgramJob.program_id
        ).where(CalyxProgramJob.status == "running")
        if owner is not None:
            active_query = active_query.where(CalyxProgram.owner == owner)
        active_rows = self.db.scalars(active_query).all()
        active = [self._identity(item) for item in active_rows]

        for candidate in candidates:
            decision = self.policy.evaluate(self._identity(candidate), active)
            if not decision.admitted:
                continue
            token = str(uuid4())
            filters = [
                CalyxProgramJob.program_job_id == candidate.program_job_id,
                CalyxProgramJob.status == "queued",
                CalyxProgramJob.outcome.is_(None),
            ]
            if owner is not None:
                owned_program_ids = select(CalyxProgram.program_id).where(CalyxProgram.owner == owner)
                filters.append(CalyxProgramJob.program_id.in_(owned_program_ids))
            updated = (
                self.db.query(CalyxProgramJob)
                .filter(*filters)
                .update(
                    {
                        CalyxProgramJob.status: "running",
                        CalyxProgramJob.lease_owner: worker_id,
                        CalyxProgramJob.lease_token: token,
                        CalyxProgramJob.lease_expires_at: now + timedelta(seconds=lease_seconds),
                        CalyxProgramJob.attempt_count: CalyxProgramJob.attempt_count + 1,
                    },
                    synchronize_session=False,
                )
            )
            if updated:
                self.db.commit()
                claimed = self.db.get(CalyxProgramJob, candidate.program_job_id)
                if claimed is None:
                    raise LookupError("PROGRAM_JOB_NOT_FOUND")
                self.db.refresh(claimed)
                return claimed
            self.db.rollback()
        return None

    def heartbeat(self, *, program_job_id: str, worker_id: str, lease_token: str, lease_seconds: int = 300) -> CalyxProgramJob:
        updated = (
            self.db.query(CalyxProgramJob)
            .filter(
                CalyxProgramJob.program_job_id == program_job_id,
                CalyxProgramJob.status == "running",
                CalyxProgramJob.lease_owner == worker_id,
                CalyxProgramJob.lease_token == lease_token,
            )
            .update(
                {CalyxProgramJob.lease_expires_at: utcnow() + timedelta(seconds=lease_seconds)},
                synchronize_session=False,
            )
        )
        if not updated:
            self.db.rollback()
            raise PermissionError("STALE_PROGRAM_JOB_LEASE")
        self.db.commit()
        job = self.db.get(CalyxProgramJob, program_job_id)
        if job is None:
            raise LookupError("PROGRAM_JOB_NOT_FOUND")
        self.db.refresh(job)
        return job

    def complete(
        self,
        *,
        program_job_id: str,
        worker_id: str,
        lease_token: str,
        outcome: str,
        evidence: dict | None = None,
        blocker: str | None = None,
        human_action: str | None = None,
    ) -> CalyxProgramJob:
        job = self.db.get(CalyxProgramJob, program_job_id)
        if job is None:
            raise LookupError("PROGRAM_JOB_NOT_FOUND")
        if job.status != "running" or job.lease_owner != worker_id or job.lease_token != lease_token:
            raise PermissionError("STALE_PROGRAM_JOB_LEASE")
        program = self.db.get(CalyxProgram, job.program_id)
        if program is None:
            raise LookupError("PROGRAM_NOT_FOUND")
        completed = PersistentProgramRepository(self.db).record_outcome(
            owner=program.owner,
            program_id=program.program_id,
            job_key=job.job_key,
            outcome=outcome,
            evidence=evidence,
            blocker=blocker,
            human_action=human_action,
        )
        completed.lease_owner = None
        completed.lease_token = None
        completed.lease_expires_at = None
        self.db.commit()
        self.db.refresh(completed)
        return completed

    def recover_expired_leases(self, *, now=None, owner: str | None = None) -> int:
        now = now or utcnow()
        query = (
            select(CalyxProgramJob)
            .join(CalyxProgram, CalyxProgram.program_id == CalyxProgramJob.program_id)
            .where(
                CalyxProgramJob.status == "running",
                CalyxProgramJob.outcome.is_(None),
                CalyxProgramJob.lease_expires_at.is_not(None),
                CalyxProgramJob.lease_expires_at <= now,
            )
        )
        if owner is not None:
            query = query.where(CalyxProgram.owner == owner)
        expired = self.db.scalars(query).all()
        recovered = 0
        for job in expired:
            job.lease_owner = None
            job.lease_token = None
            job.lease_expires_at = None
            if job.attempt_count >= job.max_attempts:
                job.status = "blocked"
                job.outcome = "DEAD_LETTER"
                job.blocker = "PROGRAM_JOB_ATTEMPTS_EXHAUSTED"
                job.human_action = "Inspect the failed evidence, repair the executable capability, and create a governed retry revision."
                job.evidence_json = json.dumps({"attempt_count": job.attempt_count}, sort_keys=True)
                job.completed_at = now
            else:
                job.status = "queued"
            recovered += 1
        if recovered:
            self.db.commit()
        return recovered

    @staticmethod
    def _identity(job: CalyxProgramJob) -> EngineeringWorkIdentity:
        return EngineeringWorkIdentity(
            job_id=job.program_job_id,
            role=job.role_key,
            repository=job.repository,
            branch=job.branch,
            mutates_code=job.mutating,
            status=job.status,
        )
