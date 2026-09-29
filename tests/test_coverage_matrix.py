"""Tests for OC-COMPLETE-003 — scientific coverage/freshness/backfill matrix.

Covers:
- Fabricated-zero is forbidden (UNKNOWN, not 0, when unmeasured)
- Unavailable-state semantics: UNKNOWN covers every domain when DB absent
- Source precedence: canonical reviewed > canonical unreviewed > external fallback
- Stale-data detection: stale metrics are backfill candidates
- No promotion of unreviewed science (automatic_publication/KG mutation always False)
- Backfill priority ordering: BACKFILL_REQUIRED > STALE > UNKNOWN+source > UNKNOWN
- Deduplication: same metric_key appears only once in backfill task list
- Matrix serializable as JSON
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
    classify_source_precedence,
    compute_backfill_priority,
    serialize_matrix_as_json,
)

# ---------------------------------------------------------------------------
# DomainMetric — fabricated-zero guard
# ---------------------------------------------------------------------------


def test_measured_zero_with_source_allowed():
    m = DomainMetric(
        domain=CoverageDomain.OCCURRENCES,
        metric_key="backfill_debt",
        state=CoverageState.MEASURED,
        value=0,
        source_relation="oc_admin.occurrences",
    )
    assert m.value == 0
    assert m.source_relation


def test_measured_zero_without_source_forbidden():
    with pytest.raises(ValueError, match="FABRICATED_ZERO_FORBIDDEN"):
        DomainMetric(
            domain=CoverageDomain.OCCURRENCES,
            metric_key="total_records",
            state=CoverageState.MEASURED,
            value=0,
            source_relation="",
        )


def test_unknown_state_allows_none_value():
    m = DomainMetric(
        domain=CoverageDomain.TAXONOMY,
        metric_key="canonical_taxon_count",
        state=CoverageState.UNKNOWN,
        value=None,
    )
    assert m.value is None
    assert m.state == CoverageState.UNKNOWN


def test_unavailable_state_allows_none_value():
    m = DomainMetric(
        domain=CoverageDomain.KNOWLEDGE_GRAPH,
        metric_key="domain_readiness",
        state=CoverageState.UNAVAILABLE,
        value=None,
    )
    assert m.value is None


# ---------------------------------------------------------------------------
# DomainMetric — backfill candidate detection
# ---------------------------------------------------------------------------


def test_stale_metric_is_backfill_candidate():
    m = DomainMetric(
        domain=CoverageDomain.LITERATURE,
        metric_key="discovered_count",
        state=CoverageState.STALE,
        value=1200,
        source_relation="europe_pmc",
    )
    assert m.is_backfill_candidate is True


def test_backfill_required_is_backfill_candidate():
    m = DomainMetric(
        domain=CoverageDomain.TRAITS,
        metric_key="taxon_bound_count",
        state=CoverageState.BACKFILL_REQUIRED,
    )
    assert m.is_backfill_candidate is True


def test_unknown_is_backfill_candidate():
    m = DomainMetric(
        domain=CoverageDomain.MYCORRHIZA,
        metric_key="orchid_bound_count",
        state=CoverageState.UNKNOWN,
    )
    assert m.is_backfill_candidate is True


def test_measured_is_not_backfill_candidate():
    m = DomainMetric(
        domain=CoverageDomain.TAXONOMY,
        metric_key="canonical_taxon_count",
        state=CoverageState.MEASURED,
        value=28000,
        source_relation="gbif_backbone",
    )
    assert m.is_backfill_candidate is False


def test_not_applicable_is_not_backfill_candidate():
    m = DomainMetric(
        domain=CoverageDomain.MOLECULAR_SEQUENCE,
        metric_key="accession_linked",
        state=CoverageState.NOT_APPLICABLE,
    )
    assert m.is_backfill_candidate is False


# ---------------------------------------------------------------------------
# build_unavailable_matrix — unavailable-state semantics
# ---------------------------------------------------------------------------


def test_unavailable_matrix_has_all_domains():
    matrix = build_unavailable_matrix()
    domains = {m.domain for m in matrix.metrics}
    expected = set(CoverageDomain)
    assert expected <= domains, f"Missing domains: {expected - domains}"


def test_unavailable_matrix_every_metric_is_unknown():
    matrix = build_unavailable_matrix()
    for m in matrix.metrics:
        assert m.state == CoverageState.UNKNOWN, (
            f"{m.domain.value}.{m.metric_key} is {m.state.value}, expected UNKNOWN"
        )


def test_unavailable_matrix_every_value_is_none():
    matrix = build_unavailable_matrix()
    for m in matrix.metrics:
        assert m.value is None, (
            f"{m.domain.value}.{m.metric_key} has value={m.value!r}"
        )


def test_unavailable_matrix_no_auto_publication():
    matrix = build_unavailable_matrix()
    assert matrix.automatic_publication is False


def test_unavailable_matrix_no_kg_mutation():
    matrix = build_unavailable_matrix()
    assert matrix.knowledge_graph_mutation is False


def test_unavailable_matrix_no_fabricated_zero():
    matrix = build_unavailable_matrix()
    assert matrix.fabricated_zero is False


def test_unavailable_matrix_covers_taxonomy():
    matrix = build_unavailable_matrix()
    tax = matrix.metrics_by_domain(CoverageDomain.TAXONOMY)
    keys = {m.metric_key for m in tax}
    assert "canonical_taxon_count" in keys
    assert "release_version" in keys


def test_unavailable_matrix_covers_literature():
    matrix = build_unavailable_matrix()
    lit = matrix.metrics_by_domain(CoverageDomain.LITERATURE)
    keys = {m.metric_key for m in lit}
    assert "discovered_count" in keys
    assert "kg_ready_materialized" in keys


def test_unavailable_matrix_all_are_backfill_candidates():
    matrix = build_unavailable_matrix()
    assert all(m.is_backfill_candidate for m in matrix.metrics)


def test_unavailable_matrix_metric_ids_are_unique():
    matrix = build_unavailable_matrix()
    ids = [f"{m.domain}:{m.metric_key}" for m in matrix.metrics]
    assert len(ids) == len(set(ids)), "Duplicate metric keys found"


# ---------------------------------------------------------------------------
# CoverageMatrix — safety invariant enforcement
# ---------------------------------------------------------------------------


def test_matrix_raises_on_auto_publication():
    with pytest.raises(PermissionError, match="AUTO_PUBLICATION_FORBIDDEN"):
        CoverageMatrix(automatic_publication=True)


def test_matrix_raises_on_kg_mutation():
    with pytest.raises(PermissionError, match="KG_MUTATION_FORBIDDEN"):
        CoverageMatrix(knowledge_graph_mutation=True)


def test_matrix_raises_on_fabricated_zero():
    with pytest.raises(ValueError, match="FABRICATED_ZERO_FORBIDDEN"):
        CoverageMatrix(fabricated_zero=True)


def test_backfill_task_raises_on_auto_publication():
    with pytest.raises(PermissionError, match="AUTO_PUBLICATION_FORBIDDEN"):
        BackfillTask(
            domain=CoverageDomain.TAXONOMY,
            metric_key="k",
            priority=BackfillPriority.LOW,
            description="d",
            idempotency_key="k",
            automatic_publication=True,
        )


def test_backfill_task_raises_on_kg_mutation():
    with pytest.raises(PermissionError, match="KG_MUTATION_FORBIDDEN"):
        BackfillTask(
            domain=CoverageDomain.TAXONOMY,
            metric_key="k",
            priority=BackfillPriority.LOW,
            description="d",
            idempotency_key="k",
            knowledge_graph_mutation=True,
        )


# ---------------------------------------------------------------------------
# Source precedence rules
# ---------------------------------------------------------------------------


def test_source_precedence_canonical_reviewed_wins():
    value, rationale = classify_source_precedence(
        canonical_value=100,
        external_value=200,
        canonical_reviewed=True,
    )
    assert value == 100
    assert rationale == "canonical_db_read_through"


def test_source_precedence_canonical_unreviewed_beats_external():
    value, rationale = classify_source_precedence(
        canonical_value=50,
        external_value=200,
        canonical_reviewed=False,
    )
    assert value == 50
    assert rationale == "canonical_unreviewed"


def test_source_precedence_external_fallback_when_canonical_absent():
    value, rationale = classify_source_precedence(
        canonical_value=None,
        external_value=99,
        canonical_reviewed=True,
    )
    assert value == 99
    assert rationale == "external_discovery_fallback"


def test_source_precedence_both_absent_returns_unavailable():
    value, rationale = classify_source_precedence(
        canonical_value=None,
        external_value=None,
        canonical_reviewed=True,
    )
    assert value is None
    assert rationale == "unavailable"


def test_source_precedence_zero_canonical_not_silently_replaced_by_external():
    # canonical_value=0 WITH a source_relation is a valid measured zero,
    # not fabricated. It should win over external.
    value, rationale = classify_source_precedence(
        canonical_value=0,
        external_value=500,
        canonical_reviewed=True,
    )
    assert value == 0
    assert rationale == "canonical_db_read_through"


# ---------------------------------------------------------------------------
# compute_backfill_priority — ordering and deduplication
# ---------------------------------------------------------------------------


def test_backfill_critical_before_high_before_medium_before_low():
    matrix = CoverageMatrix(
        metrics=[
            DomainMetric(
                domain=CoverageDomain.TRAITS,
                metric_key="taxon_bound_count",
                state=CoverageState.BACKFILL_REQUIRED,
            ),
            DomainMetric(
                domain=CoverageDomain.LITERATURE,
                metric_key="discovered_count",
                state=CoverageState.STALE,
                value=100,
                source_relation="europe_pmc",
            ),
            DomainMetric(
                domain=CoverageDomain.POLLINATION,
                metric_key="orchid_bound_count",
                state=CoverageState.UNKNOWN,
                source_relation="gloBIdb",
            ),
            DomainMetric(
                domain=CoverageDomain.MYCORRHIZA,
                metric_key="fungus_resolved_count",
                state=CoverageState.UNKNOWN,
            ),
        ]
    )
    tasks = compute_backfill_priority(matrix)
    priorities = [t.priority for t in tasks]
    order = [BackfillPriority.CRITICAL, BackfillPriority.HIGH, BackfillPriority.MEDIUM, BackfillPriority.LOW]
    assert priorities == order


def test_backfill_deduplicates_same_key():
    m = DomainMetric(
        domain=CoverageDomain.TAXONOMY,
        metric_key="canonical_taxon_count",
        state=CoverageState.UNKNOWN,
    )
    matrix = CoverageMatrix(metrics=[m, m])
    tasks = compute_backfill_priority(matrix)
    keys = [t.idempotency_key for t in tasks]
    assert len(keys) == len(set(keys))


def test_backfill_measured_metrics_excluded():
    matrix = CoverageMatrix(
        metrics=[
            DomainMetric(
                domain=CoverageDomain.TAXONOMY,
                metric_key="canonical_taxon_count",
                state=CoverageState.MEASURED,
                value=28000,
                source_relation="gbif_backbone",
            )
        ]
    )
    tasks = compute_backfill_priority(matrix)
    assert len(tasks) == 0


def test_backfill_tasks_never_auto_publish():
    matrix = build_unavailable_matrix()
    tasks = compute_backfill_priority(matrix)
    for t in tasks:
        assert t.automatic_publication is False
        assert t.knowledge_graph_mutation is False


def test_backfill_tasks_all_require_review():
    matrix = build_unavailable_matrix()
    tasks = compute_backfill_priority(matrix)
    for t in tasks:
        assert t.review_required is True


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_matrix_serializable_as_json():
    matrix = build_unavailable_matrix()
    raw = serialize_matrix_as_json(matrix)
    parsed = json.loads(raw)
    assert parsed["schema_version"] == SCHEMA_VERSION


def test_matrix_json_no_secrets():
    matrix = build_unavailable_matrix()
    raw = serialize_matrix_as_json(matrix)
    for bad in ("sk-live-", "Bearer ", "api_key=", "password="):
        assert bad not in raw, f"Potential secret found: {bad}"


def test_matrix_json_contains_summary():
    matrix = build_unavailable_matrix()
    raw = serialize_matrix_as_json(matrix)
    parsed = json.loads(raw)
    assert "summary" in parsed
    assert parsed["summary"]["total_metrics"] == len(matrix.metrics)


def test_matrix_json_auto_publication_false():
    raw = serialize_matrix_as_json(build_unavailable_matrix())
    parsed = json.loads(raw)
    assert parsed["automatic_publication"] is False
    assert parsed["knowledge_graph_mutation"] is False
    assert parsed["fabricated_zero"] is False


def test_matrix_to_dict_has_all_domains():
    matrix = build_unavailable_matrix()
    d = matrix.to_dict()
    domains_in_metrics = {m["domain"] for m in d["metrics"]}
    expected = {dom.value for dom in CoverageDomain}
    assert expected <= domains_in_metrics


# ---------------------------------------------------------------------------
# CoverageMatrix accessors
# ---------------------------------------------------------------------------


def test_metrics_by_domain_filters_correctly():
    matrix = build_unavailable_matrix()
    tax = matrix.metrics_by_domain(CoverageDomain.TAXONOMY)
    assert all(m.domain == CoverageDomain.TAXONOMY for m in tax)


def test_metrics_by_state_filters_unknown():
    matrix = build_unavailable_matrix()
    unknowns = matrix.metrics_by_state(CoverageState.UNKNOWN)
    assert len(unknowns) == len(matrix.metrics)


def test_coverage_summary_counts_correct():
    matrix = build_unavailable_matrix()
    summary = matrix.coverage_summary()
    assert summary["total_metrics"] == len(matrix.metrics)
    assert summary["backfill_candidates"] == len(matrix.metrics)
