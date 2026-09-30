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
    DEAD_LETTER_OWNER_ACTION_SCHEMA,
    OWNER_ACTION_BLOCKER,
    build_retry_backoff_record,
    dead_letter_repair_fingerprint,
    dead_letter_repair_job_key,
    in_retry_backoff,
    is_owner_action_record,
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
        # populate_existing: evaluate the rows as they are now, not as this
        # session's identity map last saw them.
        candidates = self.db.scalars(query.execution_options(populate_existing=True)).all()
        candidates.sort(key=lambda item: runnable_rank[item.program_job_id])

        active_query = select(CalyxProgramJob).join(
            CalyxProgram, CalyxProgram.program_id == CalyxProgramJob.program_id
        ).where(CalyxProgramJob.status == "running")
        if owner is not None:
            active_query = active_query.where(CalyxProgram.owner == owner)
        active_rows = self.db.scalars(active_query).all()
        active = [self._identity(item) for item in active_rows]

        for candidate in candidates:
            # Re-check backoff on the row this claim will fence on, not only
            # on the schedule projection read earlier.
            if in_retry_backoff(candidate.status, candidate.evidence_json, now):
                continue
            observed_attempts = candidate.attempt_count
            observed_evidence = candidate.evidence_json
            decision = self.policy.evaluate(self._identity(candidate), active)
            if not decision.admitted:
                continue
            token = str(uuid4())
            filters = [
                CalyxProgramJob.program_job_id == candidate.program_job_id,
                CalyxProgramJob.status == "queued",
                CalyxProgramJob.outcome.is_(None),
                # Compare-and-swap on what was evaluated. Any claim, failed
                # attempt or backoff written since then changes these, so a
                # concurrent worker's fresh backoff cannot be claimed through.
                CalyxProgramJob.attempt_count == observed_attempts,
                (
                    CalyxProgramJob.evidence_json.is_(None)
                    if observed_evidence is None
                    else CalyxProgramJob.evidence_json == observed_evidence
                ),
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

    def _select_expired_leases(self, *, now, owner: str | None) -> list[CalyxProgramJob]:
        query = (
            select(CalyxProgramJob)
            .join(CalyxProgram, CalyxProgram.program_id == CalyxProgramJob.program_id)
            .where(
                CalyxProgramJob.status == "running",
                CalyxProgramJob.outcome.is_(None),
                CalyxProgramJob.lease_expires_at.is_not(None),
                CalyxProgramJob.lease_expires_at <= now,
            )
            .execution_options(populate_existing=True)
        )
        if owner is not None:
            query = query.where(CalyxProgram.owner == owner)
        return list(self.db.scalars(query).all())

    def recover_expired_leases(self, *, now=None, owner: str | None = None) -> int:
        now = now or utcnow()
        observed = [
            (job.program_job_id, job.lease_token, job.attempt_count >= job.max_attempts)
            for job in self._select_expired_leases(now=now, owner=owner)
        ]
        recovered = 0
        for program_job_id, token, exhausted in observed:
            # Fence on the expired lease exactly as observed. If its holder
            # released it (with a backoff record) or it was recovered
            # elsewhere in the meantime, this matches nothing and the newer
            # state, including its failure history, is left alone.
            fenced = (
                self.db.query(CalyxProgramJob)
                .filter(
                    CalyxProgramJob.program_job_id == program_job_id,
                    CalyxProgramJob.status == "running",
                    CalyxProgramJob.outcome.is_(None),
                    (
                        CalyxProgramJob.lease_token.is_(None)
                        if token is None
                        else CalyxProgramJob.lease_token == token
                    ),
                    CalyxProgramJob.lease_expires_at.is_not(None),
                    CalyxProgramJob.lease_expires_at <= now,
                )
                .update(
                    {
                        CalyxProgramJob.lease_owner: None,
                        CalyxProgramJob.lease_token: None,
                        CalyxProgramJob.lease_expires_at: None,
                        # Exhausted jobs stay running (unclaimable) until the
                        # dead letter below is written in this transaction.
                        CalyxProgramJob.status: "running" if exhausted else "queued",
                    },
                    synchronize_session=False,
                )
            )
            if not fenced:
                continue
            recovered += 1
            if exhausted:
                job = self.db.get(CalyxProgramJob, program_job_id)
                if job is None:
                    continue
                self.db.refresh(job)
                self._dead_letter(job, now=now, failures=prior_failures(job.evidence_json))
        if recovered:
            self.db.commit()
        return recovered

    def _dead_letter(self, job: CalyxProgramJob, *, now, failures: list[dict]) -> None:
        """Dead-letter ``job``, block its program, and record one owner action."""
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
        """Block the program of a dead-lettered job and record one owner action.

        The follow-up is an explicit owner-action record, not a runnable job.
        There is no repair executor, and re-running the capability that just
        failed its full attempt budget is exactly what the dead letter exists
        to stop; the governed path is a new program revision. So the record is
        ``blocked`` with ``blocker=OWNER_ACTION_REQUIRED:DEAD_LETTER`` and no
        outcome, which every owner surface (program snapshot, portfolio
        blockers and next actions) already shows. It is never schedulable
        (terminal status, ``max_attempts=0``), and the owner resolves it by
        recording an outcome on it (``POST /{program_id}/jobs/{job_key}/outcome``).

        Returns the record, or ``None`` when ``job`` is not a dead letter, is
        itself an owner-action record (no chaining), or its program no longer
        exists or was already completed or cancelled. Idempotent: the record
        is keyed on the dead job's id under the program's unique job-key
        constraint. Does not commit.
        """
        if job.outcome != "DEAD_LETTER":
            return None
        now = now or utcnow()
        program = self.db.get(CalyxProgram, job.program_id)
        if program is None:
            return None
        # Settle every dependant, transitively and regardless of row order.
        PersistentProgramRepository(self.db).settle_failed_dependants(program_id=program.program_id)
        if program.status in {"completed", "cancelled"}:
            # The owner already ended this program; nothing is left to repair.
            return None
        program.status = "blocked"
        if is_owner_action_record(job.job_key, job.input_json):
            # A follow-up record never produces another follow-up.
            return None

        record_key = dead_letter_repair_job_key(job.program_job_id)
        existing = self.db.scalar(
            select(CalyxProgramJob).where(
                CalyxProgramJob.program_id == program.program_id,
                CalyxProgramJob.job_key == record_key,
            )
        )
        if existing is not None:
            return existing
        reason = f"{DEAD_LETTER_BLOCKER}:{job.job_key}"
        record = CalyxProgramJob(
            program_id=program.program_id,
            job_key=record_key,
            role_key=job.role_key,
            title=f"Owner action: dead-lettered job {job.job_key}"[:240],
            repository=job.repository,
            branch=job.branch,
            mutating=False,
            # No reserved assignment keys: this manifest describes the record
            # and is never turned into an assignment.
            input_json=json.dumps(
                {
                    "schema": DEAD_LETTER_OWNER_ACTION_SCHEMA,
                    "record_kind": "owner_action",
                    "reason": reason,
                    "dead_letter_program_job_id": job.program_job_id,
                    "dead_letter_job_key": job.job_key,
                    "attempts_used": job.attempt_count,
                    "attempt_limit": job.max_attempts,
                    "dead_lettered_at": now.isoformat(),
                    "automatic_retry": False,
                    "resolution": (
                        "Create a governed program revision that repairs or replaces "
                        "the failed capability, then record an outcome on this record."
                    ),
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
            work_fingerprint=dead_letter_repair_fingerprint(job.program_job_id),
            status="blocked",
            outcome=None,
            blocker=OWNER_ACTION_BLOCKER,
            human_action=(
                f"Dead letter {reason} blocked program {program.program_id}. "
                f"{DEAD_LETTER_HUMAN_ACTION} Then record an outcome on job "
                f"{record_key} to close this owner action."
            ),
            attempt_count=0,
            max_attempts=0,
        )
        self.db.add(record)
        self.db.flush()
        return record

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
