from __future__ import annotations

import hashlib
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.brain.plant_diagnostic_context import (
    PlantDiagnosticContextRequest,
    compose_plant_diagnostic_context,
)
from runtime.knowledge_graph import GraphRepository


class DiagnosticHypothesisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    context: PlantDiagnosticContextRequest
    max_hypotheses: int = Field(default=10, ge=1, le=50)
    include_indeterminate: bool = True


def _stable_id(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _hypothesis_score(path: dict[str, Any]) -> tuple[float, str]:
    confidence = max(0.0, min(float(path.get("confidence", 0.0)), 1.0))
    status = str((path.get("applicability") or {}).get("status") or "indeterminate")
    if status == "applicable":
        return round(confidence, 6), "scope_applicable"
    if status == "indeterminate":
        # Unresolved applicability can remain a diagnostic hypothesis, but it
        # must never outrank an equally supported scope-qualified pathway.
        return round(confidence * 0.5, 6), "scope_indeterminate_penalty"
    return 0.0, "out_of_scope_excluded"


def rank_diagnostic_hypotheses(
    graph_repository: GraphRepository,
    request: DiagnosticHypothesisRequest,
    candidate_components: tuple[Any, Any] | None = None,
) -> dict[str, Any]:
    """Rank explanatory hypotheses without creating scientific claims.

    Ranking is based on canonical reasoning-path evidence and applicability.
    Local plant observations are attached as context but do not increase causal
    confidence and are not interpreted as confirmation of any mechanism.
    """

    context = compose_plant_diagnostic_context(
        graph_repository,
        request.context,
        candidate_components,
    )
    reasoning = context["canonical_reasoning"]
    local_context = context["local_observation_context"]
    local_observations = list(local_context.get("observations", []))

    hypotheses: list[dict[str, Any]] = []
    excluded_out_of_scope: list[dict[str, Any]] = []
    for path in reasoning.get("paths", []):
        applicability = dict(path.get("applicability") or {})
        status = str(applicability.get("status") or "indeterminate")
        score, scoring_basis = _hypothesis_score(path)
        if status == "out_of_scope":
            excluded_out_of_scope.append(
                {
                    "path_edge_ids": list(path.get("edge_ids", [])),
                    "explanation": path.get("explanation"),
                    "reason": "canonical_path_out_of_requested_scope",
                }
            )
            continue
        if status == "indeterminate" and not request.include_indeterminate:
            continue

        core = {
            "plant_record_key": request.context.plant_record_key,
            "edge_ids": list(path.get("edge_ids", [])),
            "node_ids": list(path.get("node_ids", [])),
            "applicability_status": status,
            "path_confidence": path.get("confidence"),
        }
        hypotheses.append(
            {
                "hypothesis_id": _stable_id(core),
                "status": "diagnostic_hypothesis_only",
                "rank_score": score,
                "scoring_basis": scoring_basis,
                "explanation": path.get("explanation"),
                "canonical_path": path,
                "applicability_status": status,
                "canonical_path_confidence": path.get("confidence"),
                "local_context": {
                    "plant_record_key": request.context.plant_record_key,
                    "observation_count": len(local_observations),
                    "observation_candidate_ids": [
                        item.get("candidate_id") for item in local_observations
                    ],
                    "causal_confirmation": False,
                    "rank_score_contribution": 0.0,
                },
                "interpretation": {
                    "possible_explanation": True,
                    "scientific_claim": False,
                    "causality_proven": False,
                    "local_observations_confirm_mechanism": False,
                    "requires_additional_discriminating_evidence": True,
                },
            }
        )

    hypotheses.sort(
        key=lambda item: (
            -float(item["rank_score"]),
            str(item["hypothesis_id"]),
        )
    )
    hypotheses = hypotheses[: request.max_hypotheses]

    return {
        "contract": "calyx-diagnostic-hypothesis-ranking-v1",
        "plant_record_key": request.context.plant_record_key,
        "hypothesis_count": len(hypotheses),
        "hypotheses": hypotheses,
        "excluded_out_of_scope": excluded_out_of_scope,
        "local_observation_count": len(local_observations),
        "ranking_policy": {
            "canonical_path_confidence_used": True,
            "scope_applicability_used": True,
            "indeterminate_scope_penalty": 0.5,
            "out_of_scope_paths_ranked": False,
            "local_observations_increase_causal_confidence": False,
            "local_observations_increase_rank_score": False,
        },
        "governance": {
            "read_only": True,
            "hypotheses_are_not_scientific_claims": True,
            "automatic_candidate_creation": False,
            "automatic_publication": False,
            "canonical_graph_mutated": False,
            "candidate_knowledge_mutated": False,
            "human_review_required_for_new_scientific_claims": True,
        },
    }
