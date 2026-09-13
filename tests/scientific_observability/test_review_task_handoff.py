"""SCI-OBS-004 — anomaly persistence into the canonical review service."""

from __future__ import annotations

import json

from app.review_tasks.repository import MemoryReviewTaskRepository
from app.review_tasks.service import GovernedReviewTaskService
from app.scientific_observability.models import (
    ObservationEventType,
    PipelineStage,
    SafeStatus,
    SafeStatusState,
    ScientificObservationEvent,
)
from app.scientific_observability.service import ObservabilityService
from app.scientific_observability.store import ObservationStore


def _protected_locality_event() -> ScientificObservationEvent:
    return ScientificObservationEvent(
        event_type=ObservationEventType.EVIDENCE_ASSERTION_CREATED,
        pipeline_stage=PipelineStage.TAXONOMY_EVIDENCE_RESOLUTION,
        component="app/evidence_aggregation",
        safe_status=SafeStatus(
            status=SafeStatusState.OK,
            reason_code="ASSERTION_CREATED",
        ),
        source={"source_id": "partner", "source_anchor_id": "sealed-anchor"},
        extensions={
            "latitude": 19.4326,
            "longitude": -99.1332,
            "exact_locality": "sealed ravine",
            "country": "Mexico",
        },
    )


def test_anomaly_handoff_persists_once_and_stays_sealed_on_replay() -> None:
    repository = MemoryReviewTaskRepository()
    review_service = GovernedReviewTaskService(repository=repository)
    observability = ObservabilityService(
        ObservationStore(),
        review_service=review_service,
    )
    event = _protected_locality_event()

    first = observability.record(event)
    second = observability.record(event)

    locality_tasks = [
        task
        for task in repository.list_tasks()
        if task["review_type"]
        == "SCI_OBS_ANOMALY:PROTECTED_LOCALITY_EXPOSURE"
    ]
    assert len(locality_tasks) == 1
    task = locality_tasks[0]
    assert task["batch_key"].endswith(
        f":{event.event_id}:PROTECTED_LOCALITY_EXPOSURE"
    )
    assert task["embargoed"] is True
    assert task["display_policy"] == "SEALED_PARTNER"
    assert task["metadata"]["authoritative_state_mutated"] is False

    serialized = json.dumps(task, sort_keys=True)
    assert "sealed ravine" not in serialized
    assert "19.4326" not in serialized
    assert "-99.1332" not in serialized

    first_projection = first.to_dict()["persisted_review_tasks"]
    second_projection = second.to_dict()["persisted_review_tasks"]
    assert first_projection[0]["reused"] is False
    assert any(
        item["review_type"]
        == "SCI_OBS_ANOMALY:PROTECTED_LOCALITY_EXPOSURE"
        and item["reused"] is True
        for item in second_projection
    )


def test_handoff_is_explicit_and_does_not_create_a_parallel_queue() -> None:
    event = _protected_locality_event()
    result = ObservabilityService(ObservationStore()).record(event)

    assert result.review_bindings
    assert result.persisted_review_tasks == []
