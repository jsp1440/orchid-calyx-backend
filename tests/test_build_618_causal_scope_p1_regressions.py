from __future__ import annotations

import pytest

from app.brain.causal_scope import CausalScope, normalize_causal_scope
from app.brain.mechanistic_candidates import (
    MechanisticCandidateRequest,
    handoff_mechanistic_candidate,
)
from app.brain.mechanistic_contradictions import analyze_mechanistic_contradictions
from app.candidate_knowledge.repository import MemoryCandidateRepository
from app.candidate_knowledge.service import CandidateExtractionService


def components():
    repository = MemoryCandidateRepository()
    return repository, CandidateExtractionService(repository)


def request(
    relationship: str, scope: dict, reasoning_id: str
) -> MechanisticCandidateRequest:
    return MechanisticCandidateRequest.model_validate(
        {
            "reasoning_id": reasoning_id,
            "source": {
                "node_type": "environment",
                "label": "Cool nights",
                "stable_key": "cool-nights",
            },
            "relationship": relationship,
            "target": {
                "node_type": "physiology",
                "label": "Respiration rate",
                "stable_key": "respiration-rate",
            },
            "confidence": 0.8,
            "evidence_text": "Cool nights changed respiration rate.",
            "source_object_type": "document_revision",
            "source_object_id": 11 if relationship == "promotes" else 21,
            "revision_id": 12 if relationship == "promotes" else 22,
            "extraction_run_id": 13 if relationship == "promotes" else 23,
            "source_anchors": [{"anchor_id": 14 if relationship == "promotes" else 24}],
            "causal_scope": scope,
        }
    )


@pytest.mark.parametrize(
    "mapping",
    [
        {"temperature": None},
        {"temperature": "   "},
        {"   ": "cool nights"},
        {"temperature": []},
        {"temperature": {}},
        {"temperature": {"night": None}},
        {"temperature": [" ", None, {}]},
    ],
)
def test_bounded_scope_rejects_semantically_empty_mapping_bounds(mapping):
    with pytest.raises(
        ValueError, match="BOUNDED_CAUSAL_SCOPE_REQUIRES_APPLICABILITY_BOUNDS"
    ):
        CausalScope.model_validate({"scope_class": "bounded", "environments": mapping})


def test_mapping_scope_normalizes_keys_values_nested_collections_and_scope_id():
    first = normalize_causal_scope(
        {
            "scope_class": "bounded",
            "environments": {
                " Temperature ": " Cool   Nights ",
                "Location": {" Exposure ": " SHADE "},
                "seasons": [" Summer ", "winter", "SUMMER"],
            },
        }
    )
    second = normalize_causal_scope(
        {
            "scope_class": "bounded",
            "environments": {
                "temperature": "cool nights",
                "location": {"exposure": "shade"},
                "SEASONS": ["WINTER", "summer"],
            },
        }
    )

    assert first["environments"] == second["environments"]
    assert first["scope_id"] == second["scope_id"]


def test_equivalent_categorical_mapping_scope_forms_real_contradiction():
    repository, service = components()
    positive_scope = {
        "scope_class": "bounded",
        "environments": {"Temperature": "Cool Nights"},
    }
    negative_scope = {
        "scope_class": "bounded",
        "environments": {" temperature ": " cool   nights "},
    }

    handoff_mechanistic_candidate(
        request("promotes", positive_scope, "mapping-positive"),
        (repository, service),
    )
    handoff_mechanistic_candidate(
        request("inhibits", negative_scope, "mapping-negative"),
        (repository, service),
    )

    report = analyze_mechanistic_contradictions((repository, service))
    assert report["contradiction_count"] == 1


def test_conflicting_keys_that_collapse_to_same_canonical_key_are_rejected():
    with pytest.raises(
        ValueError, match="AMBIGUOUS_CAUSAL_SCOPE_MAPPING_KEY:temperature"
    ):
        CausalScope.model_validate(
            {
                "scope_class": "bounded",
                "environments": {
                    "Temperature": "cool nights",
                    " temperature ": "warm nights",
                },
            }
        )
