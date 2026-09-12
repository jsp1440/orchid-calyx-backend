"""Provider-free Mission Control snapshot over canonical workflow evidence."""

from __future__ import annotations

from typing import Any

from .agent_context import ContextValidationError, build_governed_agent_context
from .ranking import (
    FORMULA_VERSION,
    ClassifiedFactor,
    MeasurementClass,
    OpportunityInput,
    RankingFactor,
    rank_opportunities,
)
from .runbook import RunbookValidationError, generate_reviewable_runbook
from .store import ObservationStore
from .workflow import WorkflowReconstructor, WorkflowValidationError, parse_workflow_metadata

SNAPSHOT_VERSION = "workflow-intelligence-mission-control-v1"
MAX_WORKFLOWS = 50


def _unavailable() -> ClassifiedFactor:
    return ClassifiedFactor(MeasurementClass.UNAVAILABLE, None)


def _ranking_for(reconstruction: dict[str, Any]) -> dict[str, Any]:
    stage_count = len(reconstruction["stages"])
    retry_rework = min(
        (reconstruction["retry_count"] + reconstruction["rework_count"])
        / max(stage_count, 1),
        1.0,
    )
    evidence_coverage = min(
        len(reconstruction["evidence_refs"]) / max(stage_count, 1),
        1.0,
    )
    source = f"event:{reconstruction['correlation_id']}"
    opportunity = OpportunityInput(
        opportunity_id=f"workflow:{reconstruction['workflow_id']}",
        workflow_id=reconstruction["workflow_id"],
        factors={
            RankingFactor.FREQUENCY: _unavailable(),
            RankingFactor.MANUAL_TIME: _unavailable(),
            RankingFactor.RETRY_REWORK_RATE: ClassifiedFactor(
                MeasurementClass.CALCULATED, retry_rework, source
            ),
            RankingFactor.DEPENDENCY_READINESS: _unavailable(),
            RankingFactor.REVERSIBILITY: _unavailable(),
            RankingFactor.SCIENTIFIC_GOVERNANCE_RISK: _unavailable(),
            RankingFactor.DATA_COMPLETENESS: ClassifiedFactor(
                MeasurementClass.CALCULATED, evidence_coverage, source
            ),
        },
    )
    return rank_opportunities([opportunity])[0]


def _display_state(current_state: str) -> str:
    if current_state == "blocked":
        return "BLOCKED"
    if current_state == "failed":
        return "RECENTLY_FAILED"
    if current_state == "review_required":
        return "AWAITING_REVIEW"
    if current_state in {"completed", "cancelled"}:
        return "TERMINAL"
    return "ACTIVE"


def build_mission_control_snapshot(store: ObservationStore) -> dict[str, Any]:
    """Return a bounded deterministic snapshot; no execution authority is granted."""

    correlations: list[str] = []
    last_recorded_at: str | None = None
    for event in store.all():
        recorded_at = event.get("recorded_at")
        if isinstance(recorded_at, str) and (
            last_recorded_at is None or recorded_at > last_recorded_at
        ):
            last_recorded_at = recorded_at
        try:
            parse_workflow_metadata(event)
        except WorkflowValidationError:
            continue
        correlation_id = event.get("correlation_id")
        if isinstance(correlation_id, str) and correlation_id not in correlations:
            correlations.append(correlation_id)

    reconstructor = WorkflowReconstructor(store)
    items: list[dict[str, Any]] = []
    for correlation_id in sorted(correlations)[:MAX_WORKFLOWS]:
        try:
            reconstruction = reconstructor.reconstruct(correlation_id)
            ranking = _ranking_for(reconstruction)
            context = build_governed_agent_context(reconstruction, ranking)
        except (WorkflowValidationError, ContextValidationError):
            continue

        runbook: dict[str, Any] | None
        try:
            runbook = generate_reviewable_runbook(reconstruction, context)
        except RunbookValidationError:
            runbook = None

        items.append(
            {
                "workflow_id": reconstruction["workflow_id"],
                "workflow_type": reconstruction["workflow_type"],
                "correlation_id": correlation_id,
                "display_state": _display_state(reconstruction["current_state"]),
                "current_state": reconstruction["current_state"],
                "retry_count": reconstruction["retry_count"],
                "rework_count": reconstruction["rework_count"],
                "evidence_refs": reconstruction["evidence_refs"],
                "blocker_refs": reconstruction["blocker_refs"],
                "findings": reconstruction["findings"],
                "stale": {
                    "classification": MeasurementClass.UNAVAILABLE.value,
                    "value": None,
                },
                "ranking": ranking,
                "agent_context": context,
                "runbook": runbook,
                "capability_state": "BACKEND_ONLY",
            }
        )

    items.sort(key=lambda item: (item["display_state"], item["workflow_id"]))
    return {
        "contract_version": SNAPSHOT_VERSION,
        "source_contracts": [
            "workflow-intelligence-v1",
            FORMULA_VERSION,
            "governed-agent-context-v1",
            "reviewable-runbook-v1",
        ],
        "generated_at": last_recorded_at,
        "workflow_count": len(items),
        "workflows": items,
        "advisory_only": True,
        "human_review_required": True,
        "dispatch_authority": False,
        "mutation_authority": False,
        "publication_authority": False,
        "spending_authority": False,
    }
