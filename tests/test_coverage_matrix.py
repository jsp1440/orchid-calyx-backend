"""Tests for OC-COMPLETE-003 coverage matrix.

Covers the core invariants from issue #1085:
- Unavailable-state semantics: no domain reports absent from a failed query
- Masking detection: unselected large relation → warning in backfill list
- Stale-data handling: generated_at, evidence_state on every metric
- No production KG mutation
- No fabricated zero: db=None → all unavailable, never 0
- All domain names present in output
- Backfill list is prioritized and deduplicated
- Literature pipeline section separable from relationship measurements
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.readiness.coverage_matrix import (
    SCHEMA_VERSION,
    _prioritized_backfill,
    _taxonomy_summary,
    build_coverage_matrix,
)
from app.readiness.relationship_measurement import _unavailable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ALL_DOMAIN_KEYS = {
    "taxonomy_to_occurrences",
    "taxonomy_to_elevation",
    "taxonomy_to_climate",
    "taxonomy_to_literature",
    "taxonomy_to_pollinators",
    "taxonomy_to_mycorrhiza",
    "taxonomy_to_habitat",
    "taxonomy_to_conservation",
    "taxonomy_to_traits",
    "taxonomy_to_images",
}


# ---------------------------------------------------------------------------
# No-DB invariants: db=None → all domains unavailable, never 0
# ---------------------------------------------------------------------------


def test_no_db_returns_schema_version():
    result = build_coverage_matrix(None)
    assert result["schema_version"] == SCHEMA_VERSION


def test_no_db_returns_generated_at():
    result = build_coverage_matrix(None)
    assert "generated_at" in result
    assert result["generated_at"].endswith("+00:00") or result["generated_at"].endswith("Z")


def test_no_db_graph_mutation_false():
    result = build_coverage_matrix(None)
    assert result["graph_mutation"] is False


def test_no_db_all_domains_present():
    result = build_coverage_matrix(None)
    assert set(result["domains"].keys()) >= _ALL_DOMAIN_KEYS


def test_no_db_all_domains_unavailable_not_zero():
    result = build_coverage_matrix(None)
    for name, measurement in result["domains"].items():
        state = measurement.get("state")
        assert state == "unavailable", (
            f"Domain {name!r} reported state={state!r} without DB; "
            "expected 'unavailable' — never fabricate a zero."
        )
        # Must never carry a zero count that could be mistaken for measured
        assert "linked_object_count" not in measurement, (
            f"Domain {name!r} has linked_object_count without DB access"
        )


def test_no_db_interpretation_says_unknown_not_absent():
    result = build_coverage_matrix(None)
    for name, measurement in result["domains"].items():
        interp = measurement.get("interpretation", "")
        # The phrase "not a finding that … is absent" is the canonical denial form;
        # a bare "absent" without denial context would be the mistake.
        if "not a finding" not in interp.lower():
            assert "absent" not in interp.lower(), (
                f"Domain {name!r} used 'absent' without denial context: {interp!r}"
            )
        assert "unknown" in interp.lower() or "not a finding" in interp.lower(), (
            f"Domain {name!r} interpretation should clarify state is unknown: {interp!r}"
        )


def test_no_db_taxonomy_unavailable():
    result = build_coverage_matrix(None)
    assert result["taxonomy"]["state"] == "unavailable"


def test_no_db_kg_domains_all_unavailable():
    result = build_coverage_matrix(None)
    for key, val in result["kg_domain_readiness"].items():
        assert val["state"] == "unavailable", (
            f"KG domain {key!r} not marked unavailable when db=None"
        )


def test_no_db_literature_pipeline_unavailable():
    result = build_coverage_matrix(None)
    assert result["literature_pipeline"]["state"] == "unavailable"


def test_no_db_db_available_false():
    result = build_coverage_matrix(None)
    assert result["db_available"] is False


def test_no_db_backfill_list_populated():
    """Unavailable domains should all appear in the backfill list."""
    result = build_coverage_matrix(None)
    backfill = result["backfill_priority_list"]
    assert len(backfill) > 0
    domains_in_backfill = {item["domain"] for item in backfill}
    # Core domains must appear.
    for domain in (
        "taxonomy_to_occurrences",
        "taxonomy_to_literature",
        "taxonomy_to_traits",
    ):
        assert domain in domains_in_backfill, (
            f"Expected {domain!r} in backfill list when unavailable"
        )


# ---------------------------------------------------------------------------
# Masking detection
# ---------------------------------------------------------------------------


def test_prioritized_backfill_flags_masking_warnings():
    domains = {
        "taxonomy_to_occurrences": {
            "state": "measured",
            "linked_object_count": 26,
            "masking_warnings": [
                (
                    "public.orchid_occurrence exists with approximately 580,612 row(s), "
                    "far more than the measured source (26 row(s)); "
                    "this relationship measurement may be reading a non-authoritative relation."
                )
            ],
        }
    }
    backfill = _prioritized_backfill(domains)
    masked = [item for item in backfill if item["current_state"] == "masked"]
    assert len(masked) == 1
    assert "review_source_selection" == masked[0]["action"]
    assert "non-authoritative" in masked[0]["detail"]


def test_prioritized_backfill_flags_empty_measured_domain():
    domains = {
        "taxonomy_to_traits": {
            "state": "measured",
            "linked_object_count": 0,
        }
    }
    backfill = _prioritized_backfill(domains)
    empty_items = [
        item for item in backfill
        if item["domain"] == "taxonomy_to_traits" and item["current_state"] == "empty"
    ]
    assert len(empty_items) == 1
    assert empty_items[0]["action"] == "ingest"


def test_prioritized_backfill_does_not_flag_healthy_domain():
    domains = {
        "taxonomy_to_occurrences": {
            "state": "measured",
            "linked_object_count": 109195,
            "masking_warnings": [],
        }
    }
    backfill = _prioritized_backfill(domains)
    occurrence_items = [
        item for item in backfill
        if item["domain"] == "taxonomy_to_occurrences"
    ]
    # Healthy, non-masked domain with rows should not appear.
    assert len(occurrence_items) == 0


# ---------------------------------------------------------------------------
# Stale-data / evidence state
# ---------------------------------------------------------------------------


def test_taxonomy_summary_includes_evidence_state():
    """_taxonomy_summary must carry evidence_state so consumers can tell freshness."""
    cur = MagicMock()
    # First table check: table exists.
    cur.fetchone.side_effect = [
        {"present": True},     # to_regclass
        {"count": "12345"},    # COUNT(*)
    ]
    result = _taxonomy_summary(cur)
    assert "evidence_state" in result


def test_taxonomy_summary_reports_unavailable_when_no_table():
    cur = MagicMock()
    # All tables absent.
    cur.fetchone.return_value = {"present": False}
    result = _taxonomy_summary(cur)
    assert result["state"] == "unavailable"
    interp = result.get("interpretation", "")
    # The canonical denial form "not a finding that … is absent" is acceptable.
    if "not a finding" not in interp.lower():
        assert "absent" not in interp.lower(), f"Bare 'absent' in interpretation: {interp!r}"


def test_taxonomy_summary_falls_through_on_exception():
    cur = MagicMock()
    cur.fetchone.side_effect = Exception("connection lost")
    result = _taxonomy_summary(cur)
    assert result["state"] == "unavailable"


# ---------------------------------------------------------------------------
# No KG mutation invariant
# ---------------------------------------------------------------------------


def test_build_coverage_matrix_no_db_graph_mutation():
    result = build_coverage_matrix(None)
    assert result["graph_mutation"] is False


def test_build_coverage_matrix_live_cursor_graph_mutation_false():
    """Even with a live cursor the matrix must never set graph_mutation=True."""
    cur = MagicMock()
    # Make all queries return 'table absent' so measurement stays short.
    cur.fetchone.return_value = {"present": False}
    cur.fetchall.return_value = []

    with patch(
        "app.readiness.coverage_matrix.measure_declared_relationships",
        return_value={name: _unavailable(name, "table absent") for name in (
            "taxonomy_to_occurrences", "taxonomy_to_elevation",
            "taxonomy_to_climate", "taxonomy_to_literature",
            "taxonomy_to_pollinators", "taxonomy_to_mycorrhiza",
            "taxonomy_to_habitat", "taxonomy_to_conservation",
        )},
    ), patch(
        "app.readiness.coverage_matrix._measure_extra_domain",
        return_value=_unavailable("extra", "table absent"),
    ), patch(
        "app.readiness.coverage_matrix._kg_domain_readiness",
        return_value={},
    ), patch(
        "app.readiness.coverage_matrix._taxonomy_summary",
        return_value=_unavailable("taxonomy", "no table"),
    ):
        result = build_coverage_matrix(cur)

    assert result["graph_mutation"] is False


# ---------------------------------------------------------------------------
# Structure invariants
# ---------------------------------------------------------------------------


def test_result_has_all_required_top_level_keys():
    result = build_coverage_matrix(None)
    for key in (
        "schema_version",
        "generated_at",
        "graph_mutation",
        "db_available",
        "taxonomy",
        "domains",
        "kg_domain_readiness",
        "literature_pipeline",
        "backfill_priority_list",
    ):
        assert key in result, f"Missing top-level key {key!r}"


def test_all_domain_names_in_output():
    result = build_coverage_matrix(None)
    assert set(result["domains"].keys()) >= _ALL_DOMAIN_KEYS


def test_domains_include_traits_and_images():
    result = build_coverage_matrix(None)
    assert "taxonomy_to_traits" in result["domains"]
    assert "taxonomy_to_images" in result["domains"]


def test_backfill_items_have_required_fields():
    result = build_coverage_matrix(None)
    for item in result["backfill_priority_list"]:
        for field in ("domain", "priority", "action", "rationale", "current_state", "detail"):
            assert field in item, f"Backfill item missing field {field!r}: {item}"


def test_backfill_priority_values_are_valid():
    result = build_coverage_matrix(None)
    valid_priorities = {"P1", "P2", "P3", "P4"}
    for item in result["backfill_priority_list"]:
        assert item["priority"] in valid_priorities, (
            f"Invalid priority {item['priority']!r} in {item['domain']!r}"
        )


def test_backfill_occurrences_higher_priority_than_conservation():
    result = build_coverage_matrix(None)
    items = {item["domain"]: item for item in result["backfill_priority_list"]}
    occ = items.get("taxonomy_to_occurrences")
    cons = items.get("taxonomy_to_conservation")
    if occ and cons:
        # P1 < P3 numerically in our string ordering (but compare as ints).
        p_occ = int(occ["priority"][1])
        p_cons = int(cons["priority"][1])
        assert p_occ <= p_cons, (
            f"Occurrences ({occ['priority']}) should be >= priority than conservation ({cons['priority']})"
        )


# ---------------------------------------------------------------------------
# Literature pipeline absent without repository
# ---------------------------------------------------------------------------


def test_no_literature_repo_reports_unavailable():
    result = build_coverage_matrix(None, literature_repository=None)
    assert result["literature_pipeline"]["state"] == "unavailable"
    detail = result["literature_pipeline"].get("detail", "")
    # When cur=None the detail is about the missing cursor; when cur is present but
    # no repository was passed the detail names the missing repository argument.
    assert (
        "literature_repository" in detail.lower()
        or "database cursor" in detail.lower()
        or "not available" in detail.lower()
    ), f"Unexpected literature_pipeline detail: {detail!r}"


# ---------------------------------------------------------------------------
# Domain measurement isolation — one bad domain must not kill others
# ---------------------------------------------------------------------------


def test_measure_declared_relationships_isolation():
    """measure_declared_relationships wraps each spec; one exception → unavailable."""
    from app.readiness.relationship_measurement import measure_declared_relationships

    cur = MagicMock()
    # Raise on every query so all specs fail.
    cur.execute.side_effect = Exception("connection reset")
    cur.fetchone.side_effect = Exception("connection reset")

    results = measure_declared_relationships(cur)
    # Must return a result for every spec, not raise.
    assert isinstance(results, dict)
    assert len(results) > 0
    for name, result in results.items():
        assert result["state"] == "unavailable", (
            f"Domain {name!r} should be unavailable after exception, got {result['state']!r}"
        )
