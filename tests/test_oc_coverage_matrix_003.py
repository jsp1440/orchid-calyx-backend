"""Tests for OC-COMPLETE-003 — scientific coverage matrix schema and safety semantics.

Covers:
- Fabricated-zero prohibition (MEASURED + value 0 + no source → error)
- UNKNOWN state when DB is unavailable
- Governance invariants (no auto-publication, no KG mutation, no fabricated_zero)
- BackfillTask safety constraints (no auto-publication, no KG mutation)
- build_unavailable_matrix() completeness and correctness
- CoverageMatrix summary and query helpers
- Serialization safety
- Domain coverage spans all required scientific domains
"""
from __future__ import annotations

import json

import pytest

from app.scientific_adapter_lab.coverage_matrix import (
    SCHEMA_VERSION,
    BackfillPriority,
    BackfillTask,
    CoverageDomain,
    CoverageMatrix,
    CoverageState,
    DomainMetric,
    build_unavailable_matrix,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _metric(
    domain: CoverageDomain = CoverageDomain.TAXONOMY,
    key: str = "test_metric",
    state: CoverageState = CoverageState.UNKNOWN,
    value: int | float | str | None = None,
    source_relation: str = "",
) -> DomainMetric:
    return DomainMetric(
        domain=domain,
        metric_key=key,
        state=state,
        value=value,
        source_relation=source_relation,
    )


def _backfill(
    domain: CoverageDomain = CoverageDomain.TAXONOMY,
    key: str = "test_key",
    priority: BackfillPriority = BackfillPriority.HIGH,
    idempotency_key: str = "test-idem-001",
    auto_pub: bool = False,
    kg_mut: bool = False,
) -> BackfillTask:
    return BackfillTask(
        domain=domain,
        metric_key=key,
        priority=priority,
        description="test backfill",
        idempotency_key=idempotency_key,
        automatic_publication=auto_pub,
        knowledge_graph_mutation=kg_mut,
    )


# ---------------------------------------------------------------------------
# DomainMetric — fabricated-zero prohibition
# ---------------------------------------------------------------------------


class TestFabricatedZeroProhibition:
    def test_measured_zero_with_source_is_valid(self):
        m = _metric(state=CoverageState.MEASURED, value=0, source_relation="db:taxonomy.count")
        assert m.value == 0
        assert m.state == CoverageState.MEASURED

    def test_measured_zero_without_source_raises(self):
        with pytest.raises(ValueError, match="FABRICATED_ZERO_FORBIDDEN"):
            DomainMetric(
                domain=CoverageDomain.TAXONOMY,
                metric_key="canonical_taxon_count",
                state=CoverageState.MEASURED,
                value=0,
                source_relation="",
            )

    def test_unknown_zero_value_is_allowed(self):
        m = _metric(state=CoverageState.UNKNOWN, value=0)
        assert m.state == CoverageState.UNKNOWN

    def test_unknown_none_value_is_the_default(self):
        m = _metric(state=CoverageState.UNKNOWN)
        assert m.value is None

    def test_backfill_required_zero_no_source_is_not_flagged(self):
        m = _metric(state=CoverageState.BACKFILL_REQUIRED, value=0, source_relation="")
        assert m.value == 0

    def test_measured_nonzero_without_source_is_valid(self):
        m = _metric(state=CoverageState.MEASURED, value=42, source_relation="")
        assert m.value == 42


# ---------------------------------------------------------------------------
# DomainMetric — backfill candidate property
# ---------------------------------------------------------------------------


class TestBackfillCandidateProperty:
    def test_unknown_is_backfill_candidate(self):
        assert _metric(state=CoverageState.UNKNOWN).is_backfill_candidate is True

    def test_stale_is_backfill_candidate(self):
        assert _metric(state=CoverageState.STALE).is_backfill_candidate is True

    def test_backfill_required_is_backfill_candidate(self):
        assert _metric(state=CoverageState.BACKFILL_REQUIRED).is_backfill_candidate is True

    def test_measured_is_not_backfill_candidate(self):
        assert _metric(state=CoverageState.MEASURED).is_backfill_candidate is False

    def test_unavailable_is_not_backfill_candidate(self):
        assert _metric(state=CoverageState.UNAVAILABLE).is_backfill_candidate is False

    def test_not_applicable_is_not_backfill_candidate(self):
        assert _metric(state=CoverageState.NOT_APPLICABLE).is_backfill_candidate is False


# ---------------------------------------------------------------------------
# BackfillTask — governance constraints
# ---------------------------------------------------------------------------


class TestBackfillTaskGovernance:
    def test_auto_publication_raises(self):
        with pytest.raises(PermissionError, match="BACKFILL_TASK_AUTO_PUBLICATION_FORBIDDEN"):
            _backfill(auto_pub=True)

    def test_kg_mutation_raises(self):
        with pytest.raises(PermissionError, match="BACKFILL_TASK_KG_MUTATION_FORBIDDEN"):
            _backfill(kg_mut=True)

    def test_valid_task_created(self):
        t = _backfill()
        assert t.review_required is True
        assert t.automatic_publication is False
        assert t.knowledge_graph_mutation is False

    def test_all_priorities_valid(self):
        for p in BackfillPriority:
            t = _backfill(priority=p, idempotency_key=f"idem-{p.value}")
            assert t.priority == p


# ---------------------------------------------------------------------------
# CoverageMatrix — governance invariants
# ---------------------------------------------------------------------------


class TestCoverageMatrixGovernance:
    def test_default_matrix_has_safe_flags(self):
        m = CoverageMatrix()
        assert m.automatic_publication is False
        assert m.knowledge_graph_mutation is False
        assert m.fabricated_zero is False

    def test_auto_publication_true_raises(self):
        with pytest.raises(PermissionError, match="COVERAGE_MATRIX_AUTO_PUBLICATION_FORBIDDEN"):
            CoverageMatrix(automatic_publication=True)

    def test_kg_mutation_true_raises(self):
        with pytest.raises(PermissionError, match="COVERAGE_MATRIX_KG_MUTATION_FORBIDDEN"):
            CoverageMatrix(knowledge_graph_mutation=True)

    def test_fabricated_zero_true_raises(self):
        with pytest.raises(ValueError, match="COVERAGE_MATRIX_FABRICATED_ZERO_FORBIDDEN"):
            CoverageMatrix(fabricated_zero=True)


# ---------------------------------------------------------------------------
# build_unavailable_matrix() — completeness and safety
# ---------------------------------------------------------------------------


class TestBuildUnavailableMatrix:
    def test_all_metrics_unknown(self):
        mat = build_unavailable_matrix()
        assert all(m.state == CoverageState.UNKNOWN for m in mat.metrics)

    def test_no_metrics_have_non_none_value(self):
        mat = build_unavailable_matrix()
        assert all(m.value is None for m in mat.metrics)

    def test_schema_version_correct(self):
        mat = build_unavailable_matrix()
        assert mat.schema_version == SCHEMA_VERSION

    def test_all_required_domains_covered(self):
        mat = build_unavailable_matrix()
        present = {m.domain for m in mat.metrics}
        required = {
            CoverageDomain.TAXONOMY,
            CoverageDomain.OCCURRENCES,
            CoverageDomain.IMAGES_MEDIA,
            CoverageDomain.TRAITS,
            CoverageDomain.LITERATURE,
            CoverageDomain.POLLINATION,
            CoverageDomain.MYCORRHIZA,
            CoverageDomain.HABITAT,
            CoverageDomain.KNOWLEDGE_GRAPH,
            CoverageDomain.MOLECULAR_SEQUENCE,
        }
        assert required <= present, f"Missing domains: {required - present}"

    def test_no_fabricated_zero_flags(self):
        mat = build_unavailable_matrix()
        assert mat.fabricated_zero is False

    def test_no_auto_publication(self):
        mat = build_unavailable_matrix()
        assert mat.automatic_publication is False

    def test_no_kg_mutation(self):
        mat = build_unavailable_matrix()
        assert mat.knowledge_graph_mutation is False

    def test_generated_at_param_passed_through(self):
        mat = build_unavailable_matrix(generated_at="2026-01-01T00:00:00Z")
        assert mat.generated_at == "2026-01-01T00:00:00Z"

    def test_production_sha_param_passed_through(self):
        mat = build_unavailable_matrix(production_sha="abc123")
        assert mat.production_sha == "abc123"

    def test_taxonomy_metrics_present(self):
        mat = build_unavailable_matrix()
        keys = {m.metric_key for m in mat.metrics if m.domain == CoverageDomain.TAXONOMY}
        assert "canonical_taxon_count" in keys
        assert "release_version" in keys

    def test_occurrences_metrics_present(self):
        mat = build_unavailable_matrix()
        keys = {m.metric_key for m in mat.metrics if m.domain == CoverageDomain.OCCURRENCES}
        assert "total_records" in keys
        assert "backfill_debt" in keys
        assert "lat_lng_coverage_fraction" in keys

    def test_kg_metrics_present(self):
        mat = build_unavailable_matrix()
        keys = {m.metric_key for m in mat.metrics if m.domain == CoverageDomain.KNOWLEDGE_GRAPH}
        assert "domain_readiness" in keys
        assert "unresolved_link_queue_size" in keys

    def test_molecular_metrics_present(self):
        mat = build_unavailable_matrix()
        keys = {m.metric_key for m in mat.metrics if m.domain == CoverageDomain.MOLECULAR_SEQUENCE}
        assert "sequence_record_count" in keys
        assert "accession_linked" in keys

    def test_minimum_metric_count(self):
        mat = build_unavailable_matrix()
        assert len(mat.metrics) >= 40


# ---------------------------------------------------------------------------
# CoverageMatrix query helpers
# ---------------------------------------------------------------------------


class TestCoverageMatrixHelpers:
    def _mat(self) -> CoverageMatrix:
        return CoverageMatrix(
            metrics=[
                _metric(domain=CoverageDomain.TAXONOMY, key="k1", state=CoverageState.UNKNOWN),
                _metric(domain=CoverageDomain.TAXONOMY, key="k2", state=CoverageState.STALE),
                _metric(domain=CoverageDomain.OCCURRENCES, key="k3", state=CoverageState.MEASURED,
                        value=100, source_relation="db:occ"),
                _metric(domain=CoverageDomain.LITERATURE, key="k4",
                        state=CoverageState.BACKFILL_REQUIRED),
            ]
        )

    def test_metrics_by_domain_taxonomy(self):
        mat = self._mat()
        result = mat.metrics_by_domain(CoverageDomain.TAXONOMY)
        assert len(result) == 2
        assert all(m.domain == CoverageDomain.TAXONOMY for m in result)

    def test_metrics_by_domain_occurrences(self):
        mat = self._mat()
        result = mat.metrics_by_domain(CoverageDomain.OCCURRENCES)
        assert len(result) == 1

    def test_metrics_by_state_unknown(self):
        mat = self._mat()
        result = mat.metrics_by_state(CoverageState.UNKNOWN)
        assert len(result) == 1

    def test_backfill_candidates_excludes_measured(self):
        mat = self._mat()
        candidates = mat.backfill_candidates()
        keys = {m.metric_key for m in candidates}
        assert "k1" in keys
        assert "k2" in keys
        assert "k4" in keys
        assert "k3" not in keys

    def test_coverage_summary_total(self):
        mat = self._mat()
        summary = mat.coverage_summary()
        assert summary["total_metrics"] == 4

    def test_coverage_summary_backfill_candidates_count(self):
        mat = self._mat()
        summary = mat.coverage_summary()
        assert summary["backfill_candidates"] == 3


# ---------------------------------------------------------------------------
# Serialization safety
# ---------------------------------------------------------------------------


class TestSerializationSafety:
    def test_domain_metric_to_dict_has_schema_keys(self):
        m = _metric()
        d = m.to_dict()
        for k in ("domain", "metric_key", "state", "value", "source_relation",
                   "source_version", "generated_at", "evidence_state", "is_backfill_candidate"):
            assert k in d

    def test_backfill_task_to_dict_has_governance_keys(self):
        t = _backfill()
        d = t.to_dict()
        assert d["automatic_publication"] is False
        assert d["knowledge_graph_mutation"] is False
        assert d["review_required"] is True

    def test_coverage_matrix_to_dict_has_schema_version(self):
        mat = build_unavailable_matrix(generated_at="2026-01-01T00:00:00Z")
        d = mat.to_dict()
        assert d["schema_version"] == SCHEMA_VERSION
        assert "summary" in d
        assert "metrics" in d
        assert "backfill_tasks" in d

    def test_matrix_serializes_to_json(self):
        mat = build_unavailable_matrix(generated_at="2026-09-08T00:00:00Z")
        raw = json.dumps(mat.to_dict())
        parsed = json.loads(raw)
        assert parsed["schema_version"] == SCHEMA_VERSION
        assert parsed["automatic_publication"] is False
        assert len(parsed["metrics"]) >= 40

    def test_no_credential_fields_in_serialized_output(self):
        mat = build_unavailable_matrix()
        raw = json.dumps(mat.to_dict())
        for forbidden in ("password", "secret", "api_key", "token", "credential"):
            assert forbidden not in raw.lower()

    def test_unavailable_matrix_has_no_non_none_values(self):
        mat = build_unavailable_matrix()
        parsed = json.loads(json.dumps(mat.to_dict()))
        for m in parsed["metrics"]:
            assert m["value"] is None, f"Expected None for {m['metric_key']}, got {m['value']}"
