from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from .product_agents import PRODUCT_ROLE_REGISTRY, ProductAgentRole, ProductResult
from .product_program import PRODUCT_DIRECTOR_JOB, PRODUCT_JOB_TEMPLATES
from .program_models import CalyxProgramJob
from .program_repository import PersistentProgramRepository, ProgramJobSpec
from .program_worker import PersistentProgramWorker

PRODUCT_REPOSITORY = "jsp1440/orchid-calyx-backend"


def product_program_specs() -> tuple[list[ProgramJobSpec], list[tuple[str, str]]]:
    templates = (*PRODUCT_JOB_TEMPLATES, PRODUCT_DIRECTOR_JOB)
    jobs = [
        ProgramJobSpec(
            job_key=item.job_key,
            role_key=item.role.value,
            title=item.title,
            repository=PRODUCT_REPOSITORY,
            branch=f"product/{item.domain}",
            mutating=False,
        )
        for item in templates
    ]
    dependencies = [(key, PRODUCT_DIRECTOR_JOB.job_key) for key in PRODUCT_DIRECTOR_JOB.depends_on]
    return jobs, dependencies


def create_product_program(db: Session, *, owner: str, start_immediately: bool = True) -> dict[str, Any]:
    jobs, dependencies = product_program_specs()
    repository = PersistentProgramRepository(db)
    program = repository.create_program(
        owner=owner,
        title="CALYX Phase 3 Product Agents Demonstration",
        objective="Execute eight bounded product readiness jobs, then release one Product Director report.",
        jobs=jobs,
        dependencies=dependencies,
        max_active_jobs=6,
    )
    if start_immediately:
        repository.start(owner=owner, program_id=program.program_id)
    return repository.snapshot(owner=owner, program_id=program.program_id)


def validate_product_payload(*, role_key: str, evidence: dict[str, Any]) -> ProductResult:
    try:
        role = ProductAgentRole(role_key)
    except ValueError as exc:
        raise ValueError("PRODUCT_ROLE_REQUIRED") from exc
    if role not in PRODUCT_ROLE_REGISTRY:
        raise ValueError("PRODUCT_ROLE_REQUIRED")
    dependencies_raw = evidence.get("dependencies", ())
    blockers_raw = evidence.get("blockers", ())
    if not isinstance(dependencies_raw, (list, tuple)):
        raise TypeError("PRODUCT_DEPENDENCIES_INVALID")
    if not isinstance(blockers_raw, (list, tuple)):
        raise TypeError("PRODUCT_BLOCKERS_INVALID")
    result = ProductResult(
        role=role,
        evidence=evidence,
        dependencies=tuple(str(item) for item in dependencies_raw),
        blockers=tuple(str(item) for item in blockers_raw),
        deployment_state=str(evidence.get("deployment_state", "not_requested")),
        requested_action=evidence.get("requested_action"),
    )
    result.validate()
    return result


def complete_product_job(
    db: Session,
    *,
    program_job_id: str,
    worker_id: str,
    lease_token: str,
    outcome: str,
    evidence: dict[str, Any],
    blocker: str | None = None,
    human_action: str | None = None,
) -> CalyxProgramJob:
    worker = PersistentProgramWorker(db)
    job = db.get(CalyxProgramJob, program_job_id)
    if job is None:
        raise LookupError("PROGRAM_JOB_NOT_FOUND")
    if outcome in {"DELIVERED", "NO_OP"}:
        validate_product_payload(role_key=job.role_key, evidence=evidence)
    governed_evidence = dict(evidence)
    governed_evidence["product_payload_hash"] = hashlib.sha256(
        json.dumps(governed_evidence, sort_keys=True, default=str).encode()
    ).hexdigest()
    return worker.complete(
        program_job_id=program_job_id,
        worker_id=worker_id,
        lease_token=lease_token,
        outcome=outcome,
        evidence=governed_evidence,
        blocker=blocker,
        human_action=human_action,
    )
