from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.brain.local_observation_context import local_observation_history
from app.brain.scoped_reasoning_map import (
    ScopedReasoningMapRequest,
    build_scoped_reasoning_map,
)
from runtime.knowledge_graph import GraphRepository


class PlantDiagnosticContextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plant_record_key: str = Field(min_length=1, max_length=240)
    reasoning: ScopedReasoningMapRequest

    @field_validator("plant_record_key")
    @classmethod
    def normalize_plant_record_key(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("PLANT_RECORD_KEY_REQUIRED")
        return normalized


def compose_plant_diagnostic_context(
    graph_repository: GraphRepository,
    request: PlantDiagnosticContextRequest,
    candidate_components: tuple[Any, Any] | None = None,
) -> dict[str, Any]:
    """Compose scoped canonical mechanisms with local plant evidence read-only.

    Local observations remain a separate evidence channel and are never treated
    as proof of a canonical mechanism or injected into the canonical graph.
    """

    reasoning_map = build_scoped_reasoning_map(graph_repository, request.reasoning)
    local_history = local_observation_history(
        request.plant_record_key,
        candidate_components,
    )

    scope_summary = reasoning_map.get("scope_summary", {})
    applicable_paths = int(scope_summary.get("fully_applicable_path_count", 0))
    out_of_scope_paths = int(scope_summary.get("out_of_scope_path_count", 0))
    indeterminate_paths = int(scope_summary.get("indeterminate_path_count", 0))
    observation_count = int(local_history.get("observation_count", 0))

    return {
        "contract": "calyx-plant-diagnostic-context-v1",
        "plant_record_key": request.plant_record_key,
        "canonical_reasoning": reasoning_map,
        "local_observation_context": local_history,
        "summary": {
            "applicable_canonical_path_count": applicable_paths,
            "out_of_scope_canonical_path_count": out_of_scope_paths,
            "indeterminate_canonical_path_count": indeterminate_paths,
            "local_observation_count": observation_count,
            "has_applicable_canonical_context": applicable_paths > 0,
            "has_local_context": observation_count > 0,
        },
        "interpretation_policy": {
            "canonical_mechanisms_and_local_observations_are_separate_channels": True,
            "local_observation_implies_canonical_mechanism": False,
            "similarity_is_not_causality": True,
            "unknown_scope_is_not_assumed_applicable": True,
            "diagnostic_hypothesis_generation_allowed": True,
            "automatic_scientific_claim_generation": False,
            "automatic_publication": False,
        },
        "governance": {
            "read_only": True,
            "canonical_graph_mutated": False,
            "candidate_knowledge_mutated": False,
            "scientific_publication_authority": False,
            "human_review_required_for_new_scientific_claims": True,
        },
    }
