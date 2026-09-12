from __future__ import annotations

from datetime import datetime, timezone

from app.kernel.identity import OCIDFactory, OCIDKind
from app.scientific_observability.mission_control import build_mission_control_snapshot
from app.scientific_observability.models import (
    ObservationEventType,
    PipelineStage,
    SafeStatus,
    SafeStatusState,
    ScientificObservationEvent,
)
from app.scientific_observability.store import ObservationStore
from app.scientific_observability.workflow import (
    WorkflowActorType,
    WorkflowStage,
    WorkflowState,
    WorkflowType,
    workflow_metadata,
)


def _event(
    *,
    event_id: str,
    correlation_id: str,
    sequence: int,
    previous: WorkflowState | None,
    resulting: WorkflowState,
    stage: WorkflowStage,
    evidence: list[str] | None = None,
) -> ScientificObservationEvent:
    return ScientificObservationEvent(
        event_id=event_id,
        correlation_id=correlation_id,
        sequence=sequence,
        occurred_at=datetime(2026, 9, 12, sequence, tzinfo=timezone.utc),
        recorded_at=datetime(2026, 9, 12, sequence, tzinfo=timezone.utc),
        event_type=ObservationEventType.API_CONTRACT_PRODUCED,
        pipeline_stage=PipelineStage.API_PRODUCER,
        component="app/scientific_observability",
        safe_status=SafeStatus(status=SafeStatusState.OK),
        extensions=workflow_metadata(
            workflow_id="workflow-test",
            workflow_type=WorkflowType.BUILD_CI_VALIDATION,
            stage=stage,
            previous_state=previous,
            resulting_state=resulting,
            actor_type=WorkflowActorType.SERVICE,
            actor_id="ci",
            evidence_refs=evidence or [],
        ),
    )


def test_snapshot_is_bounded_deterministic_and_preserves_unavailable() -> None:
    store = ObservationStore()
    correlation = str(OCIDFactory.new(OCIDKind.EVENT))
    first = str(OCIDFactory.new(OCIDKind.EVENT))
    second = str(OCIDFactory.new(OCIDKind.EVENT))
    store.append(
        _event(
            event_id=first,
            correlation_id=correlation,
            sequence=1,
            previous=None,
            resulting=WorkflowState.RUNNING,
            stage=WorkflowStage.VALIDATE,
        ).to_dict()
    )
    store.append(
        _event(
            event_id=second,
            correlation_id=correlation,
            sequence=2,
            previous=WorkflowState.RUNNING,
            resulting=WorkflowState.COMPLETED,
            stage=WorkflowStage.COMPLETE,
            evidence=["commit:abc123"],
        ).to_dict()
    )

    first_snapshot = build_mission_control_snapshot(store)
    second_snapshot = build_mission_control_snapshot(store)

    assert first_snapshot == second_snapshot
    assert first_snapshot["workflow_count"] == 1
    item = first_snapshot["workflows"][0]
    assert item["display_state"] == "TERMINAL"
    assert item["stale"] == {"classification": "UNAVAILABLE", "value": None}
    assert item["ranking"]["score"] is None
    assert "scientific_governance_risk" in item["ranking"]["unavailable_factors"]
    assert item["runbook"] is None
    assert item["capability_state"] == "BACKEND_ONLY"
    assert first_snapshot["dispatch_authority"] is False
    assert first_snapshot["publication_authority"] is False


def test_snapshot_ignores_non_workflow_events_without_inventing_work() -> None:
    store = ObservationStore()
    event = ScientificObservationEvent(
        event_type=ObservationEventType.EVIDENCE_ASSERTION_CREATED,
        pipeline_stage=PipelineStage.API_PRODUCER,
        component="app/scientific_observability",
    )
    store.append(event.to_dict())

    snapshot = build_mission_control_snapshot(store)

    assert snapshot["workflow_count"] == 0
    assert snapshot["workflows"] == []
