from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .program_models import CalyxProgram, CalyxProgramDependency, CalyxProgramJob
from .scheduler import (
    DependencyScheduler,
    ScheduledDecision,
    ScheduledJob,
    ScheduledState,
    SchedulerLimits,
    SchedulerSnapshot,
)

GLOBAL_PROGRAM_JOB_LIMIT = 6
ROLE_PROGRAM_JOB_LIMIT = 2
REPOSITORY_PROGRAM_JOB_LIMIT = 2


@dataclass(frozen=True, slots=True)
class PersistedSchedule:
    snapshot: SchedulerSnapshot
    job_ids_by_schedule_key: dict[str, str]
    schedule_keys_by_job_id: dict[str, str]
    program_ids_by_schedule_key: dict[str, str]
    job_keys_by_schedule_key: dict[str, str]

    @property
    def runnable_program_job_ids(self) -> tuple[str, ...]:
        return tuple(self.job_ids_by_schedule_key[key] for key in self.snapshot.runnable_order)


def _schedule_key(job: CalyxProgramJob) -> str:
    return f"{job.program_id}:{job.job_key}"


def _scheduled_state(status: str) -> ScheduledState:
    try:
        return ScheduledState(status)
    except ValueError as exc:
        raise ValueError(f"UNSUPPORTED_PERSISTED_JOB_STATUS:{status}") from exc


def project_persisted_schedule(db: Session, *, owner: str | None = None) -> PersistedSchedule:
    program_query = select(CalyxProgram).where(CalyxProgram.status == "running", CalyxProgram.paused.is_(False))
    if owner is not None:
        program_query = program_query.where(CalyxProgram.owner == owner)
    programs = db.scalars(program_query.order_by(CalyxProgram.created_at.asc(), CalyxProgram.program_id.asc())).all()
    if not programs:
        empty = DependencyScheduler().project(jobs=(), dependencies=())
        return PersistedSchedule(empty, {}, {}, {}, {})

    program_by_id = {program.program_id: program for program in programs}
    program_ids = tuple(program_by_id)
    jobs = db.scalars(
        select(CalyxProgramJob)
        .where(CalyxProgramJob.program_id.in_(program_ids))
        .order_by(CalyxProgramJob.created_at.asc(), CalyxProgramJob.program_job_id.asc())
    ).all()
    dependencies = db.scalars(
        select(CalyxProgramDependency)
        .where(CalyxProgramDependency.program_id.in_(program_ids))
        .order_by(CalyxProgramDependency.created_at.asc(), CalyxProgramDependency.dependency_id.asc())
    ).all()

    job_by_id = {job.program_job_id: job for job in jobs}
    schedule_jobs: list[ScheduledJob] = []
    ids_by_key: dict[str, str] = {}
    keys_by_id: dict[str, str] = {}
    program_ids_by_key: dict[str, str] = {}
    job_keys_by_key: dict[str, str] = {}
    for created_order, job in enumerate(jobs):
        key = _schedule_key(job)
        ids_by_key[key] = job.program_job_id
        keys_by_id[job.program_job_id] = key
        program_ids_by_key[key] = job.program_id
        job_keys_by_key[key] = job.job_key
        schedule_jobs.append(
            ScheduledJob(
                job_key=key,
                role_key=job.role_key,
                architecture=job.program_id,
                repository=job.repository,
                created_order=created_order,
                state=_scheduled_state(job.status),
                outcome=job.outcome,
                branch=job.branch,
                mutating=job.mutating,
            )
        )

    schedule_dependencies: list[tuple[str, str]] = []
    for dependency in dependencies:
        upstream = job_by_id.get(dependency.upstream_program_job_id)
        downstream = job_by_id.get(dependency.downstream_program_job_id)
        if upstream is None or downstream is None:
            raise ValueError("PERSISTED_SCHEDULE_DEPENDENCY_JOB_NOT_FOUND")
        if upstream.program_id != dependency.program_id or downstream.program_id != dependency.program_id:
            raise ValueError("PERSISTED_SCHEDULE_DEPENDENCY_PROGRAM_MISMATCH")
        schedule_dependencies.append((_schedule_key(upstream), _schedule_key(downstream)))

    limits = SchedulerLimits(
        max_global_running=GLOBAL_PROGRAM_JOB_LIMIT,
        max_architecture_running=GLOBAL_PROGRAM_JOB_LIMIT,
        max_role_running=ROLE_PROGRAM_JOB_LIMIT,
        max_repository_running=REPOSITORY_PROGRAM_JOB_LIMIT,
        architecture_limits={program_id: program.max_active_jobs for program_id, program in program_by_id.items()},
    )
    snapshot = DependencyScheduler().project(
        jobs=tuple(schedule_jobs),
        dependencies=tuple(schedule_dependencies),
        limits=limits,
    )
    return PersistedSchedule(
        snapshot=snapshot,
        job_ids_by_schedule_key=ids_by_key,
        schedule_keys_by_job_id=keys_by_id,
        program_ids_by_schedule_key=program_ids_by_key,
        job_keys_by_schedule_key=job_keys_by_key,
    )


def persisted_schedule_status(db: Session, *, owner: str) -> dict[str, object]:
    try:
        schedule = project_persisted_schedule(db, owner=owner)
    except ValueError as exc:
        return {
            "ready": False,
            "error": str(exc),
            "runnable_order": [],
            "decisions": [],
        }

    decisions = [_decision_payload(schedule, decision) for decision in schedule.snapshot.decisions]
    return {
        "ready": True,
        "error": None,
        "runnable_order": [
            {
                "program_job_id": schedule.job_ids_by_schedule_key[key],
                "program_id": schedule.program_ids_by_schedule_key[key],
                "job_key": schedule.job_keys_by_schedule_key[key],
            }
            for key in schedule.snapshot.runnable_order
        ],
        "running_counts": schedule.snapshot.running_counts,
        "decisions": decisions,
        "worker_claim_enforced": True,
        "production_activation": False,
    }


def _decision_payload(schedule: PersistedSchedule, decision: ScheduledDecision) -> dict[str, object]:
    key = decision.job_key
    return {
        "program_job_id": schedule.job_ids_by_schedule_key[key],
        "program_id": schedule.program_ids_by_schedule_key[key],
        "job_key": schedule.job_keys_by_schedule_key[key],
        "runnable": decision.runnable,
        "rank": decision.rank,
        "critical_path_depth": decision.critical_path_depth,
        "blocked_by": [schedule.job_keys_by_schedule_key[parent] for parent in decision.blocked_by],
        "code": decision.code,
    }
