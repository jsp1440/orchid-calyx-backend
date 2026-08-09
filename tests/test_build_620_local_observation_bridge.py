from __future__ import annotations

import pytest

from app.brain.local_observation_context import local_observation_history
from app.brain.local_observations import (
    LocalObservationRequest,
    handoff_local_observation,
)
from app.brain.mechanistic_publication_plan import (
    plan_mechanistic_candidate_publication,
)
from app.candidate_knowledge.repository import MemoryCandidateRepository
from app.candidate_knowledge.service import CandidateExtractionService


def components():
    repository = MemoryCandidateRepository()
    service = CandidateExtractionService(repository)
    return repository, service


def request(observation_id: str, response_label: str = "New root growth"):
    return LocalObservationRequest.model_validate(
        {
            "observation_id": observation_id,
            "plant_record_key": "conservatory-plant-42",
            "taxon": "Phalaenopsis bellina",
            "observed_at": "2026-08-08T18:30:00-07:00",
            "location_key": "greenhouse-east-bench",
            "response_type": "phenotype",
            "response_label": response_label,
            "observation_text": (
                "New root growth was visible after the latest greenhouse observation interval."
            ),
            "confidence": 0.9,
            "environmental_context": {
                "temperature_c": 24.0,
                "relative_humidity_percent": 72,
            },
            "cultivation_context": {"media": "bark", "watered_days_ago": 2},
            "matrix_context": {"cultivation_score": 0.84},
            "source_object_id": 501,
            "revision_id": 502,
            "extraction_run_id": 503,
            "source_anchors": [{"anchor_id": 504, "locator": {"confidence": 1.0}}],
        }
    )


def test_local_observation_is_noncausal_review_required_candidate():
    repository, service = components()
    result = handoff_local_observation(request("obs-001"), (repository, service))
    assert result["state"] == "COMPLETED"
    assert result["local_only"] is True
    assert result["generalizable"] is False
    assert result["causal_claim"] is False
    assert result["published"] is False
    assert result["canonical_graph_mutation"] is False
    assert result["graph_preview"]["semantics"] == {
        "role": "evidence",
        "polarity": 0,
        "causal": False,
    }
    candidate = repository.candidates[0]
    assert candidate["kind"] == "CULTIVATION_OBSERVATION"
    assert candidate["predicate"] == "observed_as"
    assert candidate["review_state"] == "REQUIRED"
    assert candidate["published"] is False
    assert candidate["qualifiers"]["local_observation"] is True
    assert candidate["qualifiers"]["generalizable"] is False
    assert candidate["qualifiers"]["causal_scope"]["scope_class"] == "bounded"
    assert candidate["qualifiers"]["causal_scope"]["population_context"]["n"] == 1


def test_repeated_same_plant_observations_remain_distinct_longitudinal_events():
    repository, service = components()
    first = handoff_local_observation(request("obs-001"), (repository, service))
    second = handoff_local_observation(
        request("obs-002", response_label="Second root tip emerged"),
        (repository, service),
    )
    assert first["candidate_ids"] != second["candidate_ids"]
    assert len(repository.candidates) == 2
    assert all(candidate["active"] for candidate in repository.candidates)
    assert repository.conflicts == {}
    subjects = {candidate["normalized_subject"] for candidate in repository.candidates}
    assert len(subjects) == 2


@pytest.mark.parametrize("field", ["observation_id", "plant_record_key"])
def test_local_observation_identity_rejects_semantically_blank_values(field):
    payload = {
        "observation_id": "obs-identity",
        "plant_record_key": "conservatory-plant-42",
        "observed_at": "2026-08-08T18:30:00-07:00",
        "response_label": "New root growth",
        "observation_text": "A single-plant observation.",
        "source_object_id": 501,
        "revision_id": 502,
        "extraction_run_id": 503,
        "source_anchors": [{"anchor_id": 504}],
    }
    payload[field] = "   "

    with pytest.raises(ValueError, match="LOCAL_OBSERVATION_IDENTITY_REQUIRED"):
        LocalObservationRequest.model_validate(payload)


def test_local_observation_identity_is_trimmed_before_scope_and_candidate_identity():
    repository, service = components()
    payload = request("obs-trimmed").model_copy(
        update={
            "observation_id": "  obs-trimmed  ",
            "plant_record_key": "  conservatory-plant-42  ",
        }
    )
    # model_copy does not re-run validators, so validate the dumped representation.
    payload = LocalObservationRequest.model_validate(payload.model_dump())

    result = handoff_local_observation(payload, (repository, service))
    candidate = repository.candidates[0]
    assert result["observation_id"] == "obs-trimmed"
    assert candidate["qualifiers"]["plant_record_key"] == "conservatory-plant-42"
    assert result["causal_scope"]["population_context"] == {
        "n": 1,
        "plant_record_key": "conservatory-plant-42",
    }


def test_local_observation_cannot_become_mechanistic_publication_plan():
    repository, service = components()
    result = handoff_local_observation(request("obs-003"), (repository, service))
    candidate_id = result["candidate_ids"][0]
    plan = plan_mechanistic_candidate_publication(candidate_id, (repository, service))
    assert plan["ready_for_controlled_publication_gate"] is False
    assert "candidate_kind_not_mechanistic" in plan["blockers"]
    assert plan["authorized"] is False
    assert plan["commit_capability"] is False


def test_scope_binds_observation_to_plant_time_and_location():
    repository, service = components()
    result = handoff_local_observation(request("obs-004"), (repository, service))
    scope = result["causal_scope"]
    assert scope["taxa"] == ["phalaenopsis bellina"]
    assert scope["cultivation_context"]["plant_record_key"] == "conservatory-plant-42"
    assert scope["cultivation_context"]["location_key"] == "greenhouse-east-bench"
    assert scope["cultivation_context"]["observed_at"].startswith("2026-08-08T18:30:00")
    assert scope["population_context"] == {
        "n": 1,
        "plant_record_key": "conservatory-plant-42",
    }


def test_graph_preview_is_local_evidence_not_canonical_mechanism():
    repository, service = components()
    result = handoff_local_observation(request("obs-005"), (repository, service))
    edge = result["graph_preview"]["edges"][0]
    assert edge["edge_type"] == "observed_as"
    assert edge["payload"]["local_only"] is True
    assert edge["payload"]["candidate_only"] is True
    assert result["graph_preview"]["validation"]["healthy"] is True
    assert result["scientific_publication_authority"] is False


def test_local_history_returns_only_same_plant_local_observations():
    repository, service = components()
    handoff_local_observation(request("obs-006"), (repository, service))
    handoff_local_observation(
        request("obs-007", response_label="Leaf expanded"),
        (repository, service),
    )
    history = local_observation_history("conservatory-plant-42", (repository, service))
    assert history["observation_count"] == 2
    assert history["reasoning_use"] == "local_context_only"
    assert history["species_level_generalization"] is False
    assert all(item["generalizable"] is False for item in history["observations"])
    assert all(item["causal_claim"] is False for item in history["observations"])
