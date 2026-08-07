from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.calyx_orchestrator.scheduler import (
    DependencyScheduler,
    ScheduledJob,
    ScheduledState,
    SchedulerLimits,
    SchedulerSnapshot,
)

from .build_queue import BuildQueueItem, BuildQueueSnapshot


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SchedulerJobMetadata(StrictModel):
    build_id: str = Field(min_length=3)
    role_key: str = Field(min_length=1)
    repository: str = Field(min_length=1)
    created_order: int = Field(default=0, ge=0)
    branch: str | None = None
    mutating: bool = False


def _architecture_key(architecture_id: str) -> str:
    prefix = "architecture:"
    return architecture_id[len(prefix) :] if architecture_id.startswith(prefix) else architecture_id


def _state_and_outcome(item: BuildQueueItem) -> tuple[ScheduledState, str | None]:
    mapping: dict[str, tuple[ScheduledState, str | None]] = {
        "admitted": (ScheduledState.WAITING, None),
        "blocked": (ScheduledState.BLOCKED, "BLOCKED"),
        "scheduled": (ScheduledState.QUEUED, None),
        "running": (ScheduledState.RUNNING, None),
        "completed": (ScheduledState.COMPLETED, "DELIVERED"),
        "cancelled": (ScheduledState.CANCELLED, "CANCELLED"),
    }
    return mapping[item.status]


def to_scheduled_job(item: BuildQueueItem, metadata: SchedulerJobMetadata) -> ScheduledJob:
    if item.build_id != metadata.build_id:
        raise ValueError("SCHEDULER_BRIDGE_BUILD_ID_MISMATCH")
    state, outcome = _state_and_outcome(item)
    return ScheduledJob(
        job_key=item.build_id,
        role_key=metadata.role_key,
        architecture=_architecture_key(item.architecture_id),
        repository=metadata.repository,
        priority=item.priority,
        created_order=metadata.created_order,
        state=state,
        outcome=outcome,
        branch=metadata.branch,
        mutating=metadata.mutating,
    )


def project_governed_queue(
    *,
    queue: BuildQueueSnapshot,
    metadata: tuple[SchedulerJobMetadata, ...],
    dependencies: tuple[tuple[str, str], ...],
    limits: SchedulerLimits | None = None,
) -> SchedulerSnapshot:
    metadata_by_build = {record.build_id: record for record in metadata}
    if len(metadata_by_build) != len(metadata):
        raise ValueError("DUPLICATE_SCHEDULER_BRIDGE_METADATA")

    queue_ids = {item.build_id for item in queue.items}
    metadata_ids = set(metadata_by_build)
    missing = sorted(queue_ids - metadata_ids)
    extra = sorted(metadata_ids - queue_ids)
    if missing:
        raise ValueError(f"SCHEDULER_BRIDGE_METADATA_MISSING:{','.join(missing)}")
    if extra:
        raise ValueError(f"SCHEDULER_BRIDGE_METADATA_ORPHANED:{','.join(extra)}")

    jobs = tuple(
        to_scheduled_job(item, metadata_by_build[item.build_id])
        for item in sorted(queue.items, key=lambda record: record.build_id)
    )
    return DependencyScheduler().project(
        jobs=jobs,
        dependencies=dependencies,
        limits=limits,
    )
