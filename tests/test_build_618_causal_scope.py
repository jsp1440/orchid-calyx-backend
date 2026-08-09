from __future__ import annotations

import pytest

from app.brain.causal_scope import CausalScope, normalize_causal_scope
from app.brain.mechanistic_candidates import (
    MechanisticCandidateRequest,
    handoff_mechanistic_candidate,
)
from app.brain.mechanistic_contradictions import analyze_mechanistic_contradictions
from app.brain.mechanistic_publication_plan import (
    plan_mechanistic_candidate_publication,
)
from app.candidate_knowledge.repository import MemoryCandidateRepository
from app.candidate_knowledge.service import CandidateExtractionService


def components():
    repository = MemoryCandidateRepository()
    return repository, CandidateExtractionService(repository)


def request(
    relationship="promotes", causal_scope=None, reasoning_id="scope:001"
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
            "evidence_text": "Cool nights changed respiration rate in expanding leaves.",
            "source_object_type": "document_revision",
            "source_object_id": 1,
            "revision_id": 2,
            "extraction_run_id": 3,
            "source_anchors": [{"anchor_id": 4}],
            "causal_scope": causal_scope or {},
        }
    )


def approve(repository, candidate_id):
    for review_id, review in list(repository.reviews.items()):
        if review.get("candidate_id") == candidate_id and review.get("state") == "OPEN":
            repository.resolve_review(
                review_id,
                "APPROVE_CANDIDATE",
                "Scope and evidence reviewed.",
                "qualified.science-reviewer",
            )


def test_unknown_scope_is_never_global_and_blocks_publication():
    repository, service = components()
    result = handoff_mechanistic_candidate(request(), (repository, service))
    candidate_id = result["candidate_ids"][0]
    approve(repository, candidate_id)
    assert result["graph_preview"]["causal_scope"]["scope_class"] == "unknown"
    plan = plan_mechanistic_candidate_publication(candidate_id, (repository, service))
    assert "causal_scope_unknown" in plan["blockers"]
    assert plan["ready_for_controlled_publication_gate"] is False


def test_bounded_scope_requires_real_bounds():
    with pytest.raises(
        ValueError, match="BOUNDED_CAUSAL_SCOPE_REQUIRES_APPLICABILITY_BOUNDS"
    ):
        CausalScope.model_validate({"scope_class": "bounded"})


def test_global_scope_requires_explicit_justification():
    with pytest.raises(ValueError, match="GLOBAL_CAUSAL_SCOPE_REQUIRES_JUSTIFICATION"):
        CausalScope.model_validate({"scope_class": "global"})


def test_global_scope_rejects_local_bounds():
    with pytest.raises(
        ValueError, match="GLOBAL_CAUSAL_SCOPE_CANNOT_DECLARE_LOCAL_BOUNDS"
    ):
        CausalScope.model_validate(
            {
                "scope_class": "global",
                "global_justification": "Explicitly global synthesis.",
                "tissues": ["leaf"],
            }
        )


def test_scope_normalization_is_order_independent():
    first = normalize_causal_scope(
        {
            "scope_class": "bounded",
            "taxa": ["Phalaenopsis", "Cattleya"],
            "tissues": ["Leaf", "Root"],
        }
    )
    second = normalize_causal_scope(
        {
            "scope_class": "bounded",
            "taxa": ["cattleya", "phalaenopsis"],
            "tissues": ["root", "leaf"],
        }
    )
    assert first["scope_id"] == second["scope_id"]
    assert first["taxa"] == ["cattleya", "phalaenopsis"]


def test_bounded_scope_preserves_canonical_endpoint_identity_in_plan():
    repository, service = components()
    scoped = {"scope_class": "bounded", "tissues": ["leaf"]}
    result = handoff_mechanistic_candidate(
        request(causal_scope=scoped), (repository, service)
    )
    candidate_id = result["candidate_ids"][0]
    approve(repository, candidate_id)

    plan = plan_mechanistic_candidate_publication(candidate_id, (repository, service))

    assert plan["ready_for_controlled_publication_gate"] is True
    assert plan["blockers"] == []
    source = plan["operations"][0]["payload"]
    target = plan["operations"][1]["payload"]
    assert source["canonical_key"] == "environment:cool-nights"
    assert source["source_pk"] == "cool-nights"
    assert target["canonical_key"] == "physiology:respiration-rate"
    assert target["source_pk"] == "respiration-rate"
    assert source["payload"]["causal_scope"]["scope_class"] == "bounded"


def test_opposite_polarity_in_different_tissues_is_not_a_contradiction():
    repository, service = components()
    leaf = {"scope_class": "bounded", "tissues": ["leaf"]}
    root = {"scope_class": "bounded", "tissues": ["root"]}
    handoff_mechanistic_candidate(
        request("promotes", leaf, "leaf"), (repository, service)
    )
    handoff_mechanistic_candidate(
        request("inhibits", root, "root"), (repository, service)
    )
    report = analyze_mechanistic_contradictions((repository, service))
    assert report["contradiction_count"] == 0


def test_opposite_polarity_in_same_normalized_scope_is_a_contradiction():
    repository, service = components()
    scope_a = {
        "scope_class": "bounded",
        "taxa": ["Phalaenopsis"],
        "tissues": ["Leaf"],
    }
    scope_b = {
        "scope_class": "bounded",
        "taxa": ["phalaenopsis"],
        "tissues": ["leaf"],
    }
    handoff_mechanistic_candidate(
        request("promotes", scope_a, "positive"), (repository, service)
    )
    handoff_mechanistic_candidate(
        request("inhibits", scope_b, "negative"), (repository, service)
    )
    report = analyze_mechanistic_contradictions((repository, service))
    assert report["contradiction_count"] == 1
    assert (
        report["contradictions"][0]["scope"]["causal_scope"]["scope_class"] == "bounded"
    )
