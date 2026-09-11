from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.research_traits.routes import _subject
from app.research_traits.service import aggregate_trait_rows


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


def test_missing_count_is_not_treated_as_zero() -> None:
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

    assert result[0]["buckets"] == [{"value": "epiphyte", "count": 2}]
    assert result[0]["sample_size"] == 2


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
