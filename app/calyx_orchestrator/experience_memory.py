from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .program_models import CalyxProgram, CalyxProgramDependency, CalyxProgramJob
from .program_repository import PersistentProgramRepository

SCHEMA_VERSION = "calyx-experience-memory/1"
SUCCESSFUL_OUTCOMES = frozenset({"DELIVERED", "NO_OP"})


def _canonical_hash(value: object) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat()


def _decode_json_object(value: str | None) -> tuple[dict[str, Any], bool]:
    if not value:
        return {}, False
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return {}, True
    if not isinstance(decoded, dict):
        return {}, True
    return decoded, False


def _receipt_summary(job: CalyxProgramJob) -> dict[str, Any]:
    evidence, invalid = _decode_json_object(job.evidence_json)
    if invalid:
        return {
            "present": bool(job.evidence_json),
            "invalid": True,
            "evidence_payload_sha256": (
                hashlib.sha256(job.evidence_json.encode("utf-8")).hexdigest()
                if job.evidence_json
                else None
            ),
            "receipt_type": None,
            "executor_key": None,
            "state": None,
            "input_checksum": None,
            "output_checksum": None,
            "evidence_uris": [],
            "blocker_code": None,
        }

    evidence_uris = evidence.get("evidence_uris")
    if not isinstance(evidence_uris, list):
        evidence_uris = []
    normalized_uris = sorted(
        {
            item.strip()
            for item in evidence_uris
            if isinstance(item, str) and item.strip()
        }
    )
    return {
        "present": bool(evidence),
        "invalid": False,
        "evidence_payload_sha256": _canonical_hash(evidence) if evidence else None,
        "receipt_type": evidence.get("receipt_type"),
        "executor_key": evidence.get("executor_key"),
        "state": evidence.get("state"),
        "input_checksum": evidence.get("input_checksum"),
        "output_checksum": evidence.get("output_checksum"),
        "evidence_uris": normalized_uris,
        "blocker_code": evidence.get("blocker_code"),
        # Deliberately retain only the shape/hash of executor output, not its body.
        "output_keys": (
            sorted(str(key) for key in evidence["output"])
            if isinstance(evidence.get("output"), dict)
            else []
        ),
    }


def _job_experience(job: CalyxProgramJob) -> dict[str, Any]:
    receipt = _receipt_summary(job)
    recovered_after_retry = bool(
        job.outcome in SUCCESSFUL_OUTCOMES and job.attempt_count > 1
    )
    return {
        "experience_node_id": f"experience:program:{job.program_id}:job:{job.program_job_id}",
        "program_job_id": job.program_job_id,
        "job_key": job.job_key,
        "role_key": job.role_key,
        "title": job.title,
        "repository": job.repository,
        "branch": job.branch,
        "mutating": bool(job.mutating),
        "work_fingerprint": job.work_fingerprint,
        "orchestrator_job_id": job.orchestrator_job_id,
        "status": job.status,
        "outcome": job.outcome,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "recovered_after_retry": recovered_after_retry,
        "blocker": job.blocker,
        "human_action": job.human_action,
        "created_at": _iso(job.created_at),
        "updated_at": _iso(job.updated_at),
        "completed_at": _iso(job.completed_at),
        "receipt": receipt,
        "authority": "durable_execution_observation",
        "scientific_source_evidence": False,
        "can_change_policy": False,
        "can_change_permissions": False,
    }


def _lesson_id(
    program_id: str,
    lesson_type: str,
    evidence_refs: Iterable[str],
    applicability: Mapping[str, Any],
) -> str:
    return "experience-lesson:" + _canonical_hash(
        {
            "program_id": program_id,
            "lesson_type": lesson_type,
            "evidence_refs": sorted(evidence_refs),
            "applicability": dict(applicability),
        }
    )


def _lesson(
    *,
    program_id: str,
    lesson_type: str,
    observation: str,
    evidence_refs: Iterable[str],
    applicability: Mapping[str, Any],
) -> dict[str, Any]:
    refs = sorted(set(evidence_refs))
    bounds = dict(applicability)
    return {
        "lesson_id": _lesson_id(program_id, lesson_type, refs, bounds),
        "lesson_type": lesson_type,
        "observation": observation,
        "evidence_refs": refs,
        "applicability": bounds,
        "confidence": 1.0,
        "confidence_semantics": "confidence_that_observed_pattern_occurred_not_predictive_success",
        "authority": "non_authoritative_lesson_candidate",
        "may_inform_planning": True,
        "may_rewrite_policy": False,
        "may_expand_permissions": False,
        "may_trigger_deployment": False,
        "may_publish_scientific_claim": False,
    }


def _lesson_candidates(
    program: CalyxProgram, jobs: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    lessons: list[dict[str, Any]] = []
    for job in jobs:
        ref = job["experience_node_id"]
        applicability = {
            "role_key": job["role_key"],
            "repository": job["repository"],
            "mutating": job["mutating"],
        }
        outcome = job["outcome"]
        if outcome == "DELIVERED":
            lessons.append(
                _lesson(
                    program_id=program.program_id,
                    lesson_type="successful_execution_pattern",
                    observation=(
                        f"Role {job['role_key']} delivered job {job['job_key']} "
                        f"after {job['attempt_count']} recorded attempt(s)."
                    ),
                    evidence_refs=(ref,),
                    applicability=applicability,
                )
            )
        elif outcome == "NO_OP":
            lessons.append(
                _lesson(
                    program_id=program.program_id,
                    lesson_type="no_op_pattern",
                    observation=(
                        f"Job {job['job_key']} terminated as NO_OP; equivalent future "
                        "work may warrant an early no-op check."
                    ),
                    evidence_refs=(ref,),
                    applicability=applicability,
                )
            )
        if job["recovered_after_retry"]:
            lessons.append(
                _lesson(
                    program_id=program.program_id,
                    lesson_type="recovery_after_retry",
                    observation=(
                        f"Job {job['job_key']} delivered after multiple attempts; the "
                        "recorded execution path demonstrates recovery was possible."
                    ),
                    evidence_refs=(ref,),
                    applicability=applicability,
                )
            )
        if job["blocker"]:
            lessons.append(
                _lesson(
                    program_id=program.program_id,
                    lesson_type="persistent_blocker",
                    observation=(
                        f"Job {job['job_key']} recorded blocker {job['blocker']!r}."
                    ),
                    evidence_refs=(ref,),
                    applicability=applicability,
                )
            )
        if job["human_action"]:
            lessons.append(
                _lesson(
                    program_id=program.program_id,
                    lesson_type="human_escalation_required",
                    observation=(
                        f"Job {job['job_key']} recorded an explicit human-action boundary."
                    ),
                    evidence_refs=(ref,),
                    applicability=applicability,
                )
            )
        if job["blocker"] == "UPSTREAM_JOB_FAILED":
            lessons.append(
                _lesson(
                    program_id=program.program_id,
                    lesson_type="dependency_failure_propagation",
                    observation=(
                        f"Job {job['job_key']} was blocked because an upstream dependency failed."
                    ),
                    evidence_refs=(ref,),
                    applicability=applicability,
                )
            )
    lessons.sort(key=lambda item: item["lesson_id"])
    return lessons


def project_program_experience(
    program: CalyxProgram,
    jobs: Iterable[CalyxProgramJob],
    dependencies: Iterable[CalyxProgramDependency],
) -> dict[str, Any]:
    """Project durable program execution state into governed institutional memory."""

    ordered_jobs = sorted(jobs, key=lambda item: (item.created_at, item.program_job_id))
    by_id = {job.program_job_id: job.job_key for job in ordered_jobs}
    job_memory = [_job_experience(job) for job in ordered_jobs]

    dep_memory = [
        {
            "dependency_id": dep.dependency_id,
            "upstream_program_job_id": dep.upstream_program_job_id,
            "downstream_program_job_id": dep.downstream_program_job_id,
            "upstream": by_id.get(dep.upstream_program_job_id),
            "downstream": by_id.get(dep.downstream_program_job_id),
        }
        for dep in dependencies
    ]
    dep_memory.sort(key=lambda item: item["dependency_id"])

    lessons = _lesson_candidates(program, job_memory)
    evidence_uris = sorted(
        {
            uri
            for job in job_memory
            for uri in job["receipt"]["evidence_uris"]
        }
    )
    executor_keys = sorted(
        {
            str(job["receipt"]["executor_key"])
            for job in job_memory
            if job["receipt"]["executor_key"]
        }
    )
    outcome_counts: dict[str, int] = {}
    for job in job_memory:
        key = str(job["outcome"] or "PENDING")
        outcome_counts[key] = outcome_counts.get(key, 0) + 1

    memory_core = {
        "schema_version": SCHEMA_VERSION,
        "program_id": program.program_id,
        "title": program.title,
        "objective": program.objective,
        "status": program.status,
        "paused": bool(program.paused),
        "cancellation_reason": program.cancellation_reason,
        "max_active_jobs": program.max_active_jobs,
        "created_at": _iso(program.created_at),
        "updated_at": _iso(program.updated_at),
        "completed_at": _iso(program.completed_at),
        "jobs": job_memory,
        "dependencies": dep_memory,
        "outcome_counts": outcome_counts,
        "executor_keys": executor_keys,
        "validation_evidence_uris": evidence_uris,
        "lesson_candidates": lessons,
    }
    return {
        **memory_core,
        "experience_fingerprint": _canonical_hash(memory_core),
        "experience_node_id": f"experience:program:{program.program_id}",
        "authority": "non_authoritative_experience_memory",
        "learning_boundary": {
            "may_inform_future_planning": True,
            "automatic_policy_rewrite": False,
            "automatic_permission_expansion": False,
            "automatic_production_action": False,
            "scientific_source_evidence": False,
            "private_chain_of_thought_stored": False,
        },
    }


def load_program_experience(
    db: Session, *, owner: str, program_id: str
) -> dict[str, Any]:
    """Load one owner-scoped program and project its durable experience memory."""

    # Existing snapshot lookup is the canonical ownership boundary.
    PersistentProgramRepository(db).snapshot(owner=owner, program_id=program_id)
    program = db.get(CalyxProgram, program_id)
    if program is None:
        raise LookupError("PROGRAM_NOT_FOUND")
    jobs = db.scalars(
        select(CalyxProgramJob)
        .where(CalyxProgramJob.program_id == program_id)
        .order_by(CalyxProgramJob.created_at.asc())
    ).all()
    dependencies = db.scalars(
        select(CalyxProgramDependency).where(
            CalyxProgramDependency.program_id == program_id
        )
    ).all()
    return project_program_experience(program, jobs, dependencies)
