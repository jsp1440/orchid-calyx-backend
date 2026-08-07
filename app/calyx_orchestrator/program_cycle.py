from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy.orm import Session

from .assignment_factory import governed_assignment_from_claimed_job
from .execution_bridge import LeaseExecutionBridge
from .executor_registry import AuthoritativeExecutorRegistry
from .program_worker import PersistentProgramWorker


@dataclass(frozen=True, slots=True)
class CycleJobResult:
    program_job_id: str
    program_id: str
    job_key: str
    outcome: str | None
    receipt_state: str
    executor_key: str
    workspace_mutation: bool = False
    repository_code_execution: bool = False


@dataclass(frozen=True, slots=True)
class AutonomousCycleResult:
    owner: str
    worker_id: str
    attempted_jobs: int
    completed_jobs: int
    stop_reason: str
    jobs: tuple[CycleJobResult, ...]
    error: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "worker_id": self.worker_id,
            "attempted_jobs": self.attempted_jobs,
            "completed_jobs": self.completed_jobs,
            "stop_reason": self.stop_reason,
            "jobs": [asdict(item) for item in self.jobs],
            "error": self.error,
            "mode": "registered_authoritative_adapters_only",
            "workspace_mutation_performed": any(item.workspace_mutation for item in self.jobs),
            "repository_code_execution_performed": any(
                item.repository_code_execution for item in self.jobs
            ),
            "external_side_effects": [],
            "automatic_merge": False,
            "automatic_deployment": False,
            "automatic_publication": False,
            "production_knowledge_graph_mutation": False,
        }


def run_deterministic_program_cycle(
    db: Session,
    *,
    owner: str,
    worker_id: str,
    max_jobs: int = 10,
    lease_seconds: int = 300,
    timeout_seconds: int = 300,
    registry: AuthoritativeExecutorRegistry | None = None,
) -> AutonomousCycleResult:
    normalized_owner = owner.strip()
    normalized_worker = worker_id.strip()
    if not normalized_owner:
        raise ValueError("AUTONOMY_OWNER_REQUIRED")
    if not normalized_worker:
        raise ValueError("AUTONOMY_WORKER_ID_REQUIRED")
    if not 1 <= max_jobs <= 50:
        raise ValueError("AUTONOMY_MAX_JOBS_OUT_OF_RANGE")
    if not 60 <= lease_seconds <= 3600:
        raise ValueError("AUTONOMY_LEASE_SECONDS_OUT_OF_RANGE")
    if not 1 <= timeout_seconds <= 3600:
        raise ValueError("AUTONOMY_TIMEOUT_SECONDS_OUT_OF_RANGE")

    executor_registry = registry or AuthoritativeExecutorRegistry()
    worker = PersistentProgramWorker(db)
    completed: list[CycleJobResult] = []
    attempted = 0
    for _ in range(max_jobs):
        job = worker.claim(
            worker_id=normalized_worker,
            lease_seconds=lease_seconds,
            owner=normalized_owner,
            allowed_role_keys=executor_registry.eligible_role_keys,
        )
        if job is None:
            return AutonomousCycleResult(
                owner=normalized_owner,
                worker_id=normalized_worker,
                attempted_jobs=attempted,
                completed_jobs=len(completed),
                stop_reason="idle",
                jobs=tuple(completed),
            )
        attempted += 1
        token = job.lease_token
        if not token:
            db.rollback()
            return AutonomousCycleResult(
                owner=normalized_owner,
                worker_id=normalized_worker,
                attempted_jobs=attempted,
                completed_jobs=len(completed),
                stop_reason="error",
                jobs=tuple(completed),
                error={
                    "code": "CLAIMED_JOB_LEASE_TOKEN_MISSING",
                    "program_job_id": job.program_job_id,
                },
            )
        try:
            registered = executor_registry.require_authoritative(job.role_key)
            assignment = governed_assignment_from_claimed_job(
                db,
                owner=normalized_owner,
                job=job,
                timeout_seconds=timeout_seconds,
            )
            receipt = registered.executor.execute(assignment)
            receipt.verify()
            completed_job = LeaseExecutionBridge(db).complete_from_receipt(
                program_job_id=job.program_job_id,
                worker_id=normalized_worker,
                lease_token=token,
                receipt=receipt,
            )
        except (LookupError, PermissionError, RuntimeError, TypeError, ValueError) as exc:
            db.rollback()
            return AutonomousCycleResult(
                owner=normalized_owner,
                worker_id=normalized_worker,
                attempted_jobs=attempted,
                completed_jobs=len(completed),
                stop_reason="error",
                jobs=tuple(completed),
                error={
                    "code": str(exc) or type(exc).__name__,
                    "exception_type": type(exc).__name__,
                    "program_job_id": job.program_job_id,
                    "program_id": job.program_id,
                    "job_key": job.job_key,
                },
            )
        completed.append(
            CycleJobResult(
                program_job_id=job.program_job_id,
                program_id=job.program_id,
                job_key=job.job_key,
                outcome=completed_job.outcome,
                receipt_state=receipt.state.value,
                executor_key=receipt.executor_key,
                workspace_mutation=registered.workspace_mutation,
                repository_code_execution=registered.repository_code_execution,
            )
        )

    return AutonomousCycleResult(
        owner=normalized_owner,
        worker_id=normalized_worker,
        attempted_jobs=attempted,
        completed_jobs=len(completed),
        stop_reason="budget_exhausted",
        jobs=tuple(completed),
    )
