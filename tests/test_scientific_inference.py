from __future__ import annotations

import pytest

from app.scientific_inference import (
    InferenceDomain,
    InferenceState,
    ScientificInferenceService,
)


def aggregate(
    *,
    aggregate_id: int = 1,
    aggregate_type: str = "TAXON_IDENTITY_AGGREGATE",
    aggregate_status: str = "SUPPORTED",
    review_state: str = "APPROVED",
    verification_state: str = "VERIFIED",
    supporting: int = 2,
    contradicting: int = 0,
    unresolved: int = 0,
    independent_sources: int = 3,
    anchors: bool = True,
) -> dict:
    return {
        "aggregate_id": aggregate_id,
        "aggregate_version_id": aggregate_id * 10,
        "aggregate_type": aggregate_type,
        "identity_hash": f"hash-{aggregate_id}",
        "aggregate_status": aggregate_status,
        "review_state": review_state,
        "verification_state": verification_state,
        "published": False,
        "source_anchor_links": (
            [
                {
                    "candidate_id": aggregate_id * 100,
                    "revision_id": aggregate_id * 1000,
                    "anchor_ids": [aggregate_id * 10000],
                }
            ]
            if anchors
            else []
        ),
        "confidence_dimensions": {
            "independent_sources": independent_sources,
            "supporting_assertions": supporting,
            "contradicting_assertions": contradicting,
            "unresolved_assertions": unresolved,
            "anchor_completeness": 1.0 if anchors else 0.0,
            "taxon_link_certainty": 0.95,
            "method_compatibility": 1.0,
            "temporal_compatibility": 1.0,
            "geographic_compatibility": 1.0,
            "review_completeness": 1.0 if review_state == "APPROVED" else 0.0,
        },
    }


def test_taxonomic_inference_preserves_evidence_and_has_no_publication_authority():
    service = ScientificInferenceService()
    result = service.build(
        domain=InferenceDomain.TAXONOMY,
        statement="The supplied evidence supports the proposed taxon identity.",
        aggregates=[aggregate()],
        assumptions=["Canonical taxon identifiers are current for this analysis."],
    )

    assert result.state == InferenceState.CANDIDATE
    assert result.domain == InferenceDomain.TAXONOMY
    assert result.aggregate_refs[0]["aggregate_id"] == 1
    assert result.source_anchor_refs[0]["source_anchor_ids"] == (10000,)
    assert result.confidence_score >= 0.8
    assert result.confidence_band == "HIGH"
    assert result.confidence_interpretation == "HEURISTIC_EVIDENCE_SUPPORT_INDEX"
    assert result.confidence_is_probability is False
    assert result.confidence_calibrated is False
    assert result.review_required is True
    assert result.reviewed_conclusion is False
    assert result.published is False
    assert result.scientific_publication_authorized is False
    assert result.knowledge_graph_mutation_authorized is False
    assert result.provenance["confidence_is_probability"] is False
    assert result.provenance["confidence_calibrated"] is False
    assert result.provenance["inference_is_not_source_evidence"] is True


def test_ecological_relationship_conflict_requires_review_and_reduces_confidence():
    service = ScientificInferenceService()
    clean = service.build(
        domain=InferenceDomain.RELATIONSHIP,
        statement="The orchid is associated with the supplied pollinator taxon.",
        aggregates=[aggregate(aggregate_type="POLLINATOR_ASSOCIATION_AGGREGATE")],
    )
    conflicted = service.build(
        domain=InferenceDomain.RELATIONSHIP,
        statement="The orchid is associated with the supplied pollinator taxon.",
        aggregates=[
            aggregate(
                aggregate_type="POLLINATOR_ASSOCIATION_AGGREGATE",
                contradicting=1,
                unresolved=1,
            )
        ],
    )

    assert conflicted.state == InferenceState.CONFLICT_REVIEW_REQUIRED
    assert conflicted.confidence_score < clean.confidence_score
    assert conflicted.conflict_summary["contradicting_assertions"] == 1
    assert "CONTRADICTORY_EVIDENCE_PRESENT" in conflicted.known_limitations
    assert "UNRESOLVED_EVIDENCE_RELATIONSHIPS_PRESENT" in conflicted.known_limitations


def test_conservation_inference_retains_multiple_aggregate_provenance():
    service = ScientificInferenceService()
    result = service.build(
        domain=InferenceDomain.CONSERVATION,
        statement="The evidence supports treating the assessed pressure as a conservation concern.",
        aggregates=[
            aggregate(aggregate_id=1, aggregate_type="CONSERVATION_THREAT_AGGREGATE"),
            aggregate(aggregate_id=2, aggregate_type="GEOGRAPHIC_DISTRIBUTION_AGGREGATE"),
        ],
        limitations=["No population viability model was supplied."],
    )

    assert {ref["aggregate_id"] for ref in result.aggregate_refs} == {1, 2}
    assert len(result.source_anchor_refs) == 2
    assert "No population viability model was supplied." in result.known_limitations
    assert result.reviewed_conclusion is False


def test_unreviewed_evidence_cannot_become_candidate_conclusion():
    service = ScientificInferenceService()
    result = service.build(
        domain=InferenceDomain.ECOLOGY,
        statement="The evidence suggests the supplied habitat association.",
        aggregates=[
            aggregate(
                aggregate_type="HABITAT_AGGREGATE",
                review_state="REQUIRED",
                verification_state="UNVERIFIED",
            )
        ],
    )

    assert result.state == InferenceState.REVIEW_REQUIRED
    assert "HUMAN_REVIEW_INCOMPLETE" in result.known_limitations
    assert result.review_required is True


@pytest.mark.parametrize("status", ["WITHDRAWN", "SUPERSEDED"])
def test_withdrawn_or_superseded_aggregate_fails_closed(status: str):
    service = ScientificInferenceService()
    result = service.build(
        domain=InferenceDomain.GENERAL,
        statement="This inference must not advance from inactive evidence.",
        aggregates=[aggregate(aggregate_status=status)],
    )

    assert result.state == InferenceState.INSUFFICIENT_EVIDENCE
    assert f"AGGREGATE_STATUS_{status}" in result.known_limitations
    assert result.reviewed_conclusion is False
    assert result.published is False


@pytest.mark.parametrize(
    "status",
    [
        "NEEDS_REVIEW",
        "TAXONOMICALLY_AMBIGUOUS",
        "METHOD_DEPENDENT",
        "GEOGRAPHICALLY_LIMITED",
        "TEMPORALLY_LIMITED",
        "MIXED_EVIDENCE",
        "CONFLICTING",
        "LIMITED_EVIDENCE",
        "SINGLE_SOURCE",
    ],
)
def test_review_consensus_statuses_cannot_become_clean_candidate(status: str):
    service = ScientificInferenceService()
    result = service.build(
        domain=InferenceDomain.GENERAL,
        statement="This inference remains review-bound by aggregate consensus status.",
        aggregates=[aggregate(aggregate_status=status)],
    )

    assert result.state == InferenceState.REVIEW_REQUIRED
    assert f"AGGREGATE_STATUS_{status}" in result.known_limitations
    assert result.review_required is True


def test_missing_source_anchors_fail_closed_as_insufficient_evidence():
    service = ScientificInferenceService()
    result = service.build(
        domain=InferenceDomain.GENERAL,
        statement="A synthesis was proposed from an aggregate without source anchors.",
        aggregates=[aggregate(anchors=False)],
    )

    assert result.state == InferenceState.INSUFFICIENT_EVIDENCE
    assert result.source_anchor_refs == ()


def test_inference_id_is_deterministic_and_changes_with_evidence_identity():
    service = ScientificInferenceService()
    kwargs = {
        "domain": InferenceDomain.TAXONOMY,
        "statement": "The supplied evidence supports the proposed taxon identity.",
        "assumptions": ["Names are interpreted under the same taxonomic concept."],
    }
    first = service.build(aggregates=[aggregate(aggregate_id=1)], **kwargs)
    second = service.build(aggregates=[aggregate(aggregate_id=1)], **kwargs)
    changed = service.build(aggregates=[aggregate(aggregate_id=2)], **kwargs)

    assert first.inference_id == second.inference_id
    assert first.inference_id != changed.inference_id


def test_missing_aggregate_identity_is_rejected():
    service = ScientificInferenceService()
    bad = aggregate()
    del bad["identity_hash"]

    with pytest.raises(ValueError, match="AGGREGATE_IDENTITY_REQUIRED"):
        service.build(
            domain=InferenceDomain.GENERAL,
            statement="This should fail before inference construction.",
            aggregates=[bad],
        )
