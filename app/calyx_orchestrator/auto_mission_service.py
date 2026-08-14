from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, replace
from datetime import timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from .assignment_factory import governed_assignment_from_claimed_job
from .auto_mission import (
    GovernanceAwarePrioritySelector,
    GovernanceDisposition,
    MissionReceiptValidator,
    ValidationDecision,
    ValidationDisposition,
)
from .auto_mission_models import (
    CalyxBrainCompletionWriteback,
    CalyxProgramValidationEvent,
)
from .engineering_core import EngineeringWorkIdentity, TerminalOutcome
from .executor import ExecutionReceipt, GovernedAssignment
from .executor_registry import AuthoritativeExecutorRegistry, RegisteredExecutor
from .models import utcnow
from .persisted_scheduler import project_persisted_schedule
from .program_models import CalyxProgram, CalyxProgramJob
from .program_repository import SUCCESSFUL_OUTCOMES, PersistentProgramRepository
from .program_worker import PersistentProgramWorker


@dataclass(frozen=True, slots=True)
class AutoMissionJobResult:
    program_job_id: str
    program_id: str
    job_key: str
    disposition: str
    outcome: str | None
    attempt_count: int
    executor_key: str | None = None
    validation_code: str | None = None
    brain_writeback_id: str | None = None
    continuation_released: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AutoMissionCycleResult:
    owner: str
    worker_id: str
    attempted_jobs: int
    completed_jobs: int
    validator_retries: int
    governance_holds: int
    stop_reason: str
    jobs: tuple[AutoMissionJobResult, ...]
    error: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "jobs": [asdict(item) for item in self.jobs],
            "durable_mission_queue": True,
            "lease_claim_semantics": True,
            "governance_aware_priority_selector": True,
            "validator_feedback_loop": True,
            "brain_completion_writeback": True,
            "automatic_next_mission_continuation": True,
            "automatic_merge": False,
            "automatic_deployment": False,
            "automatic_publication": False,
            "production_knowledge_graph_mutation": False,
        }


class GovernedAutoMissionWorker:
    def __init__(
        self,
        db: Session,
        selector: GovernanceAwarePrioritySelector | None = None,
    ) -> None:
        self.db = db
        self.selector = selector or GovernanceAwarePrioritySelector()
        self.base = PersistentProgramWorker(db)

    @staticmethod
    def _identity(job: CalyxProgramJob) -> EngineeringWorkIdentity:
        return EngineeringWorkIdentity(
            job.program_job_id,
            job.role_key,
            job.repository,
            job.branch,
            job.mutating,
            job.status,
        )

    def _queued_partition(
        self,
        *,
        owner: str,
        roles: frozenset[str],
        program_ids: tuple[str, ...] | None = None,
    ) -> tuple[frozenset[str], frozenset[str]]:
        """Partition claimable queued work before provisional capacity is allocated."""
        query = (
            select(CalyxProgramJob)
            .join(CalyxProgram)
            .where(
                CalyxProgram.owner == owner,
                CalyxProgram.status == "running",
                CalyxProgram.paused.is_(False),
                CalyxProgramJob.status == "queued",
                CalyxProgramJob.outcome.is_(None),
                CalyxProgramJob.attempt_count < CalyxProgramJob.max_attempts,
            )
        )
        if program_ids is not None:
            if not program_ids:
                return frozenset(), frozenset()
            query = query.where(CalyxProgram.program_id.in_(program_ids))
        automatic: set[str] = set()
        held: set[str] = set()
        for job in self.db.scalars(query).all():
            if (
                job.role_key in roles
                and self.selector.decision(job).disposition
                == GovernanceDisposition.AUTOMATIC
            ):
                automatic.add(job.program_job_id)
            else:
                held.add(job.program_job_id)
        return frozenset(automatic), frozenset(held)

    def hold_governance_bound(
        self,
        *,
        owner: str,
        roles: frozenset[str],
    ) -> list[str]:
        """Report dependency-ready work that cannot be claimed automatically.

        Held work is projected as the only provisional candidate set. It therefore
        remains visible as a governance boundary without consuming the capacity used
        to choose automatically admissible work in ``claim``.
        """
        _, held_ids = self._queued_partition(owner=owner, roles=roles)
        if not held_ids:
            return []
        schedule = project_persisted_schedule(
            self.db,
            owner=owner,
            candidate_program_job_ids=held_ids,
        )
        return sorted(schedule.runnable_program_job_ids)

    def _lock_owner_claim_scope(self, owner: str) -> tuple[str, ...]:
        """Serialize owner-level admission decisions until the claim transaction commits."""
        program_ids = self.db.scalars(
            select(CalyxProgram.program_id)
            .where(
                CalyxProgram.owner == owner,
                CalyxProgram.status == "running",
                CalyxProgram.paused.is_(False),
            )
            .order_by(CalyxProgram.program_id.asc())
            .with_for_update()
        ).all()
        return tuple(program_ids)

    def claim(
        self,
        *,
        worker_id: str,
        owner: str,
        roles: frozenset[str],
        lease_seconds: int,
    ) -> CalyxProgramJob | None:
        now = utcnow()
        self.base.recover_expired_leases(now=now, owner=owner)
        locked_program_ids = self._lock_owner_claim_scope(owner)
        if not locked_program_ids:
            self.db.rollback()
            return None
        try:
            automatic_ids, _ = self._queued_partition(
                owner=owner,
                roles=roles,
                program_ids=locked_program_ids,
            )
            if not automatic_ids:
                self.db.rollback()
                return None
            schedule = project_persisted_schedule(
                self.db,
                owner=owner,
                candidate_program_job_ids=automatic_ids,
            )
        except (TypeError, ValueError):
            self.db.rollback()
            raise
        rank = {
            job_id: index
            for index, job_id in enumerate(schedule.runnable_program_job_ids)
        }
        if not rank or not roles:
            self.db.rollback()
            return None
        jobs = self.db.scalars(
            select(CalyxProgramJob)
            .join(CalyxProgram)
            .where(
                CalyxProgram.owner == owner,
                CalyxProgram.program_id.in_(locked_program_ids),
                CalyxProgram.status == "running",
                CalyxProgram.paused.is_(False),
                CalyxProgramJob.status == "queued",
                CalyxProgramJob.outcome.is_(None),
                CalyxProgramJob.attempt_count < CalyxProgramJob.max_attempts,
                CalyxProgramJob.program_job_id.in_(tuple(rank)),
                CalyxProgramJob.role_key.in_(tuple(sorted(roles))),
            )
            .limit(100)
        ).all()
        active = [
            self._identity(item)
            for item in self.db.scalars(
                select(CalyxProgramJob)
                .join(CalyxProgram)
                .where(
                    CalyxProgram.owner == owner,
                    CalyxProgram.program_id.in_(locked_program_ids),
                    CalyxProgramJob.status == "running",
                )
            ).all()
        ]
        for job in self.selector.order(jobs, rank):
            if not self.base.policy.evaluate(self._identity(job), active).admitted:
                continue
            token = str(uuid4())
            updated = (
                self.db.query(CalyxProgramJob)
                .filter(
                    CalyxProgramJob.program_job_id == job.program_job_id,
                    CalyxProgramJob.status == "queued",
                    CalyxProgramJob.outcome.is_(None),
                    CalyxProgramJob.attempt_count < CalyxProgramJob.max_attempts,
                    CalyxProgramJob.program_id.in_(locked_program_ids),
                )
                .update(
                    {
                        CalyxProgramJob.status: "running",
                        CalyxProgramJob.lease_owner: worker_id,
                        CalyxProgramJob.lease_token: token,
                        CalyxProgramJob.lease_expires_at: now
                        + timedelta(seconds=lease_seconds),
                        CalyxProgramJob.attempt_count: CalyxProgramJob.attempt_count
                        + 1,
                    },
                    synchronize_session=False,
                )
            )
            if updated:
                self.db.commit()
                claimed = self.db.get(CalyxProgramJob, job.program_job_id)
                if claimed is None:
                    raise LookupError("PROGRAM_JOB_NOT_FOUND")
                self.db.refresh(claimed)
                return claimed
            self.db.rollback()
            return None
        self.db.rollback()
        return None

    def retry(
        self,
        *,
        job: CalyxProgramJob,
        worker_id: str,
        token: str,
        decision: ValidationDecision,
    ) -> CalyxProgramJob:
        if (
            decision.disposition == ValidationDisposition.DEAD_LETTER
            or job.attempt_count >= job.max_attempts
        ):
            return self.base.complete(
                program_job_id=job.program_job_id,
                worker_id=worker_id,
                lease_token=token,
                outcome=TerminalOutcome.DEAD_LETTER.value,
                evidence={
                    "validation_code": decision.code,
                    "validator_feedback": list(decision.feedback),
                    "attempt_count": job.attempt_count,
                },
                blocker="VALIDATION_ATTEMPTS_EXHAUSTED",
                human_action=(
                    "Review validator feedback and create a governed mission revision."
                ),
            )
        now = utcnow()
        updated = (
            self.db.query(CalyxProgramJob)
            .filter(
                CalyxProgramJob.program_job_id == job.program_job_id,
                CalyxProgramJob.status == "running",
                CalyxProgramJob.outcome.is_(None),
                CalyxProgramJob.lease_owner == worker_id,
                CalyxProgramJob.lease_token == token,
                CalyxProgramJob.lease_expires_at.is_not(None),
                CalyxProgramJob.lease_expires_at > now,
            )
            .update(
                {
                    CalyxProgramJob.status: "queued",
                    CalyxProgramJob.lease_owner: None,
                    CalyxProgramJob.lease_token: None,
                    CalyxProgramJob.lease_expires_at: None,
                    CalyxProgramJob.blocker: decision.code,
                    CalyxProgramJob.human_action: (
                        "Apply validator feedback on the next autonomous attempt."
                    ),
                },
                synchronize_session=False,
            )
        )
        if not updated:
            self.db.rollback()
            raise PermissionError("STALE_PROGRAM_JOB_LEASE")
        self.db.commit()
        current = self.db.get(CalyxProgramJob, job.program_job_id)
        if current is None:
            raise LookupError("PROGRAM_JOB_NOT_FOUND")
        self.db.refresh(current)
        return current

    def fail_execution(
        self,
        *,
        job: CalyxProgramJob,
        worker_id: str,
        token: str,
        exc: Exception,
    ) -> CalyxProgramJob:
        """Release an expected executor failure without waiting for lease expiry."""
        code = f"EXECUTOR_EXCEPTION:{type(exc).__name__}"
        if job.attempt_count >= job.max_attempts:
            return self.base.complete(
                program_job_id=job.program_job_id,
                worker_id=worker_id,
                lease_token=token,
                outcome=TerminalOutcome.DEAD_LETTER.value,
                evidence={
                    "execution_exception_type": type(exc).__name__,
                    "attempt_count": job.attempt_count,
                    "receipt_recorded": False,
                },
                blocker="EXECUTION_ATTEMPTS_EXHAUSTED",
                human_action=(
                    "Inspect the mission input/executor failure and create a governed retry revision."
                ),
            )
        now = utcnow()
        updated = (
            self.db.query(CalyxProgramJob)
            .filter(
                CalyxProgramJob.program_job_id == job.program_job_id,
                CalyxProgramJob.status == "running",
                CalyxProgramJob.outcome.is_(None),
                CalyxProgramJob.lease_owner == worker_id,
                CalyxProgramJob.lease_token == token,
                CalyxProgramJob.lease_expires_at.is_not(None),
                CalyxProgramJob.lease_expires_at > now,
            )
            .update(
                {
                    CalyxProgramJob.status: "queued",
                    CalyxProgramJob.lease_owner: None,
                    CalyxProgramJob.lease_token: None,
                    CalyxProgramJob.lease_expires_at: None,
                    CalyxProgramJob.blocker: code,
                    CalyxProgramJob.human_action: (
                        "Retry is permitted; inspect mission input if the executor failure repeats."
                    ),
                },
                synchronize_session=False,
            )
        )
        if not updated:
            self.db.rollback()
            raise PermissionError("STALE_PROGRAM_JOB_LEASE")
        self.db.commit()
        current = self.db.get(CalyxProgramJob, job.program_job_id)
        if current is None:
            raise LookupError("PROGRAM_JOB_NOT_FOUND")
        self.db.refresh(current)
        return current


class AutoMissionCoordinator:
    def __init__(
        self,
        db: Session,
        *,
        registry: AuthoritativeExecutorRegistry | None = None,
        selector: GovernanceAwarePrioritySelector | None = None,
        validator: MissionReceiptValidator | None = None,
    ) -> None:
        self.db = db
        self.registry = registry or AuthoritativeExecutorRegistry()
        self.selector = selector or GovernanceAwarePrioritySelector()
        self.validator = validator or MissionReceiptValidator()
        self.worker = GovernedAutoMissionWorker(db, self.selector)

    def assignment_with_feedback(
        self,
        *,
        owner: str,
        job: CalyxProgramJob,
        timeout_seconds: int,
    ) -> GovernedAssignment:
        assignment = governed_assignment_from_claimed_job(
            self.db,
            owner=owner,
            job=job,
            timeout_seconds=timeout_seconds,
        )
        latest = self.db.scalar(
            select(CalyxProgramValidationEvent)
            .where(CalyxProgramValidationEvent.program_job_id == job.program_job_id)
            .order_by(
                CalyxProgramValidationEvent.created_at.desc(),
                CalyxProgramValidationEvent.validation_event_id.desc(),
            )
            .limit(1)
        )
        if latest is None or latest.disposition != ValidationDisposition.RETRY.value:
            return assignment
        inputs = dict(assignment.inputs)
        inputs["validator_feedback"] = {
            "code": latest.code,
            "feedback": json.loads(latest.feedback_json or "[]"),
            "previous_attempt_count": latest.attempt_count,
        }
        return replace(assignment, inputs=inputs, input_checksum=None)

    @staticmethod
    def _verify_receipt_binding(
        *,
        registered: RegisteredExecutor,
        assignment: GovernedAssignment,
        receipt: ExecutionReceipt,
    ) -> None:
        """Bind a self-consistent receipt to the exact dispatched assignment/executor."""
        receipt.verify()
        if (
            receipt.assignment_id != assignment.assignment_id
            or receipt.program_id != assignment.program_id
            or receipt.job_key != assignment.job_key
        ):
            raise ValueError("RECEIPT_IDENTITY_MISMATCH")
        if receipt.executor_key != registered.executor.executor_key:
            raise ValueError("RECEIPT_EXECUTOR_IDENTITY_MISMATCH")
        if receipt.input_checksum != assignment.verified_input_checksum():
            raise ValueError("RECEIPT_INPUT_CHECKSUM_MISMATCH")

    def record_validation(
        self,
        *,
        job: CalyxProgramJob,
        decision: ValidationDecision,
        receipt: ExecutionReceipt,
    ) -> CalyxProgramValidationEvent:
        event = CalyxProgramValidationEvent(
            program_job_id=job.program_job_id,
            attempt_count=job.attempt_count,
            disposition=decision.disposition.value,
            code=decision.code,
            feedback_json=json.dumps(list(decision.feedback), sort_keys=True),
            receipt_checksum=receipt.output_checksum,
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    @staticmethod
    def _receipt(receipt: ExecutionReceipt) -> dict[str, object]:
        return {
            "receipt_type": "execution",
            "assignment_id": receipt.assignment_id,
            "program_id": receipt.program_id,
            "job_key": receipt.job_key,
            "executor_key": receipt.executor_key,
            "state": receipt.state.value,
            "input_checksum": receipt.input_checksum,
            "output_checksum": receipt.output_checksum,
            "output": dict(receipt.output),
            "evidence_uris": list(receipt.evidence_uris),
            "blocker_code": receipt.blocker_code,
        }

    def _writeback(
        self,
        *,
        owner: str,
        job: CalyxProgramJob,
        receipt: ExecutionReceipt,
        event: CalyxProgramValidationEvent,
    ) -> CalyxBrainCompletionWriteback:
        key = hashlib.sha256(
            (
                f"{owner}|{job.program_id}|{job.program_job_id}|"
                f"{receipt.output_checksum}"
            ).encode()
        ).hexdigest()
        existing = self.db.scalar(
            select(CalyxBrainCompletionWriteback).where(
                CalyxBrainCompletionWriteback.program_job_id == job.program_job_id
            )
        )
        if existing:
            if existing.completion_key != key:
                raise ValueError("BRAIN_COMPLETION_WRITEBACK_DIVERGENCE")
            return existing
        payload = {
            "schema": "calyx-auto-brain-completion/v1",
            "owner": owner,
            "program_id": job.program_id,
            "program_job_id": job.program_job_id,
            "job_key": job.job_key,
            "role_key": job.role_key,
            "repository": job.repository,
            "branch": job.branch,
            "attempt_count": job.attempt_count,
            "outcome": receipt.outcome.value,
            "executor_key": receipt.executor_key,
            "input_checksum": receipt.input_checksum,
            "output_checksum": receipt.output_checksum,
            "evidence_uris": list(receipt.evidence_uris),
            "validation": {
                "event_id": event.validation_event_id,
                "disposition": event.disposition,
                "code": event.code,
            },
            "authority": {
                "automatic_merge": False,
                "automatic_deployment": False,
                "automatic_publication": False,
                "production_database_mutation": False,
                "production_knowledge_graph_mutation": False,
            },
        }
        row = CalyxBrainCompletionWriteback(
            program_id=job.program_id,
            program_job_id=job.program_job_id,
            owner=owner,
            completion_key=key,
            payload_json=json.dumps(payload, sort_keys=True, default=str),
            status="recorded",
        )
        self.db.add(row)
        self.db.flush()
        return row

    def complete_validated(
        self,
        *,
        owner: str,
        job: CalyxProgramJob,
        worker_id: str,
        token: str,
        receipt: ExecutionReceipt,
        event: CalyxProgramValidationEvent,
    ):
        receipt.verify()
        now = utcnow()
        current = self.db.get(CalyxProgramJob, job.program_job_id)
        if current is None:
            raise LookupError("PROGRAM_JOB_NOT_FOUND")
        program = self.db.get(CalyxProgram, current.program_id)
        if program is None or program.owner != owner:
            raise LookupError("PROGRAM_NOT_FOUND")
        if (
            current.status != "running"
            or current.outcome is not None
            or current.lease_owner != worker_id
            or current.lease_token != token
            or current.lease_expires_at is None
            or current.lease_expires_at <= now
        ):
            raise PermissionError("STALE_PROGRAM_JOB_LEASE")
        if (
            receipt.assignment_id != current.program_job_id
            or receipt.program_id != program.program_id
            or receipt.job_key != current.job_key
        ):
            raise ValueError("RECEIPT_IDENTITY_MISMATCH")
        if receipt.outcome.value not in SUCCESSFUL_OUTCOMES:
            raise ValueError("VALIDATED_SUCCESS_OUTCOME_REQUIRED")
        current.outcome = receipt.outcome.value
        current.status = "completed"
        current.evidence_json = json.dumps(
            self._receipt(receipt),
            sort_keys=True,
            default=str,
        )
        current.blocker = None
        current.human_action = None
        current.completed_at = now
        current.lease_owner = None
        current.lease_token = None
        current.lease_expires_at = None
        writeback = self._writeback(
            owner=owner,
            job=current,
            receipt=receipt,
            event=event,
        )
        repo = PersistentProgramRepository(self.db)
        released = repo.release_ready_jobs(program_id=current.program_id)
        repo._refresh_program_status(current.program_id)
        self.db.commit()
        self.db.refresh(current)
        self.db.refresh(writeback)
        return current, writeback, tuple(item.program_job_id for item in released)

    def _review(
        self,
        *,
        job: CalyxProgramJob,
        worker_id: str,
        token: str,
        receipt: ExecutionReceipt,
        decision: ValidationDecision,
    ):
        return self.worker.base.complete(
            program_job_id=job.program_job_id,
            worker_id=worker_id,
            lease_token=token,
            outcome=TerminalOutcome.BLOCKED.value,
            evidence={
                "receipt": self._receipt(receipt),
                "validation_code": decision.code,
                "validator_feedback": list(decision.feedback),
            },
            blocker=decision.code,
            human_action=(
                "Review validator/governance feedback before creating a governed continuation."
            ),
        )

    @staticmethod
    def _rollback(
        registered: RegisteredExecutor | None,
        assignment_id: str,
    ) -> None:
        if registered is None or not registered.workspace_mutation:
            return
        rollback = getattr(registered.executor, "rollback", None)
        if rollback is None:
            raise RuntimeError("WORKSPACE_ROLLBACK_UNAVAILABLE")
        rollback(assignment_id)

    @staticmethod
    def _finalize(registered: RegisteredExecutor, assignment_id: str) -> None:
        if not registered.workspace_mutation:
            return
        finalize = getattr(registered.executor, "finalize", None)
        if finalize is None:
            raise RuntimeError("WORKSPACE_FINALIZE_UNAVAILABLE")
        finalize(assignment_id)

    def _cleanup_completed_workspace_finalizations(
        self,
        *,
        owner: str,
    ) -> tuple[str, ...]:
        """Retry idempotent journal cleanup for already-durable accepted missions."""
        rows = self.db.scalars(
            select(CalyxProgramJob)
            .join(CalyxProgram)
            .join(
                CalyxBrainCompletionWriteback,
                CalyxBrainCompletionWriteback.program_job_id
                == CalyxProgramJob.program_job_id,
            )
            .where(
                CalyxProgram.owner == owner,
                CalyxProgramJob.status == "completed",
                CalyxProgramJob.outcome.in_(tuple(SUCCESSFUL_OUTCOMES)),
                CalyxProgramJob.role_key.in_(
                    tuple(sorted(self.registry.eligible_role_keys))
                ),
            )
        ).all()
        finalized: list[str] = []
        for job in rows:
            registered = self.registry.require_authoritative(job.role_key)
            if not registered.workspace_mutation:
                continue
            self._finalize(registered, job.program_job_id)
            finalized.append(job.program_job_id)
        return tuple(finalized)

    @staticmethod
    def _scheduler_error_result(
        *,
        owner: str,
        worker_id: str,
        attempted: int,
        completed: int,
        retries: int,
        jobs: tuple[AutoMissionJobResult, ...],
        exc: Exception,
    ) -> AutoMissionCycleResult:
        return AutoMissionCycleResult(
            owner,
            worker_id,
            attempted,
            completed,
            retries,
            0,
            "scheduler_invalid",
            jobs,
            {
                "code": str(exc) or type(exc).__name__,
                "exception_type": type(exc).__name__,
            },
        )

    def run_cycle(
        self,
        *,
        owner: str,
        worker_id: str,
        max_jobs: int = 10,
        lease_seconds: int = 600,
        timeout_seconds: int = 300,
    ) -> AutoMissionCycleResult:
        if not owner.strip():
            raise ValueError("AUTONOMY_OWNER_REQUIRED")
        if not worker_id.strip():
            raise ValueError("AUTONOMY_WORKER_ID_REQUIRED")
        if not 1 <= max_jobs <= 50:
            raise ValueError("AUTONOMY_MAX_JOBS_OUT_OF_RANGE")
        if not 60 <= lease_seconds <= 3600:
            raise ValueError("AUTONOMY_LEASE_SECONDS_OUT_OF_RANGE")
        if not 1 <= timeout_seconds <= 3600:
            raise ValueError("AUTONOMY_TIMEOUT_SECONDS_OUT_OF_RANGE")
        if timeout_seconds > lease_seconds:
            raise ValueError("AUTONOMY_TIMEOUT_EXCEEDS_LEASE")

        try:
            self._cleanup_completed_workspace_finalizations(owner=owner)
        except (LookupError, PermissionError, RuntimeError, OSError) as exc:
            self.db.rollback()
            return AutoMissionCycleResult(
                owner,
                worker_id,
                0,
                0,
                0,
                0,
                "finalization_pending",
                (),
                {
                    "code": str(exc) or type(exc).__name__,
                    "exception_type": type(exc).__name__,
                },
            )

        try:
            held = self.worker.hold_governance_bound(
                owner=owner,
                roles=self.registry.eligible_role_keys,
            )
        except (TypeError, ValueError) as exc:
            self.db.rollback()
            return self._scheduler_error_result(
                owner=owner,
                worker_id=worker_id,
                attempted=0,
                completed=0,
                retries=0,
                jobs=(),
                exc=exc,
            )

        results: list[AutoMissionJobResult] = []
        completed_count = retries = attempted = 0
        for _ in range(max_jobs):
            try:
                job = self.worker.claim(
                    worker_id=worker_id,
                    owner=owner,
                    roles=self.registry.eligible_role_keys,
                    lease_seconds=lease_seconds,
                )
            except (TypeError, ValueError) as exc:
                self.db.rollback()
                return self._scheduler_error_result(
                    owner=owner,
                    worker_id=worker_id,
                    attempted=attempted,
                    completed=completed_count,
                    retries=retries,
                    jobs=tuple(results),
                    exc=exc,
                )
            if job is None:
                try:
                    held = self.worker.hold_governance_bound(
                        owner=owner,
                        roles=self.registry.eligible_role_keys,
                    )
                except (TypeError, ValueError) as exc:
                    self.db.rollback()
                    return self._scheduler_error_result(
                        owner=owner,
                        worker_id=worker_id,
                        attempted=attempted,
                        completed=completed_count,
                        retries=retries,
                        jobs=tuple(results),
                        exc=exc,
                    )
                stop_reason = "governance_boundary" if held else "idle"
                return AutoMissionCycleResult(
                    owner,
                    worker_id,
                    attempted,
                    completed_count,
                    retries,
                    len(held),
                    stop_reason,
                    tuple(results),
                )
            attempted += 1
            token = job.lease_token
            if not token:
                return AutoMissionCycleResult(
                    owner,
                    worker_id,
                    attempted,
                    completed_count,
                    retries,
                    len(held),
                    "error",
                    tuple(results),
                    {"code": "CLAIMED_JOB_LEASE_TOKEN_MISSING"},
                )
            registered: RegisteredExecutor | None = None
            assignment: GovernedAssignment | None = None
            try:
                registered = self.registry.require_authoritative(job.role_key)
                assignment = self.assignment_with_feedback(
                    owner=owner,
                    job=job,
                    timeout_seconds=timeout_seconds,
                )
                receipt = registered.executor.execute(assignment)
                self._verify_receipt_binding(
                    registered=registered,
                    assignment=assignment,
                    receipt=receipt,
                )
                self.worker.base.heartbeat(
                    program_job_id=job.program_job_id,
                    worker_id=worker_id,
                    lease_token=token,
                    lease_seconds=lease_seconds,
                )
                self.db.refresh(job)
                decision = self.validator.validate(
                    receipt,
                    attempt_count=job.attempt_count,
                    max_attempts=job.max_attempts,
                )
                event = self.record_validation(
                    job=job,
                    decision=decision,
                    receipt=receipt,
                )
                if decision.disposition in {
                    ValidationDisposition.RETRY,
                    ValidationDisposition.DEAD_LETTER,
                }:
                    self._rollback(registered, assignment.assignment_id)
                    final = self.worker.retry(
                        job=job,
                        worker_id=worker_id,
                        token=token,
                        decision=decision,
                    )
                    retries += int(
                        decision.disposition == ValidationDisposition.RETRY
                    )
                    results.append(
                        AutoMissionJobResult(
                            job.program_job_id,
                            job.program_id,
                            job.job_key,
                            decision.disposition.value,
                            final.outcome,
                            job.attempt_count,
                            receipt.executor_key,
                            decision.code,
                        )
                    )
                    continue
                if decision.disposition == ValidationDisposition.REVIEW_REQUIRED:
                    self._rollback(registered, assignment.assignment_id)
                    final = self._review(
                        job=job,
                        worker_id=worker_id,
                        token=token,
                        receipt=receipt,
                        decision=decision,
                    )
                    results.append(
                        AutoMissionJobResult(
                            job.program_job_id,
                            job.program_id,
                            job.job_key,
                            decision.disposition.value,
                            final.outcome,
                            job.attempt_count,
                            receipt.executor_key,
                            decision.code,
                        )
                    )
                    continue
                final, writeback, released = self.complete_validated(
                    owner=owner,
                    job=job,
                    worker_id=worker_id,
                    token=token,
                    receipt=receipt,
                    event=event,
                )
                completed_count += 1
                results.append(
                    AutoMissionJobResult(
                        job.program_job_id,
                        job.program_id,
                        job.job_key,
                        decision.disposition.value,
                        final.outcome,
                        job.attempt_count,
                        receipt.executor_key,
                        decision.code,
                        writeback.writeback_id,
                        released,
                    )
                )
                try:
                    self._finalize(registered, assignment.assignment_id)
                except (RuntimeError, OSError, PermissionError, ValueError) as exc:
                    # The job/writeback/dependency release are already durable. Never restore
                    # workspace bytes after that point; retry only idempotent journal cleanup.
                    return AutoMissionCycleResult(
                        owner,
                        worker_id,
                        attempted,
                        completed_count,
                        retries,
                        len(held),
                        "finalization_pending",
                        tuple(results),
                        {
                            "code": "WORKSPACE_FINALIZE_PENDING",
                            "detail": str(exc) or type(exc).__name__,
                            "exception_type": type(exc).__name__,
                            "program_job_id": job.program_job_id,
                        },
                    )
            except (
                LookupError,
                PermissionError,
                RuntimeError,
                OSError,
                TypeError,
                ValueError,
            ) as exc:
                rollback_error: Exception | None = None
                try:
                    if assignment is not None:
                        self._rollback(registered, assignment.assignment_id)
                except (LookupError, PermissionError, RuntimeError, OSError, ValueError) as cleanup_exc:
                    rollback_error = cleanup_exc
                finally:
                    self.db.rollback()

                release_error: Exception | None = None
                released_job: CalyxProgramJob | None = None
                try:
                    released_job = self.worker.fail_execution(
                        job=job,
                        worker_id=worker_id,
                        token=token,
                        exc=exc,
                    )
                except (
                    LookupError,
                    PermissionError,
                    RuntimeError,
                    OSError,
                    TypeError,
                    ValueError,
                ) as cleanup_exc:
                    self.db.rollback()
                    release_error = cleanup_exc

                error: dict[str, Any] = {
                    "code": str(exc) or type(exc).__name__,
                    "exception_type": type(exc).__name__,
                    "program_job_id": job.program_job_id,
                    "lease_released": released_job is not None,
                }
                if released_job is not None:
                    error["job_status"] = released_job.status
                    error["retry_scheduled"] = released_job.status == "queued"
                if rollback_error is not None:
                    error["rollback_error"] = (
                        str(rollback_error) or type(rollback_error).__name__
                    )
                if release_error is not None:
                    error["lease_release_error"] = (
                        str(release_error) or type(release_error).__name__
                    )
                return AutoMissionCycleResult(
                    owner,
                    worker_id,
                    attempted,
                    completed_count,
                    retries,
                    len(held),
                    "error",
                    tuple(results),
                    error,
                )
        return AutoMissionCycleResult(
            owner,
            worker_id,
            attempted,
            completed_count,
            retries,
            len(held),
            "budget_exhausted",
            tuple(results),
        )
