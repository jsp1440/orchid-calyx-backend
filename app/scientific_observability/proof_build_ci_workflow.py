"""Provider-free end-to-end proof for governed build/CI workflow intelligence.

All observations are labeled development fixtures. The proof records operational
workflow evidence only; it cannot dispatch work or mutate scientific state.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from app.kernel.identity import OCIDFactory, OCIDKind

from .agent_context import build_governed_agent_context
from .mission_control import build_mission_control_snapshot
from .models import (
    ObservationEventType,
    PipelineStage,
    SafeStatus,
    SafeStatusState,
    ScientificObservationEvent,
)
from .ranking import (
    ClassifiedFactor,
    MeasurementClass,
    OpportunityInput,
    RankingFactor,
    score_opportunity,
)
from .runbook import generate_reviewable_runbook
from .service import ObservabilityService
from .store import ObservationStore
from .workflow import (
    WorkflowActorType,
    WorkflowReconstructor,
    WorkflowStage,
    WorkflowState,
    WorkflowType,
    workflow_metadata,
)

FIXTURE = True
ENVIRONMENT = "development"
WORKFLOW_ID = "build-ci-fixture-637"


def _extensions(
    *,
    stage: WorkflowStage,
    previous: WorkflowState | None,
    resulting: WorkflowState,
    retry_count: int = 0,
    evidence_refs: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        **workflow_metadata(
            workflow_id=WORKFLOW_ID,
            workflow_type=WorkflowType.BUILD_CI_VALIDATION,
            stage=stage,
            previous_state=previous,
            resulting_state=resulting,
            actor_type=WorkflowActorType.CI,
            actor_id="github-actions-fixture",
            retry_count=retry_count,
            evidence_refs=evidence_refs,
        ),
        "environment": ENVIRONMENT,
        "fixture": True,
    }


def build_fixture_events() -> list[ScientificObservationEvent]:
    correlation = OCIDFactory.new(OCIDKind.EVENT)
    base = datetime(2026, 9, 12, 14, 0, tzinfo=timezone.utc)
    definitions = [
        (WorkflowStage.QUEUE, None, WorkflowState.QUEUED, 0, (), SafeStatusState.OK),
        (
            WorkflowStage.EXECUTE,
            WorkflowState.QUEUED,
            WorkflowState.RUNNING,
            0,
            (),
            SafeStatusState.OK,
        ),
        (
            WorkflowStage.VALIDATE,
            WorkflowState.RUNNING,
            WorkflowState.FAILED,
            0,
            (),
            SafeStatusState.ERROR,
        ),
        (
            WorkflowStage.EXECUTE,
            WorkflowState.FAILED,
            WorkflowState.RUNNING,
            1,
            (),
            SafeStatusState.OK,
        ),
        (
            WorkflowStage.VALIDATE,
            WorkflowState.RUNNING,
            WorkflowState.RUNNING,
            1,
            ("commit:exact-head-637",),
            SafeStatusState.OK,
        ),
        (
            WorkflowStage.COMPLETE,
            WorkflowState.RUNNING,
            WorkflowState.COMPLETED,
            1,
            ("commit:exact-head-637", "artifact:ci-receipt-637"),
            SafeStatusState.OK,
        ),
    ]

    events: list[ScientificObservationEvent] = []
    parent = None
    for sequence, (stage, previous, resulting, retry, evidence, safe_state) in enumerate(
        definitions, start=1
    ):
        event = ScientificObservationEvent(
            event_type=ObservationEventType.API_CONTRACT_PRODUCED,
            pipeline_stage=PipelineStage.API_PRODUCER,
            component="app/scientific_observability/proof_build_ci_workflow.py",
            correlation_id=correlation,
            parent_event_id=parent,
            sequence=sequence,
            occurred_at=base + timedelta(seconds=sequence),
            recorded_at=base + timedelta(seconds=sequence),
            mission_id="WFI-001",
            run_id="fixture-build-ci-637",
            safe_status=SafeStatus(
                status=safe_state,
                reason_code=(
                    "FIXTURE_VALIDATION_FAILED"
                    if resulting is WorkflowState.FAILED
                    else "FIXTURE_WORKFLOW_OBSERVED"
                ),
            ),
            extensions=_extensions(
                stage=stage,
                previous=previous,
                resulting=resulting,
                retry_count=retry,
                evidence_refs=evidence,
            ),
        )
        events.append(event)
        parent = event.event_id
    return events


def _validate_fixture_boundary(events: list[ScientificObservationEvent]) -> None:
    if not events:
        raise ValueError("workflow proof requires events")
    environments = {event.extensions.get("environment") for event in events}
    if environments != {ENVIRONMENT}:
        raise ValueError("cross-environment workflow proof refused")
    if not all(event.extensions.get("fixture") is True for event in events):
        raise ValueError("unlabeled workflow proof input refused")


def _trusted_fixture_ranking(reconstruction: dict[str, Any]) -> dict[str, Any]:
    source = "review:fixture-policy-637"
    factors = {
        RankingFactor.FREQUENCY: ClassifiedFactor(
            MeasurementClass.UNAVAILABLE, None
        ),
        RankingFactor.MANUAL_TIME: ClassifiedFactor(
            MeasurementClass.UNAVAILABLE, None
        ),
        RankingFactor.RETRY_REWORK_RATE: ClassifiedFactor(
            MeasurementClass.CALCULATED,
            min(
                (
                    reconstruction["retry_count"]
                    + reconstruction["rework_count"]
                )
                / len(reconstruction["stages"]),
                1.0,
            ),
            "event:fixture-build-ci-637",
        ),
        RankingFactor.DEPENDENCY_READINESS: ClassifiedFactor(
            MeasurementClass.CALCULATED, 1.0, "commit:exact-head-637"
        ),
        RankingFactor.REVERSIBILITY: ClassifiedFactor(
            MeasurementClass.CALCULATED, 1.0, source
        ),
        RankingFactor.SCIENTIFIC_GOVERNANCE_RISK: ClassifiedFactor(
            MeasurementClass.CALCULATED, 0.1, source
        ),
        RankingFactor.DATA_COMPLETENESS: ClassifiedFactor(
            MeasurementClass.CALCULATED, 1.0, "artifact:ci-receipt-637"
        ),
    }
    return score_opportunity(
        OpportunityInput(
            opportunity_id="workflow:build-ci-fixture-637",
            workflow_id=WORKFLOW_ID,
            factors=factors,
        )
    )


def run_proof(
    events: list[ScientificObservationEvent] | None = None,
) -> dict[str, Any]:
    """Run the labeled fixture twice and return deterministic proof evidence."""

    fixture_events = events or build_fixture_events()
    _validate_fixture_boundary(fixture_events)
    store = ObservationStore()
    service = ObservabilityService(store)

    first = [service.record(event) for event in fixture_events]
    replay = [service.record(event) for event in fixture_events]
    correlation_id = str(fixture_events[0].correlation_id)
    reconstruction = WorkflowReconstructor(store).reconstruct(correlation_id)
    ranking = _trusted_fixture_ranking(reconstruction)
    context = build_governed_agent_context(reconstruction, ranking)
    runbook = generate_reviewable_runbook(reconstruction, context)
    snapshot = build_mission_control_snapshot(store)

    return {
        "contract_version": "workflow-intelligence-e2e-proof-v1",
        "FIXTURE": FIXTURE,
        "environment": ENVIRONMENT,
        "workflow_id": WORKFLOW_ID,
        "events": {
            "unique": len(store),
            "expected": len(fixture_events),
            "first_created": all(result.created for result in first),
            "replay_noop": all(not result.created for result in replay),
        },
        "reconstruction": reconstruction,
        "ranking": ranking,
        "context": context,
        "runbook": runbook,
        "mission_control": snapshot,
        "proof": {
            "failure_retry_recovery": (
                any(
                    stage["resulting_state"] == "failed"
                    for stage in reconstruction["stages"]
                )
                and reconstruction["retry_count"] == 1
                and reconstruction["rework_count"] >= 1
                and reconstruction["current_state"] == "completed"
            ),
            "completion_evidence_present": bool(reconstruction["evidence_refs"]),
            "no_unresolved_findings": reconstruction["findings"] == [],
            "ranking_preserves_unavailable": (
                "frequency" in ranking["unavailable_factors"]
                and "manual_time" in ranking["unavailable_factors"]
            ),
            "context_is_terminal": context["status"] == "TERMINAL",
            "runbook_review_required": (
                runbook["generated"] is True
                and runbook["review_required"] is True
                and runbook["approved"] is False
                and runbook["authoritative"] is False
            ),
            "one_mission_control_workflow": (
                snapshot["workflow_count"] == 1
                and snapshot["workflows"][0]["workflow_id"] == WORKFLOW_ID
            ),
            "no_authority": all(
                value is False
                for value in (
                    context["dispatch_authority"],
                    context["credential_authority"],
                    context["mutation_authority"],
                    context["publication_authority"],
                    context["spending_authority"],
                    runbook["dispatch_authority"],
                    runbook["mutation_authority"],
                    runbook["publication_authority"],
                    runbook["spending_authority"],
                    snapshot["dispatch_authority"],
                    snapshot["mutation_authority"],
                    snapshot["publication_authority"],
                    snapshot["spending_authority"],
                )
            ),
        },
    }


if __name__ == "__main__":  # pragma: no cover
    print(json.dumps(run_proof(), indent=2, default=str))
