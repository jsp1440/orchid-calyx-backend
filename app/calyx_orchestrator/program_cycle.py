from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .assignment_factory import governed_assignment_from_claimed_job
from .execution_bridge import LeaseExecutionBridge
from .executor_registry import AuthoritativeExecutorRegistry, RegisteredExecutor
from .persisted_scheduler import project_persisted_schedule
from .program_models import CalyxProgramJob
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
    # Machine-readable reason for any cycle that completed zero jobs. Built
    # only from existing contracts (ClaimDiagnostic, scheduler decision codes,
    # executor-registry and executor failure codes); None when work completed.
    zero_execution: dict[str, Any] | None = None

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
            "zero_execution": (
                None if self.zero_execution is None else dict(self.zero_execution)
            ),
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


def _zero_execution_reason(
    db: Session,
    *,
    owner: str,
    eligible_role_keys: frozenset[str],
    stop_reason: str,
    error: dict[str, Any] | None,
    failures: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    """Read-only explanation for a cycle that completed zero jobs.

    Reuses existing codes only: cycle error codes, executor failure codes,
    ``PersistentProgramWorker.diagnose`` outcomes, the registry's
    ``AUTHORITATIVE_EXECUTOR_NOT_REGISTERED`` and persisted-scheduler decision
    codes. Takes no lease and commits nothing.
    """
    record: dict[str, Any] = {
        "stop_reason": stop_reason,
        "reason_code": None,
        "source": None,
        "claim_diagnostic": None,
        "scheduler_codes": {},
        "unregistered_runnable_roles": [],
        "eligible_role_keys": sorted(eligible_role_keys),
        "failure_codes": [str(item.get("code")) for item in failures],
    }
    schedule_error: str | None = None
    try:
        diagnostic = PersistentProgramWorker(db).diagnose(
            owner=owner,
            allowed_role_keys=eligible_role_keys,
        )
        record["claim_diagnostic"] = {
            "outcome": diagnostic.outcome,
            "program_job_id": diagnostic.program_job_id,
            "reason_code": diagnostic.reason_code,
            "reason_message": diagnostic.reason_message,
        }
        try:
            schedule = project_persisted_schedule(db, owner=owner)
        except ValueError as exc:
            schedule_error = str(exc) or type(exc).__name__
            schedule = None
        if schedule is not None:
            codes: dict[str, int] = {}
            for decision in schedule.snapshot.decisions:
                if decision.code in {"RUNNABLE", "TERMINAL"}:
                    continue
                codes[decision.code] = codes.get(decision.code, 0) + 1
            record["scheduler_codes"] = dict(sorted(codes.items()))
            runnable_ids = schedule.runnable_program_job_ids
            if runnable_ids:
                roles = db.scalars(
                    select(CalyxProgramJob.role_key).where(
                        CalyxProgramJob.program_job_id.in_(runnable_ids)
                    )
                ).all()
                record["unregistered_runnable_roles"] = sorted(
                    {role for role in roles if role not in eligible_role_keys}
                )
    except Exception as exc:  # noqa: BLE001 - diagnosis must not mask the cycle result
        db.rollback()
        record["reason_code"] = "ZERO_EXECUTION_DIAGNOSIS_FAILED"
        record["source"] = "diagnosis"
        record["diagnosis_error"] = type(exc).__name__
        if error is not None:
            record["reason_code"] = str(error.get("code"))
            record["source"] = "cycle_error"
        return record

    claim = record["claim_diagnostic"]
    if error is not None:
        record["reason_code"], record["source"] = str(error.get("code")), "cycle_error"
    elif failures:
        record["reason_code"] = str(failures[-1].get("code"))
        record["source"] = "executor_failure"
    elif claim and claim["outcome"] == "REJECTED_ADMISSION":
        record["reason_code"], record["source"] = (
            claim["reason_code"],
            "claim_admission",
        )
    elif record["unregistered_runnable_roles"]:
        record["reason_code"] = "AUTHORITATIVE_EXECUTOR_NOT_REGISTERED"
        record["source"] = "executor_registry"
    elif record["scheduler_codes"]:
        codes = record["scheduler_codes"]
        record["reason_code"] = max(sorted(codes), key=lambda code: codes[code])
        record["source"] = "scheduler"
    elif schedule_error is not None:
        record["reason_code"], record["source"] = schedule_error, "schedule_projection"
    else:
        record["reason_code"] = claim["outcome"] if claim else "IDLE_NO_CANDIDATE"
        record["source"] = "claim_diagnostic"
    return record


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
    executor_registry = registry or AuthoritativeExecutorRegistry()
    result = _run_cycle(
        db,
        owner=owner,
        worker_id=worker_id,
        max_jobs=max_jobs,
        lease_seconds=lease_seconds,
        timeout_seconds=timeout_seconds,
        executor_registry=executor_registry,
    )
    if result.completed_jobs:
        return result
    return replace(
        result,
        zero_execution=_zero_execution_reason(
            db,
            owner=result.owner,
            eligible_role_keys=executor_registry.eligible_role_keys,
            stop_reason=result.stop_reason,
            error=result.error,
            failures=result.failures,
        ),
    )


def _run_cycle(
    db: Session,
    *,
    owner: str,
    worker_id: str,
    max_jobs: int,
    lease_seconds: int,
    timeout_seconds: int,
    executor_registry: AuthoritativeExecutorRegistry,
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
    # No unbounded renewal loop. Reserve execution plus settlement time using
    # the existing fenced heartbeat, which cannot revive an expired lease.
    execution_lease_seconds = max(lease_seconds, timeout_seconds + 30)
    if execution_lease_seconds > 3600:
        raise ValueError("AUTONOMY_EXECUTION_LEASE_BUDGET_OUT_OF_RANGE")

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
            job = worker.heartbeat(
                program_job_id=job.program_job_id,
                worker_id=normalized_worker,
                lease_token=token,
                lease_seconds=execution_lease_seconds,
            )
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
