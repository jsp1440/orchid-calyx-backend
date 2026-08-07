from app.calyx_orchestrator.scheduler import ScheduledState, SchedulerLimits
from app.canonical_brain.build_queue import GovernedBuildQueue
from app.canonical_brain.constitution import BuildAdmissionRequest
from app.canonical_brain.scheduler_bridge import (
    SchedulerJobMetadata,
    project_governed_queue,
    to_scheduled_job,
)


def _request(build_id: str, architecture_id: str = "architecture:brain", **overrides: object) -> BuildAdmissionRequest:
    payload = {
        "build_id": build_id,
        "architecture_id": architecture_id,
        "intent_ids": ["intent:enable-governed-autonomy"],
        "decision_ids": ["decision:brain-canonical-memory"],
        "source_uris": ["brain://scheduler-bridge"],
        "validation_plan_ids": ["validation:scheduler-bridge"],
        "deterministic_outputs": True,
        "preserves_provenance": True,
        "separates_evidence_from_inference": True,
    }
    payload.update(overrides)
    return BuildAdmissionRequest(**payload)


def _metadata(build_id: str, **overrides: object) -> SchedulerJobMetadata:
    payload = {
        "build_id": build_id,
        "role_key": "brain_engineer",
        "repository": "jsp1440/orchid-calyx-backend",
        "created_order": 0,
    }
    payload.update(overrides)
    return SchedulerJobMetadata(**payload)


def _decision(snapshot, build_id: str):
    return next(item for item in snapshot.decisions if item.job_key == build_id)


def test_bridge_preserves_constitutional_blocking() -> None:
    queue = GovernedBuildQueue()
    queue.submit(_request("BUILD-OK"), priority=10)
    queue.submit(_request("BUILD-BLOCKED", merge_requested=True), priority=1)

    snapshot = project_governed_queue(
        queue=queue.snapshot(),
        metadata=(_metadata("BUILD-OK"), _metadata("BUILD-BLOCKED")),
        dependencies=(),
    )

    assert snapshot.runnable_order == ("BUILD-OK",)
    assert _decision(snapshot, "BUILD-BLOCKED").code == "TERMINAL"


def test_bridge_maps_queue_lifecycle_without_losing_outcome_semantics() -> None:
    queue = GovernedBuildQueue()
    queue.submit(_request("BUILD-LIFECYCLE"))
    item = queue.get("BUILD-LIFECYCLE")
    assert item is not None
    assert to_scheduled_job(item, _metadata(item.build_id)).state == ScheduledState.WAITING

    item = queue.transition(item.build_id, "scheduled")
    assert to_scheduled_job(item, _metadata(item.build_id)).state == ScheduledState.QUEUED
    item = queue.transition(item.build_id, "running")
    assert to_scheduled_job(item, _metadata(item.build_id)).state == ScheduledState.RUNNING
    item = queue.transition(item.build_id, "completed")
    scheduled = to_scheduled_job(item, _metadata(item.build_id))
    assert scheduled.state == ScheduledState.COMPLETED
    assert scheduled.outcome == "DELIVERED"


def test_completed_prerequisite_releases_downstream_build() -> None:
    queue = GovernedBuildQueue()
    queue.submit(_request("BUILD-UPSTREAM"))
    queue.transition("BUILD-UPSTREAM", "scheduled")
    queue.transition("BUILD-UPSTREAM", "running")
    queue.transition("BUILD-UPSTREAM", "completed")
    queue.submit(_request("BUILD-DOWNSTREAM"))

    snapshot = project_governed_queue(
        queue=queue.snapshot(),
        metadata=(_metadata("BUILD-UPSTREAM"), _metadata("BUILD-DOWNSTREAM")),
        dependencies=(("BUILD-UPSTREAM", "BUILD-DOWNSTREAM"),),
    )

    assert snapshot.runnable_order == ("BUILD-DOWNSTREAM",)


def test_bridge_uses_existing_mutating_branch_capacity_guard() -> None:
    queue = GovernedBuildQueue()
    queue.submit(_request("BUILD-FIRST"), priority=1)
    queue.submit(_request("BUILD-SECOND"), priority=2)

    metadata = (
        _metadata("BUILD-FIRST", branch="feature/shared", mutating=True),
        _metadata("BUILD-SECOND", branch="feature/shared", mutating=True),
    )
    snapshot = project_governed_queue(
        queue=queue.snapshot(),
        metadata=metadata,
        dependencies=(),
        limits=SchedulerLimits(
            max_global_running=5,
            max_architecture_running=5,
            max_role_running=5,
            max_repository_running=5,
        ),
    )

    assert snapshot.runnable_order == ("BUILD-FIRST",)
    assert _decision(snapshot, "BUILD-SECOND").code == "MUTATING_BRANCH_CAPACITY_REACHED"


def test_bridge_fails_closed_on_missing_or_orphaned_metadata() -> None:
    queue = GovernedBuildQueue()
    queue.submit(_request("BUILD-ONE"))

    try:
        project_governed_queue(queue=queue.snapshot(), metadata=(), dependencies=())
    except ValueError as exc:
        assert str(exc) == "SCHEDULER_BRIDGE_METADATA_MISSING:BUILD-ONE"
    else:
        raise AssertionError("missing metadata must fail closed")

    try:
        project_governed_queue(
            queue=queue.snapshot(),
            metadata=(_metadata("BUILD-ONE"), _metadata("BUILD-ORPHAN")),
            dependencies=(),
        )
    except ValueError as exc:
        assert str(exc) == "SCHEDULER_BRIDGE_METADATA_ORPHANED:BUILD-ORPHAN"
    else:
        raise AssertionError("orphaned metadata must fail closed")


def test_architecture_identifier_is_normalized_for_existing_scheduler() -> None:
    queue = GovernedBuildQueue()
    item = queue.submit(_request("BUILD-ATLAS", architecture_id="architecture:atlas"))
    scheduled = to_scheduled_job(item, _metadata(item.build_id, role_key="atlas_engineer"))
    assert scheduled.architecture == "atlas"
