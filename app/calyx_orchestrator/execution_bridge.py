from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from .executor import ExecutionReceipt, ExecutionState, TerminalOutcome

_DRY_RUN_EXECUTOR_KEY = "deterministic_dry_run_v1"
from .program_models import CalyxProgram, CalyxProgramJob
from .program_worker import PersistentProgramWorker


@dataclass(frozen=True, slots=True)
class CancellationReceipt:
    program_job_id: str
    worker_id: str
    lease_token: str
    reason: str
    outcome: str = "CANCELLED"

    def as_evidence(self) -> dict[str, object]:
        return {
            "receipt_type": "cancellation",
            "program_job_id": self.program_job_id,
            "worker_id": self.worker_id,
            "reason": self.reason,
            "outcome": self.outcome,
        }


class LeaseExecutionBridge:
    """Connects verifiable executor receipts to durable program-job leases."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.worker = PersistentProgramWorker(db)

    def complete_from_receipt(
        self,
        *,
        program_job_id: str,
        worker_id: str,
        lease_token: str,
        receipt: ExecutionReceipt,
    ) -> CalyxProgramJob:
        receipt.verify()
        job, program = self._require_live_lease(
            program_job_id=program_job_id,
            worker_id=worker_id,
            lease_token=lease_token,
        )
        if receipt.assignment_id != program_job_id:
            raise ValueError("RECEIPT_ASSIGNMENT_MISMATCH")
        if receipt.program_id != program.program_id:
            raise ValueError("RECEIPT_PROGRAM_MISMATCH")
        if receipt.job_key != job.job_key:
            raise ValueError("RECEIPT_JOB_KEY_MISMATCH")

        evidence = {
            "receipt_type": "execution",
            "executor_key": receipt.executor_key,
            "state": receipt.state.value,
            "input_checksum": receipt.input_checksum,
            "output_checksum": receipt.output_checksum,
            "output": dict(receipt.output),
            "evidence_uris": list(receipt.evidence_uris),
            "blocker_code": receipt.blocker_code,
        }

        # Dry-run receipts are non-authoritative: a DELIVERED result from the
        # deterministic dry-run executor does not constitute real work and must
        # not propagate program completion.  Reclassify it as BLOCKED so that
        # the job remains open pending genuine human-verified execution.
        effective_state = receipt.state
        effective_outcome = receipt.outcome
        effective_blocker = receipt.blocker_code
        if (
            receipt.executor_key == _DRY_RUN_EXECUTOR_KEY
            and receipt.state == ExecutionState.DELIVERED
        ):
            effective_state = ExecutionState.BLOCKED
            effective_outcome = TerminalOutcome.BLOCKED
            effective_blocker = "DRY_RUN_REQUIRES_HUMAN_REVIEW"
            evidence["dry_run_reclassified"] = True
            evidence["dry_run_blocker_code"] = effective_blocker

        blocker = effective_blocker if effective_state != ExecutionState.DELIVERED else None
        human_action = None
        if effective_state == ExecutionState.TIMED_OUT:
            human_action = "Inspect timeout evidence and submit a bounded governed retry."
        elif effective_state == ExecutionState.BLOCKED:
            human_action = "Resolve the recorded executor blocker before retrying this job."
        elif effective_state == ExecutionState.CANCELLED:
            human_action = "Confirm whether the cancelled job should remain closed or be revised and retried."

        completed = self.worker.complete(
            program_job_id=program_job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            outcome=effective_outcome.value,
            evidence=evidence,
            blocker=blocker,
            human_action=human_action,
        )
        return self._normalize_cancelled_status(completed)

    def cancel(
        self,
        *,
        program_job_id: str,
        worker_id: str,
        lease_token: str,
        reason: str,
    ) -> CalyxProgramJob:
        normalized_reason = reason.strip()
        if not normalized_reason:
            raise ValueError("CANCELLATION_REASON_REQUIRED")
        self._require_live_lease(
            program_job_id=program_job_id,
            worker_id=worker_id,
            lease_token=lease_token,
        )
        receipt = CancellationReceipt(
            program_job_id=program_job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            reason=normalized_reason,
        )
        completed = self.worker.complete(
            program_job_id=program_job_id,
            worker_id=worker_id,
            lease_token=lease_token,
            outcome=receipt.outcome,
            evidence=receipt.as_evidence(),
            blocker="PROGRAM_JOB_CANCELLED",
            human_action="Confirm whether the cancelled job should remain closed or be revised and retried.",
        )
        return self._normalize_cancelled_status(completed)

    def _normalize_cancelled_status(self, job: CalyxProgramJob) -> CalyxProgramJob:
        if job.outcome == "CANCELLED" and job.status != "cancelled":
            job.status = "cancelled"
            self.db.commit()
            self.db.refresh(job)
        return job

    def _require_live_lease(
        self,
        *,
        program_job_id: str,
        worker_id: str,
        lease_token: str,
    ) -> tuple[CalyxProgramJob, CalyxProgram]:
        job = self.db.get(CalyxProgramJob, program_job_id)
        if job is None:
            raise LookupError("PROGRAM_JOB_NOT_FOUND")
        if job.status != "running" or job.lease_owner != worker_id or job.lease_token != lease_token:
            raise PermissionError("STALE_PROGRAM_JOB_LEASE")
        program = self.db.get(CalyxProgram, job.program_id)
        if program is None:
            raise LookupError("PROGRAM_NOT_FOUND")
        return job, program


def decode_receipt_evidence(job: CalyxProgramJob) -> dict[str, object]:
    if not job.evidence_json:
        return {}
    payload = json.loads(job.evidence_json)
    if not isinstance(payload, dict):
        raise TypeError("INVALID_RECEIPT_EVIDENCE")
    return payload
