"""WFI-001 bounded workflow reconstruction tests."""

from __future__ import annotations

from copy import deepcopy

import pytest

from app.kernel.identity import OCIDFactory, OCIDKind
from app.scientific_observability.models import (
    ObservationEventType,
    PipelineStage,
    ScientificObservationEvent,
)
from app.scientific_observability.store import ObservationStore
from app.scientific_observability.workflow import (
    CONTRACT_VERSION,
    WorkflowActorType,
    WorkflowReconstructor,
    WorkflowStage,
    WorkflowState,
    WorkflowType,
    WorkflowValidationError,
    parse_workflow_metadata,
    workflow_metadata,
)


def _event(
    *,
    correlation_id,
    sequence: int,
    stage: WorkflowStage,
    previous_state: WorkflowState | None,
    resulting_state: WorkflowState,
    retry_count: int = 0,
    evidence_refs: tuple[str, ...] = (),
    blocker_refs: tuple[str, ...] = (),
    extra_extensions: dict | None = None,
) -> ScientificObservationEvent:
    extensions = workflow_metadata(
        workflow_id="harvest-fixture-001",
        workflow_type=WorkflowType.SOURCE_INGESTION,
        stage=stage,
        previous_state=previous_state,
        resulting_state=resulting_state,
        actor_type=WorkflowActorType.WORKER,
        actor_id="harvest-worker",
        retry_count=retry_count,
        evidence_refs=evidence_refs,
        blocker_refs=blocker_refs,
    )
    extensions.update(extra_extensions or {})
    return ScientificObservationEvent(
        event_type=ObservationEventType.HARVEST_RUN_STARTED,
        pipeline_stage=PipelineStage.ACQUISITION,
        component="app/harvest/manager.py",
        correlation_id=correlation_id,
        sequence=sequence,
        extensions=extensions,
    )


def test_metadata_contract_is_closed_and_bounded():
    event = _event(
        correlation_id=OCIDFactory.new(OCIDKind.EVENT),
        sequence=1,
        stage=WorkflowStage.ACQUIRE,
        previous_state=None,
        resulting_state=WorkflowState.RUNNING,
    ).to_dict()
    assert parse_workflow_metadata(event).workflow_id == "harvest-fixture-001"
    assert event["extensions"]["workflow"]["contract_version"] == CONTRACT_VERSION

    event["extensions"]["workflow"]["raw_prompt"] = "do something unsafe"
    with pytest.raises(WorkflowValidationError, match="unsupported fields"):
        parse_workflow_metadata(event)


def test_illegal_transition_fails_closed():
    store = ObservationStore()
    correlation_id = OCIDFactory.new(OCIDKind.EVENT)
    event = _event(
        correlation_id=correlation_id,
        sequence=1,
        stage=WorkflowStage.COMPLETE,
        previous_state=None,
        resulting_state=WorkflowState.COMPLETED,
    )
    store.append(event.to_dict())

    with pytest.raises(WorkflowValidationError, match="illegal workflow transition"):
        WorkflowReconstructor(store).reconstruct(str(correlation_id))


def test_persisted_reconstruction_exposes_retry_rework_and_missing_evidence():
    store = ObservationStore()
    correlation_id = OCIDFactory.new(OCIDKind.EVENT)
    events = [
        _event(
            correlation_id=correlation_id,
            sequence=1,
            stage=WorkflowStage.ACQUIRE,
            previous_state=None,
            resulting_state=WorkflowState.RUNNING,
        ),
        _event(
            correlation_id=correlation_id,
            sequence=2,
            stage=WorkflowStage.NORMALIZE,
            previous_state=WorkflowState.RUNNING,
            resulting_state=WorkflowState.FAILED,
            blocker_refs=("issue:577",),
        ),
        _event(
            correlation_id=correlation_id,
            sequence=3,
            stage=WorkflowStage.NORMALIZE,
            previous_state=WorkflowState.FAILED,
            resulting_state=WorkflowState.RUNNING,
            retry_count=1,
        ),
        _event(
            correlation_id=correlation_id,
            sequence=4,
            stage=WorkflowStage.VERIFY,
            previous_state=WorkflowState.RUNNING,
            resulting_state=WorkflowState.COMPLETED,
        ),
    ]
    for event in reversed(events):
        store.append(event.to_dict())

    before = deepcopy(store.all())
    result = WorkflowReconstructor(store).reconstruct(str(correlation_id))

    assert [stage["sequence"] for stage in result["stages"]] == [1, 2, 3, 4]
    assert result["current_state"] == "completed"
    assert result["retry_count"] == 1
    assert result["rework_count"] == 1
    assert result["blocker_refs"] == ["issue:577"]
    assert [finding["reason_code"] for finding in result["findings"]] == [
        "MISSING_COMPLETION_EVIDENCE"
    ]
    assert result["authoritative_state_mutated"] is False
    assert result["publication_authority"] is False
    assert store.all() == before


def test_existing_append_idempotency_and_redaction_remain_in_force():
    store = ObservationStore()
    correlation_id = OCIDFactory.new(OCIDKind.EVENT)
    event = _event(
        correlation_id=correlation_id,
        sequence=1,
        stage=WorkflowStage.ACQUIRE,
        previous_state=None,
        resulting_state=WorkflowState.RUNNING,
        evidence_refs=("artifact:harvest-manifest-001",),
        extra_extensions={
            "latitude": 12.345,
            "api_key": "secret-value",
        },
    )

    stored, created, report = store.append(event.to_dict())
    replayed, created_again, _ = store.append(event.to_dict())

    assert created is True
    assert created_again is False
    assert replayed == stored
    assert len(store) == 1
    assert "latitude" not in stored["extensions"]
    assert stored["extensions"]["api_key"] == "__REDACTED__"
    assert report.protected_locality_detected is True

    result = WorkflowReconstructor(store).reconstruct(str(correlation_id))
    assert result["evidence_refs"] == ["artifact:harvest-manifest-001"]
