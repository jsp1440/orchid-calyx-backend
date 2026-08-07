from __future__ import annotations

from sqlalchemy.orm import Session

from .executor import ExecutorCapability, GovernedAssignment
from .program_models import CalyxProgram, CalyxProgramJob

SAFE_ASSIGNMENT_CAPABILITIES = (
    ExecutorCapability.VALIDATE_INPUT.value,
    ExecutorCapability.PRODUCE_RECEIPT.value,
    ExecutorCapability.COLLECT_EVIDENCE_URIS.value,
)


def governed_assignment_from_claimed_job(
    db: Session,
    *,
    owner: str,
    job: CalyxProgramJob,
    timeout_seconds: int = 300,
) -> GovernedAssignment:
    program = db.get(CalyxProgram, job.program_id)
    if program is None or program.owner != owner:
        raise LookupError("PROGRAM_NOT_FOUND")
    if program.status != "running" or program.paused:
        raise PermissionError("PROGRAM_NOT_EXECUTABLE")
    if job.status != "running" or not job.lease_owner or not job.lease_token or not job.lease_expires_at:
        raise PermissionError("LIVE_PROGRAM_JOB_LEASE_REQUIRED")
    if timeout_seconds <= 0:
        raise ValueError("ASSIGNMENT_TIMEOUT_INVALID")

    inputs = {
        "program": {
            "program_id": program.program_id,
            "title": program.title,
            "objective": program.objective,
        },
        "job": {
            "program_job_id": job.program_job_id,
            "job_key": job.job_key,
            "role_key": job.role_key,
            "title": job.title,
            "repository": job.repository,
            "branch": job.branch,
            "mutating_intent": bool(job.mutating),
            "attempt_count": job.attempt_count,
        },
        "governance": {
            "mode": "bounded_dry_run",
            "external_execution_authorized": False,
            "automatic_merge_authorized": False,
            "deployment_authorized": False,
            "publication_authorized": False,
            "production_graph_mutation_authorized": False,
        },
    }
    assignment = GovernedAssignment(
        assignment_id=job.program_job_id,
        program_id=program.program_id,
        job_key=job.job_key,
        role_key=job.role_key,
        objective=job.title,
        inputs=inputs,
        requested_capabilities=SAFE_ASSIGNMENT_CAPABILITIES,
        evidence_uris=(
            f"calyx:program/{program.program_id}",
            f"calyx:program-job/{job.program_job_id}",
        ),
        timeout_seconds=timeout_seconds,
    )
    assignment.verified_input_checksum()
    return assignment


def assignment_payload(assignment: GovernedAssignment) -> dict[str, object]:
    return {
        "assignment_id": assignment.assignment_id,
        "program_id": assignment.program_id,
        "job_key": assignment.job_key,
        "role_key": assignment.role_key,
        "objective": assignment.objective,
        "inputs": dict(assignment.inputs),
        "requested_capabilities": list(assignment.requested_capabilities),
        "evidence_uris": list(assignment.evidence_uris),
        "timeout_seconds": assignment.timeout_seconds,
        "cancelled": assignment.cancelled,
        "input_checksum": assignment.verified_input_checksum(),
        "external_execution_authorized": False,
    }
