from __future__ import annotations

from typing import Any

from app.candidate_knowledge.dependencies import get_candidate_components
from app.candidate_knowledge.models import CandidateKind


def local_observation_history(
    plant_record_key: str,
    components: tuple[Any, Any] | None = None,
) -> dict[str, Any]:
    repository, _service = components or get_candidate_components()
    key = plant_record_key.strip()
    if not key:
        raise ValueError("PLANT_RECORD_KEY_REQUIRED")

    observations: list[dict[str, Any]] = []
    for candidate in repository.candidates:
        if not candidate.get("active", True):
            continue
        if candidate.get("kind") != CandidateKind.CULTIVATION_OBSERVATION.value:
            continue
        qualifiers = dict(candidate.get("qualifiers") or {})
        if qualifiers.get("plant_record_key") != key:
            continue
        if qualifiers.get("local_observation") is not True:
            continue
        observations.append(
            {
                "candidate_id": candidate["candidate_id"],
                "observation_id": qualifiers.get("observation_id"),
                "plant_record_key": key,
                "taxon": qualifiers.get("taxon"),
                "observed_at": qualifiers.get("observed_at"),
                "location_key": qualifiers.get("location_key"),
                "response_type": qualifiers.get("response_type"),
                "response_label": candidate.get("object_value"),
                "confidence": candidate.get("confidence"),
                "review_state": candidate.get("review_state"),
                "causal_scope": qualifiers.get("causal_scope"),
                "matrix_context": qualifiers.get("matrix_context", {}),
                "environmental_context": qualifiers.get(
                    "environmental_context", {}
                ),
                "cultivation_context": qualifiers.get("cultivation_context", {}),
                "treatment_context": qualifiers.get("treatment_context", {}),
                "published": bool(candidate.get("published")),
                "generalizable": False,
                "causal_claim": False,
            }
        )

    observations.sort(
        key=lambda item: (
            str(item.get("observed_at") or ""),
            int(item["candidate_id"]),
        )
    )
    return {
        "contract": "calyx-local-observation-history-v1",
        "plant_record_key": key,
        "observation_count": len(observations),
        "observations": observations,
        "reasoning_use": "local_context_only",
        "species_level_generalization": False,
        "canonical_graph_mutated": False,
        "scientific_publication_authority": False,
    }
