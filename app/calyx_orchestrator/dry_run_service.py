from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from .assignment_factory import assignment_payload, governed_assignment_from_claimed_job
from .execution_bridge import LeaseExecutionBridge
from .executor import DeterministicDryRunExecutor, ExecutionReceipt
from .models import utcnow
from .program_models import CalyxProgram, CalyxProgramJob


@dataclass(frozen=True, slots=True)
class DryRunExecutionResult:
    assignment: dict[str, object]
    receipt: dict[str, object]
    completed_job: dict[str, object]


def require_owned_program_job(
    db: Session,
    *,
    owner: str,
    program_job_id: str,
) -> CalyxProgramJob:
    job = db.get(CalyxProgramJob, program_job_id)
    if job is None:
        raise LookupError("PROGRAM_JOB_NOT_FOUND")
    program = db.get(CalyxProgram, job.program_id)
    if program is None or program.owner != owner:
        raise LookupError("PROGRAM_JOB_NOT_FOUND")
    return job


def execute_deterministic_dry_run(
    db: Session,
    *,
    owner: str,
    program_job_id: str,
    worker_id: str,
    lease_token: str,
    timeout_seconds: int = 300,
) -> DryRunExecutionResult:
    job = require_owned_program_job(db, owner=owner, program_job_id=program_job_id)
    if (
        job.status != "running"
        or job.lease_owner != worker_id
        or job.lease_token != lease_token
        or _lease_is_expired(job.lease_expires_at)
    ):
        raise PermissionError("STALE_PROGRAM_JOB_LEASE")

    assignment = governed_assignment_from_claimed_job(
        db,
        owner=owner,
        job=job,
        timeout_seconds=timeout_seconds,
    )
    receipt = DeterministicDryRunExecutor().execute(assignment)
    receipt.verify()
    completed = LeaseExecutionBridge(db).complete_from_receipt(
        program_job_id=program_job_id,
        worker_id=worker_id,
        lease_token=lease_token,
        receipt=receipt,
    )
    return DryRunExecutionResult(
        assignment=assignment_payload(assignment),
        receipt=_receipt_payload(receipt),
        completed_job={
            "program_job_id": completed.program_job_id,
            "program_id": completed.program_id,
            "job_key": completed.job_key,
            "status": completed.status,
            "outcome": completed.outcome,
            "blocker": completed.blocker,
            "human_action": completed.human_action,
        },
    )


def _lease_is_expired(expires_at: datetime | None) -> bool:
    if expires_at is None:
        return True
    now = utcnow()
    if expires_at.tzinfo is None and now.tzinfo is not None:
        now = now.replace(tzinfo=None)
    elif expires_at.tzinfo is not None and now.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=None)
    return expires_at <= now


def _receipt_payload(receipt: ExecutionReceipt) -> dict[str, object]:
    return {
        "assignment_id": receipt.assignment_id,
        "program_id": receipt.program_id,
        "job_key": receipt.job_key,
        "executor_key": receipt.executor_key,
        "state": receipt.state.value,
        "outcome": receipt.outcome.value,
        "input_checksum": receipt.input_checksum,
        "output_checksum": receipt.output_checksum,
        "output": dict(receipt.output),
        "evidence_uris": list(receipt.evidence_uris),
        "blocker_code": receipt.blocker_code,
    }
