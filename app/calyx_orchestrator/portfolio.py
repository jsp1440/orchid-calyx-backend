from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .autonomy_policy import program_autonomy_status
from .persisted_scheduler import persisted_schedule_status
from .program_models import CalyxProgram, CalyxProgramDependency, CalyxProgramJob

TERMINAL_STATUSES = {"completed", "blocked", "cancelled"}


def orchestration_portfolio(
    db: Session,
    *,
    owner: str,
    program_id: str | None = None,
    architecture: str | None = None,
) -> dict[str, Any]:
    programs = db.scalars(
        select(CalyxProgram)
        .where(CalyxProgram.owner == owner)
        .order_by(CalyxProgram.created_at.desc(), CalyxProgram.program_id.asc())
    ).all()
    if program_id is not None:
        programs = [program for program in programs if program.program_id == program_id]
        if not programs:
            raise LookupError("PROGRAM_NOT_FOUND")

    program_ids = tuple(program.program_id for program in programs)
    jobs: list[CalyxProgramJob] = []
    dependencies: list[CalyxProgramDependency] = []
    if program_ids:
        jobs = db.scalars(
            select(CalyxProgramJob)
            .where(CalyxProgramJob.program_id.in_(program_ids))
            .order_by(CalyxProgramJob.created_at.asc(), CalyxProgramJob.program_job_id.asc())
        ).all()
        dependencies = db.scalars(
            select(CalyxProgramDependency)
            .where(CalyxProgramDependency.program_id.in_(program_ids))
            .order_by(
                CalyxProgramDependency.program_id.asc(),
                CalyxProgramDependency.upstream_program_job_id.asc(),
                CalyxProgramDependency.downstream_program_job_id.asc(),
            )
        ).all()

    architecture_filter = (architecture or "").strip().casefold()
    if architecture_filter:
        matching_program_ids = {
            program.program_id
            for program in programs
            if architecture_filter in program.title.casefold()
            or architecture_filter in program.objective.casefold()
        }
        matching_program_ids.update(
            job.program_id
            for job in jobs
            if architecture_filter in job.role_key.casefold()
            or architecture_filter in job.repository.casefold()
            or architecture_filter in job.title.casefold()
        )
        programs = [program for program in programs if program.program_id in matching_program_ids]
        jobs = [job for job in jobs if job.program_id in matching_program_ids]
        dependencies = [dep for dep in dependencies if dep.program_id in matching_program_ids]

    by_program: dict[str, list[CalyxProgramJob]] = defaultdict(list)
    for job in jobs:
        by_program[job.program_id].append(job)

    receipt_types: Counter[str] = Counter()
    executor_keys: Counter[str] = Counter()
    evidence_uri_count = 0
    artifact_like_receipts = 0
    for job in jobs:
        evidence = _decode_evidence(job.evidence_json)
        receipt_type = str(evidence.get("receipt_type") or "").strip()
        if receipt_type:
            receipt_types[receipt_type] += 1
        executor_key = str(evidence.get("executor_key") or "").strip()
        if executor_key:
            executor_keys[executor_key] += 1
        evidence_uris = evidence.get("evidence_uris")
        if isinstance(evidence_uris, list):
            evidence_uri_count += len([uri for uri in evidence_uris if isinstance(uri, str) and uri.strip()])
        if evidence.get("output_checksum") or evidence.get("input_checksum"):
            artifact_like_receipts += 1

    blockers = [
        {
            "program_id": job.program_id,
            "program_job_id": job.program_job_id,
            "job_key": job.job_key,
            "role_key": job.role_key,
            "repository": job.repository,
            "branch": job.branch,
            "code": job.blocker or "UNSPECIFIED_BLOCKER",
            "next_action": job.human_action or "Inspect the authoritative job evidence.",
        }
        for job in jobs
        if job.status == "blocked" or job.blocker
    ]

    program_rows = []
    for program in programs:
        program_jobs = by_program.get(program.program_id, [])
        program_blockers = [item for item in blockers if item["program_id"] == program.program_id]
        program_rows.append(
            {
                "program_id": program.program_id,
                "title": program.title,
                "objective": program.objective,
                "status": program.status,
                "paused": program.paused,
                "max_active_jobs": program.max_active_jobs,
                "job_counts": dict(sorted(Counter(job.status for job in program_jobs).items())),
                "outcome_counts": dict(
                    sorted(Counter(job.outcome for job in program_jobs if job.outcome).items())
                ),
                "active_jobs": [
                    _job_summary(job) for job in program_jobs if job.status in {"running", "completing"}
                ],
                "queued_jobs": [_job_summary(job) for job in program_jobs if job.status == "queued"],
                "waiting_jobs": [_job_summary(job) for job in program_jobs if job.status == "waiting"],
                "blockers": program_blockers,
                "created_at": program.created_at.isoformat() if program.created_at else None,
                "completed_at": program.completed_at.isoformat() if program.completed_at else None,
            }
        )

    active_jobs = [job for job in jobs if job.status in {"running", "completing"}]
    terminal_jobs = [job for job in jobs if job.status in TERMINAL_STATUSES]
    exact_actions = sorted({item["next_action"] for item in blockers})

    return {
        "contract": "calyx-orchestration-portfolio-v1",
        "owner": owner,
        "filters": {"program_id": program_id, "architecture": architecture or None},
        "summary": {
            "program_count": len(programs),
            "job_count": len(jobs),
            "dependency_count": len(dependencies),
            "program_status_counts": dict(sorted(Counter(p.status for p in programs).items())),
            "job_status_counts": dict(sorted(Counter(job.status for job in jobs).items())),
            "role_counts": dict(sorted(Counter(job.role_key for job in jobs).items())),
            "repository_counts": dict(sorted(Counter(job.repository for job in jobs).items())),
            "active_jobs": len(active_jobs),
            "terminal_jobs": len(terminal_jobs),
            "blocked_jobs": len(blockers),
        },
        "scheduler": persisted_schedule_status(db, owner=owner),
        "execution": {
            "lease_backed": True,
            "active": [_job_summary(job) for job in active_jobs],
            "receipt_type_counts": dict(sorted(receipt_types.items())),
            "executor_counts": dict(sorted(executor_keys.items())),
            "continuous_worker": program_autonomy_status(),
        },
        "evidence": {
            "artifact_like_receipts": artifact_like_receipts,
            "evidence_uri_count": evidence_uri_count,
            "immutable_artifact_registry_available": True,
            "review_eligibility_available": True,
            "brain_candidate_capture_available": True,
            "persistent_registry_projection": False,
        },
        "governance": {
            "read_only": True,
            "operational_write_controls": False,
            "automatic_merge": False,
            "automatic_deployment": False,
            "scientific_publication": False,
            "taxonomy_activation": False,
            "production_knowledge_graph_mutation": False,
            "human_review_required_for_release": True,
        },
        "blockers": blockers,
        "next_actions": exact_actions,
        "programs": program_rows,
    }


def _job_summary(job: CalyxProgramJob) -> dict[str, Any]:
    return {
        "program_id": job.program_id,
        "program_job_id": job.program_job_id,
        "job_key": job.job_key,
        "title": job.title,
        "role_key": job.role_key,
        "repository": job.repository,
        "branch": job.branch,
        "mutating": job.mutating,
        "status": job.status,
        "outcome": job.outcome,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "lease_owner": job.lease_owner,
        "lease_expires_at": job.lease_expires_at.isoformat() if job.lease_expires_at else None,
        "blocker": job.blocker,
        "human_action": job.human_action,
    }


def _decode_evidence(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {"invalid_evidence": True}
    return payload if isinstance(payload, dict) else {"invalid_evidence": True}
