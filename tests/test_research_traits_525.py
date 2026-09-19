from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.research_traits.routes import _subject
from app.research_traits.service import ResearchTraitsService, aggregate_trait_rows


def test_subject_requires_exactly_one_rank() -> None:
    with pytest.raises(HTTPException) as missing:
        _subject(None, None)
    assert missing.value.status_code == 422

    with pytest.raises(HTTPException) as duplicate:
        _subject("Cattleya", "Cattleya purpurata")
    assert duplicate.value.status_code == 422


def test_subject_preserves_exact_request_name() -> None:
    assert _subject("Cattleya", None) == ("genus", "Cattleya")
    assert _subject(None, "Cattleya purpurata") == (
        "species",
        "Cattleya purpurata",
    )


def test_distribution_preserves_zero_and_source_receipt() -> None:
    rows = [
        {
            "trait_id": "flower-size",
            "trait_name": "flower size",
            "trait_value": 0,
            "unit": "mm",
            "support_count": 3,
            "confidence_score": 0.8,
            "evidence_state": "AVAILABLE",
            "source_id": "traitbank",
            "record_id": "r-1",
            "source_url": "https://example.org/r-1",
            "license": "CC-BY-4.0",
        }
    ]

    result = aggregate_trait_rows(rows, source_table="oc_views.trait_resolved_v4")

    assert len(result) == 1
    assert result[0]["trait_id"] == "flower-size"
    assert result[0]["sample_size"] == 3
    assert result[0]["buckets"] == [{"value": 0, "count": 3}]
    assert result[0]["confidence"] == 0.8
    assert result[0]["receipts"][0]["record_id"] == "r-1"


def test_missing_count_and_sample_size_remain_unknown() -> None:
    rows = [
        {
            "trait_name": "growth form",
            "trait_value": "epiphyte",
            "evidence_state": "AVAILABLE",
            "record_id": "r-1",
        },
        {
            "trait_name": "growth form",
            "trait_value": "epiphyte",
            "evidence_state": "AVAILABLE",
            "record_id": "r-2",
        },
    ]

    result = aggregate_trait_rows(rows, source_table="oc_views.trait_resolved_v4")

    assert result[0]["buckets"] == [{"value": "epiphyte", "count": None}]
    assert result[0]["sample_size"] is None


@pytest.mark.parametrize("missing_count", [None, -1, 1.5, True, 9_007_199_254_740_992])
def test_partial_or_invalid_counts_do_not_become_complete_totals(missing_count) -> None:
    rows = [
        {"trait_name": "growth form", "trait_value": "epiphyte", "support_count": 4},
        {
            "trait_name": "growth form",
            "trait_value": "epiphyte",
            "support_count": missing_count,
        },
        {"trait_name": "growth form", "trait_value": "terrestrial", "support_count": 0},
    ]

    result = aggregate_trait_rows(rows, source_table="oc_views.trait_resolved_v4")[0]

    assert result["buckets"] == [
        {"value": "epiphyte", "count": None},
        {"value": "terrestrial", "count": 0},
    ]
    assert result["sample_size"] is None


def test_count_sums_cannot_overflow_frontend_safe_integer_contract() -> None:
    rows = [
        {"trait_name": "growth form", "trait_value": "epiphyte", "support_count": count}
        for count in (9_007_199_254_740_991, 1)
    ]

    result = aggregate_trait_rows(rows, source_table="oc_views.trait_resolved_v4")[0]

    assert result["buckets"] == [{"value": "epiphyte", "count": None}]
    assert result["sample_size"] is None


def test_sample_size_does_not_sum_only_the_reported_subset() -> None:
    rows = [
        {
            "trait_name": "growth form",
            "trait_value": "epiphyte",
            "count": 3,
            "sample_size": 3,
        },
        {"trait_name": "growth form", "trait_value": "terrestrial", "count": 2},
    ]

    result = aggregate_trait_rows(rows, source_table="oc_views.trait_resolved_v4")[0]

    assert result["sample_size"] is None


def test_non_value_state_cannot_carry_values_or_receipts() -> None:
    rows = [
        {
            "trait_name": "scent class",
            "trait_value": "floral",
            "evidence_state": "WITHHELD",
            "source_id": "restricted",
            "record_id": "secret-1",
        }
    ]

    result = aggregate_trait_rows(rows, source_table="oc_views.trait_resolved_v4")

    assert result[0]["evidence_state"] == "WITHHELD"
    assert result[0]["buckets"] == []
    assert result[0]["receipts"] == []
    assert result[0]["sample_size"] is None


@pytest.mark.parametrize("state", ["WITHHELD", "UNKNOWN", "UNAVAILABLE", "ABSENT"])
@pytest.mark.parametrize("unavailable_first", [False, True])
def test_mixed_non_value_state_remains_redacted(state, unavailable_first) -> None:
    rows = [
        {
            "trait_name": "scent class",
            "trait_value": "floral",
            "evidence_state": "AVAILABLE",
            "support_count": 3,
            "source_id": "public",
            "record_id": "public-1",
        },
        {
            "trait_name": "scent class",
            "trait_value": "restricted-value",
            "evidence_state": state,
            "support_count": 10,
            "source_id": "restricted",
            "record_id": "private-record",
        },
    ]
    if unavailable_first:
        rows.reverse()

    result = aggregate_trait_rows(rows, source_table="oc_views.trait_resolved_v4")[0]

    assert result["evidence_state"] == state
    assert result["buckets"] == []
    assert result["receipts"] == []
    assert result["sample_size"] is None
    assert result["confidence"] is None


def test_withheld_member_without_value_still_blocks_group_disclosure() -> None:
    rows = [
        {
            "trait_name": "scent class",
            "trait_value": "floral",
            "evidence_state": "AVAILABLE",
        },
        {
            "trait_name": "scent class",
            "trait_value": None,
            "evidence_state": "WITHHELD",
        },
    ]

    result = aggregate_trait_rows(rows, source_table="oc_views.trait_resolved_v4")[0]

    assert result["evidence_state"] == "WITHHELD"
    assert result["buckets"] == []
    assert result["receipts"] == []


def test_verified_without_record_identity_downgrades_to_provisional() -> None:
    rows = [
        {
            "trait_name": "growth form",
            "trait_value": "epiphyte",
            "evidence_state": "VERIFIED",
            "source_id": "traitbank",
        }
    ]

    result = aggregate_trait_rows(rows, source_table="oc_views.trait_resolved_v4")

    assert result[0]["evidence_state"] == "PROVISIONAL"


def test_unsafe_receipt_url_is_not_returned() -> None:
    rows = [
        {
            "trait_name": "growth form",
            "trait_value": "epiphyte",
            "evidence_state": "AVAILABLE",
            "source_id": "traitbank",
            "record_id": "r-1",
            "source_url": "https://user:secret@example.org/r-1",
        }
    ]

    result = aggregate_trait_rows(rows, source_table="oc_views.trait_resolved_v4")

    assert result[0]["receipts"][0]["source_url"] is None


class _TaxonCursor:
    def __init__(self, ids):
        self.ids = ids
        self.queries = []

    def execute(self, query, params):
        self.queries.append((query, params))

    def fetchall(self):
        return [(taxon_id,) for taxon_id in self.ids]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _TaxonService(ResearchTraitsService):
    def _table_exists(self, cur, table):
        return True

    def _columns(self, cur, table):
        return ("taxon_id", "scientific_name", "rank")


def test_ambiguous_exact_species_cannot_join_multiple_taxa_or_fallback_sources() -> (
    None
):
    cursor = _TaxonCursor(["taxon-a", "taxon-b"])

    resolved = _TaxonService()._resolve_taxon_ids(
        cursor, rank="species", name="Cattleya purpurata"
    )

    assert resolved == []
    assert len(cursor.queries) == 1


def test_ambiguous_species_returns_unknown_without_querying_trait_evidence() -> None:
    cursor = _TaxonCursor(["taxon-a", "taxon-b"])

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def cursor(self):
            return cursor

    class NoEvidenceReadService(_TaxonService):
        def _read_trait_rows(self, cur, taxon_ids):
            pytest.fail("Ambiguous taxonomy must stop before the evidence read")

    service = NoEvidenceReadService(
        database_url="fixture-only", connection_factory=lambda _: Connection()
    )

    assert service.get(rank="species", name="Cattleya purpurata") == {
        "contract_version": "oc-research-traits-v1",
        "subject": {"rank": "species", "name": "Cattleya purpurata"},
        "state": "UNKNOWN",
        "generated_at": None,
        "distributions": [],
    }
    assert len(cursor.queries) == 1


def test_unique_exact_species_still_resolves() -> None:
    cursor = _TaxonCursor(["taxon-a"])

    assert _TaxonService()._resolve_taxon_ids(
        cursor, rank="species", name="Cattleya purpurata"
    ) == ["taxon-a"]


def test_genus_can_resolve_multiple_species() -> None:
    cursor = _TaxonCursor(["taxon-a", "taxon-b"])

    assert _TaxonService()._resolve_taxon_ids(
        cursor, rank="genus", name="Cattleya"
    ) == ["taxon-a", "taxon-b"]
