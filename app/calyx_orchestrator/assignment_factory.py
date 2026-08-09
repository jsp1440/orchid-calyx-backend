from __future__ import annotations

import json

from sqlalchemy.orm import Session

from .executor import ExecutorCapability, GovernedAssignment
from .isolated_patch_executor import ISOLATED_PATCH_ROLE
from .program_models import CalyxProgram, CalyxProgramJob

SAFE_ASSIGNMENT_CAPABILITIES = (
    ExecutorCapability.VALIDATE_INPUT.value,
    ExecutorCapability.PRODUCE_RECEIPT.value,
    ExecutorCapability.COLLECT_EVIDENCE_URIS.value,
)
ISOLATED_PATCH_CAPABILITIES = (*SAFE_ASSIGNMENT_CAPABILITIES, "workspace_write")
# Durable job identity remains authoritative; persisted inputs may not override these keys.
RESERVED_JOB_INPUT_KEYS = frozenset(
    {
        "program_job_id",
        "job_key",
        "role_key",
        "title",
        "repository",
        "branch",
        "mutating_intent",
        "attempt_count",
    }
)


def _persisted_job_inputs(job: CalyxProgramJob) -> dict[str, object]:
    if not job.input_json:
        return {}
    try:
        value = json.loads(job.input_json)
    except json.JSONDecodeError as exc:
        raise ValueError("PROGRAM_JOB_INPUT_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise TypeError("PROGRAM_JOB_INPUT_JSON_OBJECT_REQUIRED")
    if any(not isinstance(key, str) or not key.strip() for key in value):
        raise ValueError("PROGRAM_JOB_INPUT_KEY_INVALID")
    reserved = sorted(set(value) & RESERVED_JOB_INPUT_KEYS)
    if reserved:
        raise PermissionError(f"PROGRAM_JOB_INPUT_RESERVED_KEY:{','.join(reserved)}")
    return value


def assignment_inputs_for_program_job(
    program: CalyxProgram,
    job: CalyxProgramJob,
) -> dict[str, object]:
    """Build the canonical assignment-input object from durable program/job state."""
    persisted_inputs = _persisted_job_inputs(job)
    isolated_patch = job.role_key == ISOLATED_PATCH_ROLE and bool(job.mutating)
    return {
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
            **persisted_inputs,
        },
        "governance": {
            "mode": (
                "bounded_isolated_workspace_mutation"
                if isolated_patch
                else "bounded_dry_run"
            ),
            "external_execution_authorized": False,
            "repository_code_execution_authorized": False,
            "automatic_merge_authorized": False,
            "deployment_authorized": False,
            "publication_authorized": False,
            "production_graph_mutation_authorized": False,
        },
    }


def assignment_capabilities_for_role(
    role_key: str,
    *,
    mutating_intent: bool,
) -> tuple[str, ...]:
    if role_key == ISOLATED_PATCH_ROLE:
        if not mutating_intent:
            raise PermissionError("ISOLATED_PATCH_MUTATING_JOB_REQUIRED")
        return ISOLATED_PATCH_CAPABILITIES
    return SAFE_ASSIGNMENT_CAPABILITIES


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
    if (
        job.status != "running"
        or not job.lease_owner
        or not job.lease_token
        or not job.lease_expires_at
    ):
        raise PermissionError("LIVE_PROGRAM_JOB_LEASE_REQUIRED")
    if timeout_seconds <= 0:
        raise ValueError("ASSIGNMENT_TIMEOUT_INVALID")

    inputs = assignment_inputs_for_program_job(program, job)
    assignment = GovernedAssignment(
        assignment_id=job.program_job_id,
        program_id=program.program_id,
        job_key=job.job_key,
        role_key=job.role_key,
        objective=job.title,
        inputs=inputs,
        requested_capabilities=assignment_capabilities_for_role(
            job.role_key,
            mutating_intent=bool(job.mutating),
        ),
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
        "repository_code_execution_authorized": False,
    }
