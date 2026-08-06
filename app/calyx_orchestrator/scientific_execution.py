from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from .program_repository import PersistentProgramRepository, ProgramJobSpec
from .program_worker import PersistentProgramWorker
from .scientific_agents import SCIENTIFIC_ROLE_REGISTRY, ScientificAgentRole, ScientificResult
from .scientific_program import CHIEF_SCIENTIST_JOB, SCIENTIFIC_JOB_TEMPLATES

SCIENTIFIC_REPOSITORY = "jsp1440/orchid-calyx-backend"


@dataclass(frozen=True, slots=True)
class ScientificWorkIdentity:
    domain: str
    role: ScientificAgentRole
    template_key: str

    @property
    def fingerprint(self) -> str:
        payload = f"{self.domain}|{self.role.value}|{self.template_key}"
        return hashlib.sha256(payload.encode()).hexdigest()


def scientific_program_specs() -> tuple[list[ProgramJobSpec], list[tuple[str, str]]]:
    templates = (*SCIENTIFIC_JOB_TEMPLATES, CHIEF_SCIENTIST_JOB)
    jobs = [
        ProgramJobSpec(
            job_key=item.job_key,
            role_key=item.role.value,
            title=item.title,
            repository=SCIENTIFIC_REPOSITORY,
            branch=f"scientific/{item.domain}",
            mutating=False,
        )
        for item in templates
    ]
    dependencies = [(key, CHIEF_SCIENTIST_JOB.job_key) for key in CHIEF_SCIENTIST_JOB.depends_on]
    return jobs, dependencies


def create_scientific_program(db: Session, *, owner: str, start_immediately: bool = True) -> dict[str, Any]:
    jobs, dependencies = scientific_program_specs()
    repository = PersistentProgramRepository(db)
    program = repository.create_program(
        owner=owner,
        title="CALYX Phase 2 Scientific and Data Agent Demonstration",
        objective="Execute ten bounded scientific and data audits, then release one Chief Scientist report.",
        jobs=jobs,
        dependencies=dependencies,
        max_active_jobs=6,
    )
    if start_immediately:
        repository.start(owner=owner, program_id=program.program_id)
    return repository.snapshot(owner=owner, program_id=program.program_id)


def validate_scientific_payload(*, role_key: str, evidence: dict[str, Any]) -> ScientificResult:
    try:
        role = ScientificAgentRole(role_key)
    except ValueError as exc:
        raise ValueError("SCIENTIFIC_ROLE_REQUIRED") from exc
    if role not in SCIENTIFIC_ROLE_REGISTRY:
        raise ValueError("SCIENTIFIC_ROLE_REQUIRED")
    provenance_raw = evidence.get("provenance")
    if not isinstance(provenance_raw, list | tuple) or not provenance_raw:
        raise ValueError("PROVENANCE_REQUIRED")
    contradictions_raw = evidence.get("contradictions", ())
    if not isinstance(contradictions_raw, list | tuple):
        raise ValueError("CONTRADICTIONS_INVALID")
    confidence = evidence.get("confidence")
    result = ScientificResult(
        role=role,
        canonical_taxon_identity=evidence.get("canonical_taxon_identity"),
        provenance=tuple(str(item) for item in provenance_raw),
        evidence=evidence,
        contradictions=tuple(str(item) for item in contradictions_raw),
        confidence=float(confidence) if confidence is not None else None,
        requested_action=evidence.get("requested_action"),
    )
    result.validate()
    return result


def complete_scientific_job(
    db: Session,
    *,
    program_job_id: str,
    worker_id: str,
    lease_token: str,
    outcome: str,
    evidence: dict[str, Any],
    blocker: str | None = None,
    human_action: str | None = None,
):
    worker = PersistentProgramWorker(db)
    job = db.get(__import__("app.calyx_orchestrator.program_models", fromlist=["CalyxProgramJob"]).CalyxProgramJob, program_job_id)
    if job is None:
        raise LookupError("PROGRAM_JOB_NOT_FOUND")
    if outcome in {"DELIVERED", "NO_OP"}:
        validate_scientific_payload(role_key=job.role_key, evidence=evidence)
    evidence = dict(evidence)
    evidence["scientific_payload_hash"] = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, default=str).encode()
    ).hexdigest()
    return worker.complete(
        program_job_id=program_job_id,
        worker_id=worker_id,
        lease_token=lease_token,
        outcome=outcome,
        evidence=evidence,
        blocker=blocker,
        human_action=human_action,
    )
