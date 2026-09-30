from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .engineering_core import EngineeringAdmissionPolicy, EngineeringWorkIdentity
from .models import utcnow
from .persisted_scheduler import project_persisted_schedule
from .program_models import CalyxProgram, CalyxProgramJob
from .program_repository import PersistentProgramRepository
from .program_retry import (
    DEAD_LETTER_BLOCKER,
    DEAD_LETTER_REPAIR_SCHEMA,
    build_retry_backoff_record,
    dead_letter_repair_fingerprint,
    dead_letter_repair_job_key,
    prior_failures,
)

DEAD_LETTER_HUMAN_ACTION = (
    "Inspect the failed evidence, repair the executable capability, "
    "and create a governed retry revision."
)


@dataclass(frozen=True, slots=True)
class ClaimDiagnostic:
    """Read-only explanation for why claim() returned (or would return) None.

    outcome is one of "IDLE_NO_CANDIDATE" (no runnable job matched the
    filters at all) or "REJECTED_ADMISSION" (a runnable job existed but
    every candidate failed EngineeringAdmissionPolicy.evaluate()).
    """

    outcome: str
    program_job_id: str | None = None
    reason_code: str | None = None
    reason_message: str | None = None


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
        allowed_role_keys: frozenset[str] | None = None,
    ) -> CalyxProgramJob | None:
        now = utcnow()
        self.recover_expired_leases(now=now, owner=owner)
        try:
            persisted_schedule = project_persisted_schedule(self.db, owner=owner, now=now)
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
        if allowed_role_keys is not None:
            if not allowed_role_keys:
                return None
            query = query.where(CalyxProgramJob.role_key.in_(tuple(sorted(allowed_role_keys))))
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
            if allowed_role_keys is not None:
                filters.append(CalyxProgramJob.role_key.in_(tuple(sorted(allowed_role_keys))))
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

    def diagnose(
        self,
        *,
        owner: str | None = None,
        allowed_role_keys: frozenset[str] | None = None,
    ) -> ClaimDiagnostic:
        """Explain why claim() with the same arguments would return None.

        Read-only: takes no lease, commits nothing, recovers no expired
        leases. Mirrors claim()'s own candidate-selection query exactly so
        the explanation is truthful to what claim() actually evaluated, not
        a separate approximation of it. Intended to be called only after a
        real claim() attempt has already returned None, so callers get an
        honest reason instead of a bare "idle" result that can't distinguish
        "there is genuinely no work" from "a candidate was rejected."
        """
        try:
            persisted_schedule = project_persisted_schedule(self.db, owner=owner)
        except ValueError:
            return ClaimDiagnostic(outcome="IDLE_NO_CANDIDATE")
        runnable_rank = {
            program_job_id: rank
            for rank, program_job_id in enumerate(persisted_schedule.runnable_program_job_ids)
        }
        if not runnable_rank:
            return ClaimDiagnostic(outcome="IDLE_NO_CANDIDATE")

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
        if allowed_role_keys is not None:
            if not allowed_role_keys:
                return ClaimDiagnostic(outcome="IDLE_NO_CANDIDATE")
            query = query.where(CalyxProgramJob.role_key.in_(tuple(sorted(allowed_role_keys))))
        candidates = self.db.scalars(query).all()
        if not candidates:
            return ClaimDiagnostic(outcome="IDLE_NO_CANDIDATE")
        candidates.sort(key=lambda item: runnable_rank[item.program_job_id])

        active_query = select(CalyxProgramJob).join(
            CalyxProgram, CalyxProgram.program_id == CalyxProgramJob.program_id
        ).where(CalyxProgramJob.status == "running")
        if owner is not None:
            active_query = active_query.where(CalyxProgram.owner == owner)
        active_rows = self.db.scalars(active_query).all()
        active = [self._identity(item) for item in active_rows]

        last_rejection: tuple[CalyxProgramJob, object] | None = None
        for candidate in candidates:
            decision = self.policy.evaluate(self._identity(candidate), active)
            if decision.admitted:
                # A real claim() with these same arguments would have
                # succeeded on this candidate - report honestly rather than
                # claiming rejection where none occurred.
                return ClaimDiagnostic(outcome="IDLE_NO_CANDIDATE")
            last_rejection = (candidate, decision)

        assert last_rejection is not None
        rejected_job, decision = last_rejection
        return ClaimDiagnostic(
            outcome="REJECTED_ADMISSION",
            program_job_id=rejected_job.program_job_id,
            reason_code=decision.code,
            reason_message=decision.message,
        )

    def heartbeat(
        self,
        *,
        program_job_id: str,
        worker_id: str,
        lease_token: str,
        lease_seconds: int = 300,
    ) -> CalyxProgramJob:
        now = utcnow()
        updated = (
            self.db.query(CalyxProgramJob)
            .filter(
                CalyxProgramJob.program_job_id == program_job_id,
                CalyxProgramJob.status == "running",
                CalyxProgramJob.lease_owner == worker_id,
                CalyxProgramJob.lease_token == lease_token,
                CalyxProgramJob.lease_expires_at.is_not(None),
                CalyxProgramJob.lease_expires_at > now,
            )
            .update(
                {CalyxProgramJob.lease_expires_at: now + timedelta(seconds=lease_seconds)},
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

    def release_preflight(
        self,
        *,
        program_job_id: str,
        worker_id: str,
        lease_token: str,
    ) -> CalyxProgramJob:
        """Release a dry-run lease without creating an authoritative outcome or consuming an attempt."""
        now = utcnow()
        updated = (
            self.db.query(CalyxProgramJob)
            .filter(
                CalyxProgramJob.program_job_id == program_job_id,
                CalyxProgramJob.status == "running",
                CalyxProgramJob.outcome.is_(None),
                CalyxProgramJob.lease_owner == worker_id,
                CalyxProgramJob.lease_token == lease_token,
                CalyxProgramJob.lease_expires_at.is_not(None),
                CalyxProgramJob.lease_expires_at > now,
            )
            .update(
                {
                    CalyxProgramJob.status: "queued",
                    CalyxProgramJob.lease_owner: None,
                    CalyxProgramJob.lease_token: None,
                    CalyxProgramJob.lease_expires_at: None,
                    CalyxProgramJob.attempt_count: CalyxProgramJob.attempt_count - 1,
                },
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
        now = utcnow()
        reserved = (
            self.db.query(CalyxProgramJob)
            .filter(
                CalyxProgramJob.program_job_id == program_job_id,
                CalyxProgramJob.status == "running",
                CalyxProgramJob.outcome.is_(None),
                CalyxProgramJob.lease_owner == worker_id,
                CalyxProgramJob.lease_token == lease_token,
                CalyxProgramJob.lease_expires_at.is_not(None),
                CalyxProgramJob.lease_expires_at > now,
            )
            .update(
                {CalyxProgramJob.status: "completing"},
                synchronize_session=False,
            )
        )
        if not reserved:
            self.db.rollback()
            raise PermissionError("STALE_PROGRAM_JOB_LEASE")

        job = self.db.get(CalyxProgramJob, program_job_id)
        if job is None:
            self.db.rollback()
            raise LookupError("PROGRAM_JOB_NOT_FOUND")
        self.db.refresh(job)
        program = self.db.get(CalyxProgram, job.program_id)
        if program is None:
            self.db.rollback()
            raise LookupError("PROGRAM_NOT_FOUND")
        try:
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
        except Exception:
            self.db.rollback()
            raise

    def release_failed_attempt(
        self,
        *,
        program_job_id: str,
        worker_id: str,
        lease_token: str,
        error_code: str,
        exception_type: str,
        now=None,
    ) -> CalyxProgramJob:
        """Release a live lease after a failed executor attempt.

        The job is not left holding its lease until expiry. Below the attempt
        ceiling it returns to ``queued`` with a durable exponential backoff
        record, and the scheduler skips it until the backoff elapses. At the
        ceiling it is dead-lettered, which blocks its program and records one
        follow-up repair job.
        """
        now = now or utcnow()
        # Fence on the live lease token atomically. The job stays ``running``
        # (so no concurrent claim can take it) until the final state below is
        # committed in the same transaction.
        released = (
            self.db.query(CalyxProgramJob)
            .filter(
                CalyxProgramJob.program_job_id == program_job_id,
                CalyxProgramJob.status == "running",
                CalyxProgramJob.outcome.is_(None),
                CalyxProgramJob.lease_owner == worker_id,
                CalyxProgramJob.lease_token == lease_token,
            )
            .update(
                {
                    CalyxProgramJob.lease_owner: None,
                    CalyxProgramJob.lease_token: None,
                    CalyxProgramJob.lease_expires_at: None,
                },
                synchronize_session=False,
            )
        )
        if not released:
            self.db.rollback()
            raise PermissionError("STALE_PROGRAM_JOB_LEASE")
        job = self.db.get(CalyxProgramJob, program_job_id)
        if job is None:
            self.db.rollback()
            raise LookupError("PROGRAM_JOB_NOT_FOUND")
        self.db.refresh(job)
        record = build_retry_backoff_record(
            attempt_count=job.attempt_count,
            error_code=error_code,
            exception_type=exception_type,
            now=now,
            previous_evidence_json=job.evidence_json,
        )
        if job.attempt_count >= job.max_attempts:
            self._dead_letter(job, now=now, failures=record["failures"])
        else:
            job.status = "queued"
            job.evidence_json = json.dumps(record, sort_keys=True)
        self.db.commit()
        self.db.refresh(job)
        return job

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
                self._dead_letter(job, now=now, failures=prior_failures(job.evidence_json))
            else:
                job.status = "queued"
            recovered += 1
        if recovered:
            self.db.commit()
        return recovered

    def _dead_letter(self, job: CalyxProgramJob, *, now, failures: list[dict]) -> None:
        """Dead-letter ``job``, block its program, and record one repair job.

        Idempotent: the repair job is keyed on the dead-lettered job's id and
        guarded by the program's unique job-key constraint, so re-running the
        recovery never creates a second follow-up.
        """
        job.status = "blocked"
        job.outcome = "DEAD_LETTER"
        job.blocker = DEAD_LETTER_BLOCKER
        job.human_action = DEAD_LETTER_HUMAN_ACTION
        evidence: dict[str, object] = {"attempt_count": job.attempt_count}
        if failures:
            evidence["failures"] = failures
        job.evidence_json = json.dumps(evidence, sort_keys=True)
        job.completed_at = now
        self.db.flush()
        self.block_program_for_dead_letter(job, now=now)

    def block_program_for_dead_letter(self, job: CalyxProgramJob, *, now=None) -> CalyxProgramJob | None:
        """Block the program of a dead-lettered job and ensure one repair job.

        Returns the follow-up repair job, or ``None`` when ``job`` is not a
        dead letter or its program no longer exists or was already completed
        or cancelled by its owner. Does not commit.
        """
        if job.outcome != "DEAD_LETTER":
            return None
        now = now or utcnow()
        program = self.db.get(CalyxProgram, job.program_id)
        if program is None:
            return None
        # Settle dependants first: waiting jobs downstream of the dead letter
        # become BLOCKED/UPSTREAM_JOB_FAILED, as for any other failed outcome.
        # This only acts while the program is still running.
        PersistentProgramRepository(self.db).release_ready_jobs(program_id=program.program_id)
        if program.status in {"completed", "cancelled"}:
            # The owner already ended this program; nothing is left to repair.
            return None
        program.status = "blocked"
        reason = f"{DEAD_LETTER_BLOCKER}:{job.job_key}"

        repair_key = dead_letter_repair_job_key(job.program_job_id)
        existing = self.db.scalar(
            select(CalyxProgramJob).where(
                CalyxProgramJob.program_id == program.program_id,
                CalyxProgramJob.job_key == repair_key,
            )
        )
        if existing is not None:
            return existing
        repair = CalyxProgramJob(
            program_id=program.program_id,
            job_key=repair_key,
            role_key=job.role_key,
            title=f"Repair dead-lettered job {job.job_key}"[:240],
            repository=job.repository,
            branch=job.branch,
            mutating=job.mutating,
            input_json=json.dumps(
                {
                    "schema": DEAD_LETTER_REPAIR_SCHEMA,
                    "reason": reason,
                    "dead_letter_program_job_id": job.program_job_id,
                    "dead_letter_job_key": job.job_key,
                    "attempt_count": job.attempt_count,
                    "max_attempts": job.max_attempts,
                    "dead_lettered_at": now.isoformat(),
                    "execution_mode": "governed_repair_revision_required",
                    "automatic_retry": False,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            work_fingerprint=dead_letter_repair_fingerprint(job.program_job_id),
            # Never released into a blocked program: it stays an inert,
            # reviewable record until a governed revision acts on it.
            status="waiting",
            human_action=DEAD_LETTER_HUMAN_ACTION,
            attempt_count=0,
            max_attempts=job.max_attempts,
        )
        self.db.add(repair)
        self.db.flush()
        return repair

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
