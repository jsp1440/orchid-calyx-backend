from __future__ import annotations

import pytest

from app.brain.mechanistic_candidates import (
    MechanisticCandidateRequest,
    handoff_mechanistic_candidate,
)
from app.candidate_knowledge.repository import MemoryCandidateRepository
from app.candidate_knowledge.service import CandidateExtractionService
from app.evidence_aggregation.models import CANDIDATE_TYPE_MAP, AggregateType
from app.scientific_orchestration.service import (
    GovernedScientificOrchestrationService,
    RiskClass,
)


def payload(**overrides):
    data = {
        "reasoning_id": "mechanism:light-auxin-001",
        "source": {
            "node_type": "environment",
            "label": "Directional blue light",
            "stable_key": "blue-light",
        },
        "relationship": "promotes",
        "target": {
            "node_type": "physiology",
            "label": "Auxin redistribution",
            "stable_key": "auxin-redistribution",
        },
        "confidence": 0.82,
        "evidence_text": "Directional blue light promoted auxin redistribution in the measured tissue.",
        "source_object_type": "document_revision",
        "source_object_id": 11,
        "revision_id": 12,
        "extraction_run_id": 13,
        "source_anchors": [
            {
                "anchor_id": 14,
                "ordered_span": 0,
                "page_number": 3,
                "char_start": 120,
                "char_end": 196,
                "locator": {"confidence": 0.98},
            }
        ],
        "experimental_context": {"tissue": "young leaf", "stage": "expansion"},
        "quantitative_context": {"wavelength_nm": 450},
        "provenance": {"doi": "10.0000/example"},
    }
    data.update(overrides)
    return MechanisticCandidateRequest.model_validate(data)


def components():
    repository = MemoryCandidateRepository()
    service = CandidateExtractionService(repository)
    return repository, service


class AtomicMemoryCandidateRepository(MemoryCandidateRepository):
    def __init__(self) -> None:
        super().__init__()
        self.atomic_calls = 0

    def atomic(self, operation):
        self.atomic_calls += 1
        return operation()


def test_valid_mechanistic_claim_enters_review_required_candidate_knowledge():
    repository, service = components()
    result = handoff_mechanistic_candidate(payload(), (repository, service))

    assert result["state"] == "COMPLETED"
    assert result["published"] is False
    assert result["canonical_graph_mutation"] is False
    assert result["review_required"] is True
    assert result["graph_preview"]["validation"]["healthy"] is True
    assert result["graph_preview"]["semantics"] == {
        "role": "causal",
        "polarity": 1,
        "causal": True,
    }

    candidate = repository.candidates[0]
    assert candidate["kind"] == "MECHANISTIC_RELATIONSHIP"
    assert candidate["predicate"] == "promotes"
    assert candidate["review_state"] == "REQUIRED"
    assert candidate["published"] is False
    assert (
        candidate["qualifiers"]["graph_contract"]["source_node_type"] == "environment"
    )
    assert candidate["qualifiers"]["graph_contract"]["target_node_type"] == "physiology"
    assert candidate["qualifiers"]["quantitative_context"]["wavelength_nm"] == 450
    assert repository.evidence_links[0]["anchor"]["anchor_id"] == 14


def test_inhibitory_relationship_preserves_negative_polarity():
    repository, service = components()
    result = handoff_mechanistic_candidate(
        payload(relationship="inhibits"), (repository, service)
    )
    assert result["graph_preview"]["semantics"]["polarity"] == -1
    assert repository.candidates[0]["qualifiers"]["graph_contract"]["polarity"] == -1


def test_noncausal_context_relationship_is_rejected_before_candidate_creation():
    repository, service = components()
    with pytest.raises(ValueError, match="CONTROLLED_CAUSAL_RELATIONSHIP_REQUIRED"):
        handoff_mechanistic_candidate(
            payload(relationship="has_trait"), (repository, service)
        )
    assert repository.candidates == []
    assert repository.runs == {}


def test_unapproved_endpoint_type_is_rejected_before_candidate_creation():
    repository, service = components()
    request = payload(
        source={"node_type": "image", "label": "Leaf image", "stable_key": "img-1"}
    )
    with pytest.raises(ValueError, match="UNAPPROVED_CAUSAL_SOURCE_TYPE:image"):
        handoff_mechanistic_candidate(request, (repository, service))
    assert repository.candidates == []


def test_exact_evidence_anchor_and_experimental_context_survive_handoff():
    repository, service = components()
    handoff_mechanistic_candidate(payload(), (repository, service))
    candidate = repository.candidates[0]
    assert candidate["qualifiers"]["experimental_context"] == {
        "tissue": "young leaf",
        "stage": "expansion",
    }
    assert candidate["qualifiers"]["provenance"]["doi"] == "10.0000/example"
    assert repository.evidence_links[0]["revision_id"] == 12
    assert repository.evidence_links[0]["extraction_run_id"] == 13


def test_endpoint_attributes_cannot_override_candidate_only_governance_marker():
    repository, service = components()
    request = payload(
        source={
            "node_type": "environment",
            "label": "Directional blue light",
            "stable_key": "blue-light",
            "attributes": {"candidate_only": False, "wavelength_nm": 450},
        }
    )
    result = handoff_mechanistic_candidate(request, (repository, service))
    source_node = result["graph_preview"]["nodes"][0]
    assert source_node["payload"]["candidate_only"] is True
    assert source_node["payload"]["wavelength_nm"] == 450


def test_handoff_uses_repository_atomic_boundary_when_available():
    repository = AtomicMemoryCandidateRepository()
    service = CandidateExtractionService(repository)
    result = handoff_mechanistic_candidate(payload(), (repository, service))
    assert result["state"] == "COMPLETED"
    assert repository.atomic_calls == 1


def test_duplicate_evidence_returns_existing_candidate_id():
    repository, service = components()
    first = handoff_mechanistic_candidate(payload(), (repository, service))
    duplicate = payload(
        reasoning_id="mechanism:light-auxin-002",
        evidence_text="A second source reported the same directional blue light mechanism.",
        source_object_id=21,
        revision_id=22,
        extraction_run_id=23,
        source_anchors=[{"anchor_id": 24, "page_number": 7}],
    )
    second = handoff_mechanistic_candidate(duplicate, (repository, service))
    assert first["candidate_ids"]
    assert second["candidate_ids"] == first["candidate_ids"]


def test_whitespace_only_target_label_is_rejected_before_persistence():
    repository, service = components()
    request = payload(
        target={"node_type": "physiology", "label": "   ", "stable_key": "blank"}
    )
    with pytest.raises(ValueError, match="MECHANISTIC_TARGET_LABEL_REQUIRED"):
        handoff_mechanistic_candidate(request, (repository, service))
    assert repository.candidates == []
    assert repository.runs == {}


def test_graph_preview_uses_synthetic_provenance_not_candidate_table_identity():
    repository, service = components()
    result = handoff_mechanistic_candidate(payload(), (repository, service))
    for node in result["graph_preview"]["nodes"]:
        assert node["source_table"] == "synthetic.mechanistic_candidate_preview"
        assert node["payload"]["preview_provenance"]["source_object_id"] == 11
        assert node["payload"]["preview_provenance"]["revision_id"] == 12
    edge = result["graph_preview"]["edges"][0]
    assert edge["source_table"] == "synthetic.mechanistic_candidate_preview"


def test_mechanistic_candidates_have_dedicated_aggregate_type():
    assert (
        CANDIDATE_TYPE_MAP["MECHANISTIC_RELATIONSHIP"]
        is AggregateType.MECHANISTIC_RELATIONSHIP_AGGREGATE
    )


def test_high_confidence_mechanistic_claim_still_requires_inference_review():
    service = GovernedScientificOrchestrationService.__new__(
        GovernedScientificOrchestrationService
    )
    risk = service._risk_class(
        [{"kind": "MECHANISTIC_RELATIONSHIP", "confidence": 0.99}], []
    )
    assert risk is RiskClass.LEVEL_2_SCIENTIFIC_INFERENCE
