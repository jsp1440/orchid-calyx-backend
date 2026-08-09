from __future__ import annotations

from typing import Any

import pytest

from app.scientific_inference import (
    CanonicalAggregateResolutionError,
    CanonicalAggregateResolver,
)


class FakeResult:
    def __init__(self, *, one: dict[str, Any] | None = None, many: list[dict[str, Any]] | None = None):
        self.one = one
        self.many = many or []

    def mappings(self) -> "FakeResult":
        return self

    def one_or_none(self) -> dict[str, Any] | None:
        return self.one

    def all(self) -> list[dict[str, Any]]:
        return self.many


class FakeSession:
    def __init__(self, responses: list[FakeResult]):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, statement: Any, params: dict[str, Any]) -> FakeResult:
        self.calls.append((str(statement), params))
        return self.responses.pop(0)


def canonical_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "aggregate_version_id": 10,
        "aggregate_id": 1,
        "aggregate_type": "TAXON_IDENTITY_AGGREGATE",
        "identity_hash": "a" * 64,
        "aggregate_status": "SUPPORTED",
        "review_state": "APPROVED",
        "verification_state": "VERIFIED",
        "published": False,
        "aggregate_active": True,
        "version_active": True,
        "superseded_by_version_id": None,
        "summary": {
            "independent_sources": 2,
            "supporting_assertions": 3,
            "contradicting_assertions": 0,
            "unresolved_assertions": 0,
        },
        "contexts": {"taxonomic": {"canonical": True}},
        "provenance_chain": {"candidate_ids": [100, 101]},
    }
    row.update(overrides)
    return row


def confidence_row(**overrides: Any) -> dict[str, Any]:
    row = {
        "formula_version": "086b-confidence-1",
        "components": {
            "anchor_completeness": 1.0,
            "taxon_link_certainty": 0.95,
            "method_compatibility": 1.0,
            "temporal_compatibility": 1.0,
            "geographic_compatibility": 1.0,
            "review_completeness": 1.0,
        },
        "uncertainty": {"unresolved": 0},
        "score": 0.91,
        "score_is_truth_probability": False,
    }
    row.update(overrides)
    return row


def test_resolver_reconstructs_canonical_evidence_confidence_and_anchors():
    db = FakeSession(
        [
            FakeResult(one=canonical_row()),
            FakeResult(one=confidence_row()),
            FakeResult(
                many=[
                    {"candidate_id": 100, "source_revision_id": 1000, "anchor_id": 5000},
                    {"candidate_id": 101, "source_revision_id": 1001, "anchor_id": 5001},
                ]
            ),
        ]
    )

    result = CanonicalAggregateResolver(db).resolve_version(10)

    assert result["aggregate_version_id"] == 10
    assert result["aggregate_id"] == 1
    assert result["identity_hash"] == "a" * 64
    assert result["published"] is False
    assert result["confidence_dimensions"]["independent_sources"] == 2
    assert result["confidence_dimensions"]["taxon_link_certainty"] == 0.95
    assert result["canonical_confidence_assessment"]["score_is_truth_probability"] is False
    assert result["source_anchor_links"] == [
        {"candidate_id": 100, "revision_id": 1000, "anchor_ids": [5000]},
        {"candidate_id": 101, "revision_id": 1001, "anchor_ids": [5001]},
    ]
    assert all(call[1] == {"aggregate_version_id": 10} for call in db.calls)
    assert "oc_candidate_knowledge.aggregate_versions" in db.calls[0][0]
    assert "oc_candidate_knowledge.aggregate_confidence_assessments" in db.calls[1][0]
    assert "oc_candidate_knowledge.aggregate_evidence_links" in db.calls[2][0]


def test_resolver_rejects_inactive_or_superseded_version_before_confidence_lookup():
    inactive = FakeSession([FakeResult(one=canonical_row(version_active=False))])
    with pytest.raises(CanonicalAggregateResolutionError, match="NOT_ACTIVE"):
        CanonicalAggregateResolver(inactive).resolve_version(10)
    assert len(inactive.calls) == 1

    superseded = FakeSession(
        [FakeResult(one=canonical_row(superseded_by_version_id=11))]
    )
    with pytest.raises(CanonicalAggregateResolutionError, match="SUPERSEDED"):
        CanonicalAggregateResolver(superseded).resolve_version(10)
    assert len(superseded.calls) == 1


def test_resolver_rejects_missing_or_published_invalid_canonical_state():
    missing = FakeSession([FakeResult(one=None)])
    with pytest.raises(CanonicalAggregateResolutionError, match="NOT_FOUND"):
        CanonicalAggregateResolver(missing).resolve_version(10)

    published = FakeSession([FakeResult(one=canonical_row(published=True))])
    with pytest.raises(CanonicalAggregateResolutionError, match="PUBLISHED"):
        CanonicalAggregateResolver(published).resolve_version(10)


def test_resolver_rejects_truth_probability_confidence_assessment():
    db = FakeSession(
        [
            FakeResult(one=canonical_row()),
            FakeResult(one=confidence_row(score_is_truth_probability=True)),
        ]
    )
    with pytest.raises(CanonicalAggregateResolutionError, match="TRUTH_PROBABILITY"):
        CanonicalAggregateResolver(db).resolve_version(10)
    assert len(db.calls) == 2


def test_resolve_versions_rejects_duplicate_or_invalid_version_identity():
    resolver = CanonicalAggregateResolver(FakeSession([]))
    with pytest.raises(CanonicalAggregateResolutionError, match="DUPLICATE"):
        resolver.resolve_versions([10, 10])
    with pytest.raises(CanonicalAggregateResolutionError, match="INVALID"):
        resolver.resolve_version(0)
    with pytest.raises(CanonicalAggregateResolutionError, match="INVALID"):
        resolver.resolve_version(True)
