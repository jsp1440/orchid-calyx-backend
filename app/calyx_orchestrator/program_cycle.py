from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy.orm import Session

from .assignment_factory import governed_assignment_from_claimed_job
from .execution_bridge import LeaseExecutionBridge
from .executor_registry import AuthoritativeExecutorRegistry, RegisteredExecutor
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
    # Executor failures this cycle released (with retry backoff or to dead
    # letter) and then continued past.
    failures: tuple[dict[str, Any], ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "owner": self.owner,
            "worker_id": self.worker_id,
            "attempted_jobs": self.attempted_jobs,
            "completed_jobs": self.completed_jobs,
            "failed_jobs": len(self.failures),
            "stop_reason": self.stop_reason,
            "jobs": [asdict(item) for item in self.jobs],
            "error": self.error,
            "failures": [dict(item) for item in self.failures],
            "mode": "registered_authoritative_adapters_only",
            "workspace_mutation_performed": any(
                item.workspace_mutation for item in self.jobs
            ),
            "repository_code_execution_performed": any(
                item.repository_code_execution for item in self.jobs
            ),
            "external_side_effects": [],
            "automatic_merge": False,
            "automatic_deployment": False,
            "automatic_publication": False,
            "production_knowledge_graph_mutation": False,
        }


def _rollback_workspace_mutation(
    registered: RegisteredExecutor | None,
    assignment_id: str,
) -> str | None:
    if registered is None or not registered.workspace_mutation:
        return None
    rollback = getattr(registered.executor, "rollback", None)
    if rollback is None:
        return "WORKSPACE_ROLLBACK_UNAVAILABLE"
    try:
        rollback(assignment_id)
    except Exception as exc:  # noqa: BLE001 - fail closed across executor boundary
        return f"WORKSPACE_ROLLBACK_FAILED:{type(exc).__name__}:{exc}"
    return None


def _finalize_workspace_mutation(
    registered: RegisteredExecutor,
    assignment_id: str,
) -> None:
    if not registered.workspace_mutation:
        return
    finalize = getattr(registered.executor, "finalize", None)
    if finalize is None:
        raise RuntimeError("WORKSPACE_FINALIZE_UNAVAILABLE")
    finalize(assignment_id)


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
    failures: list[dict[str, Any]] = []
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
                failures=tuple(failures),
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
                failures=tuple(failures),
            )
        registered: RegisteredExecutor | None = None
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
            _finalize_workspace_mutation(registered, assignment.assignment_id)
        except Exception as exc:  # noqa: BLE001 - executor boundary
            # Any ordinary exception from an executor (for example a provider
            # SDK's ConnectionError) is a job failure: release and back off,
            # then continue. BaseException (KeyboardInterrupt, SystemExit,
            # GeneratorExit) is deliberately not caught and still propagates.
            rollback_error = _rollback_workspace_mutation(
                registered,
                job.program_job_id,
            )
            db.rollback()
            error_code = str(exc) or type(exc).__name__
            if rollback_error:
                error_code = rollback_error
            failure: dict[str, Any] = {
                "code": error_code,
                "exception_type": type(exc).__name__,
                "program_job_id": job.program_job_id,
                "program_id": job.program_id,
                "job_key": job.job_key,
                "workspace_rollback": (
                    "failed" if rollback_error else "completed_or_not_required"
                ),
            }
            # Release the lease now rather than letting it run to expiry. The
            # job is retried only after an exponential, capped backoff, and
            # dead-lettered once its attempts are exhausted.
            try:
                released = worker.release_failed_attempt(
                    program_job_id=job.program_job_id,
                    worker_id=normalized_worker,
                    lease_token=token,
                    error_code=error_code,
                    exception_type=type(exc).__name__,
                )
            except (LookupError, PermissionError) as release_exc:
                failure["disposition"] = "lease_release_failed"
                failure["release_error"] = (
                    str(release_exc) or type(release_exc).__name__
                )
                return AutonomousCycleResult(
                    owner=normalized_owner,
                    worker_id=normalized_worker,
                    attempted_jobs=attempted,
                    completed_jobs=len(completed),
                    stop_reason="error",
                    jobs=tuple(completed),
                    error=failure,
                    failures=tuple(failures),
                )
            failure["disposition"] = (
                "dead_letter" if released.outcome == "DEAD_LETTER" else "retry_backoff"
            )
            failure["attempt_count"] = released.attempt_count
            failures.append(failure)
            if rollback_error:
                # The workspace may still hold the failed mutation. Fail closed:
                # do not run further jobs against it in this cycle.
                return AutonomousCycleResult(
                    owner=normalized_owner,
                    worker_id=normalized_worker,
                    attempted_jobs=attempted,
                    completed_jobs=len(completed),
                    stop_reason="error",
                    jobs=tuple(completed),
                    error=failure,
                    failures=tuple(failures),
                )
            continue
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
        failures=tuple(failures),
    )
