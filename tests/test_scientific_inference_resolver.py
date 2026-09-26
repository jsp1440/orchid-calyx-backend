from __future__ import annotations

from pathlib import Path

import pytest

import app.evidence_aggregation.routes as aggregation_routes
from app.evidence_aggregation.models import CandidateInput
from app.evidence_aggregation.repository import MemoryAggregateRepository
from app.evidence_aggregation.service import EvidenceAggregationService
from app.scientific_inference import (
    CanonicalAggregateResolutionError,
    CanonicalAggregateResolver,
    InferenceDomain,
    ScientificInferenceService,
)

DOMAIN = InferenceDomain.ECOLOGY


def candidate(i: int, value: str = "bee") -> CandidateInput:
    return CandidateInput(
        candidate_id=i,
        candidate_version=1,
        candidate_type="POLLINATOR_ASSOCIATION",
        normalized_subject="Dracula vampira",
        predicate="pollinated_by",
        object_value=value,
        source_revision_id=1000 + i,
        source_document_id=f"doc-{i}",
        source_anchor_ids=(5000 + i,),
        source_class="PRIMARY",
        evidence_type="DIRECT_OBSERVATION",
        directness="DIRECT_OBSERVATION",
        source_lineage=f"study-{i}",
        document_hash=f"hash-{i}",
        confidence=0.8,
        display_policy="FULL_TEXT_ALLOWED",
    )


def store(*candidate_ids: int):
    repository = MemoryAggregateRepository()
    service = EvidenceAggregationService(repository)
    plan = service.preview([candidate(i) for i in candidate_ids])
    service.execute(plan["aggregate_run_id"])
    return repository, service


def resolver(repository) -> CanonicalAggregateResolver:
    return CanonicalAggregateResolver(lambda: repository)


def test_resolver_reconstructs_canonical_evidence_confidence_and_anchors_from_runtime_store():
    repository, _ = store(100, 101)
    version = repository.versions[0]

    result = resolver(repository).resolve_version(version["aggregate_version_id"])

    assert result["aggregate_version_id"] == version["aggregate_version_id"]
    assert result["aggregate_id"] == version["aggregate_id"]
    assert result["identity_hash"] == version["identity_hash"]
    assert result["published"] is False
    assert result["confidence_dimensions"]["independent_sources"] == 2
    assert result["confidence_dimensions"]["score_is_truth_probability"] is False
    assert result["canonical_confidence_assessment"] is None
    assert result["source_anchor_links"] == [
        {"candidate_id": 100, "revision_id": 1100, "anchor_ids": [5100]},
        {"candidate_id": 101, "revision_id": 1101, "anchor_ids": [5101]},
    ]
    assert result["canonical_provenance_chain"] == version["provenance_chain"]
    assert result["canonical_contexts"]["taxonomic"] == version["taxonomic_context"]
    envelope = ScientificInferenceService().build(
        domain=DOMAIN,
        statement="Dracula vampira is visited by bees.",
        aggregates=[result],
    )
    assert envelope.aggregate_refs[0]["aggregate_version_id"] == version["aggregate_version_id"]


def test_resolver_output_is_isolated_from_the_store():
    repository, _ = store(100)
    version_id = repository.versions[0]["aggregate_version_id"]
    result = resolver(repository).resolve_version(version_id)
    result["source_anchor_links"].clear()
    result["confidence_dimensions"]["independent_sources"] = 99
    assert repository.versions[0]["source_anchor_links"]
    assert repository.versions[0]["confidence_dimensions"]["independent_sources"] == 1


def test_resolver_rejects_superseded_and_withdrawn_versions():
    repository, service = store(100, 101)
    first_version = repository.versions[0]["aggregate_version_id"]
    plan = service.preview([candidate(i) for i in (100, 101, 102)])
    service.execute(plan["aggregate_run_id"])
    assert len(repository.versions) == 2
    with pytest.raises(CanonicalAggregateResolutionError, match="NOT_ACTIVE|SUPERSEDED"):
        resolver(repository).resolve_version(first_version)

    current = repository.versions[-1]
    resolver(repository).resolve_version(current["aggregate_version_id"])
    service.supersede(current["aggregate_id"], "WITHDRAWN: retracted", "owner")
    with pytest.raises(CanonicalAggregateResolutionError, match="NOT_ACTIVE|SUPERSEDED"):
        resolver(repository).resolve_version(current["aggregate_version_id"])


def test_resolver_rejects_missing_or_published_invalid_canonical_state():
    repository, _ = store(100)
    with pytest.raises(CanonicalAggregateResolutionError, match="NOT_FOUND"):
        resolver(repository).resolve_version(987654)
    repository.versions[0]["published"] = True
    with pytest.raises(CanonicalAggregateResolutionError, match="PUBLISHED"):
        resolver(repository).resolve_version(repository.versions[0]["aggregate_version_id"])


def test_resolver_rejects_truth_probability_confidence():
    repository, _ = store(100)
    repository.versions[0]["confidence_dimensions"]["score_is_truth_probability"] = True
    with pytest.raises(CanonicalAggregateResolutionError, match="TRUTH_PROBABILITY"):
        resolver(repository).resolve_version(repository.versions[0]["aggregate_version_id"])


def test_resolve_versions_rejects_duplicate_or_invalid_version_identity():
    repository, _ = store(100)
    checker = resolver(repository)
    with pytest.raises(CanonicalAggregateResolutionError, match="DUPLICATE"):
        checker.resolve_versions([10, 10])
    with pytest.raises(CanonicalAggregateResolutionError, match="REQUIRED"):
        checker.resolve_versions([])
    with pytest.raises(CanonicalAggregateResolutionError, match="INVALID"):
        checker.resolve_version(0)
    with pytest.raises(CanonicalAggregateResolutionError, match="INVALID"):
        checker.resolve_version(True)
    version_id = repository.versions[0]["aggregate_version_id"]
    assert [x["aggregate_version_id"] for x in checker.resolve_versions([version_id])] == [version_id]


def test_resolver_fails_closed_when_store_is_unavailable(monkeypatch):
    def unavailable():
        raise RuntimeError("database unreachable")

    for provider in (unavailable, lambda: None):
        with pytest.raises(CanonicalAggregateResolutionError, match="STORE_UNAVAILABLE"):
            CanonicalAggregateResolver(provider).resolve_version(1)

    monkeypatch.setattr(aggregation_routes, "REPOSITORY", None)
    monkeypatch.setattr(aggregation_routes, "SERVICE", None)
    with pytest.raises(CanonicalAggregateResolutionError, match="STORE_UNAVAILABLE"):
        CanonicalAggregateResolver().resolve_version(1)


def test_default_resolver_reads_the_serving_aggregation_repository(monkeypatch):
    repository, service = store(100)
    monkeypatch.setattr(aggregation_routes, "REPOSITORY", repository)
    monkeypatch.setattr(aggregation_routes, "SERVICE", service)
    version_id = repository.versions[0]["aggregate_version_id"]
    assert CanonicalAggregateResolver().resolve_version(version_id)["aggregate_version_id"] == version_id


def test_resolver_does_not_read_unwritten_relational_aggregate_tables():
    source = Path("app/scientific_inference/canonical_resolver.py").read_text()
    assert "aggregate_assertions" not in source
    assert "aggregate_confidence_assessments" not in source
    assert "sqlalchemy" not in source
