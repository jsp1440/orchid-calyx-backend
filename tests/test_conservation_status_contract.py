from __future__ import annotations

import json

import pytest

from app.calyx_orchestrator.conservation_status import (
    ConservationEvidenceState,
    ConservationRecord,
    LocalityProtectionGateway,
    LocalityState,
    build_unavailable_conservation_matrix,
    choose_conservation_record,
    serialize_conservation_snapshot,
)


def _record(source_class: str, *, state: ConservationEvidenceState, code: str | None) -> ConservationRecord:
    return ConservationRecord(
        taxon_id="taxon:1",
        scientific_name="Phragmipedium kovachii",
        status_authority="IUCN",
        status_code=code,
        assessment_date="2026-01-01" if code else None,
        source_version="2026.1" if code else None,
        source_class=source_class,
        evidence_state=state,
    )


def test_protected_and_private_locality_are_withheld() -> None:
    gateway = LocalityProtectionGateway()
    locality = {"country": "Peru", "latitude": -6.1, "longitude": -77.2}

    assert gateway.serialize_locality(locality, protected=True) == {
        "state": "WITHHELD",
        "locality": None,
    }
    assert gateway.serialize_locality(locality, private=True) == {
        "state": "WITHHELD",
        "locality": None,
    }


def test_unprotected_serialization_still_strips_exact_coordinates_and_collection_ids() -> None:
    payload = LocalityProtectionGateway().serialize_locality(
        {
            "country": "Peru",
            "region": "Amazonas",
            "latitude": -6.1,
            "longitude": -77.2,
            "collection_id": "restricted-collection-9",
            "nested": {"gps": "secret", "summary": "regional only"},
        }
    )
    encoded = json.dumps(payload).casefold()
    assert payload["state"] == LocalityState.AVAILABLE.value
    assert '"latitude"' not in encoded
    assert '"longitude"' not in encoded
    assert '"collection_id"' not in encoded
    assert '"gps"' not in encoded
    assert "regional only" in encoded


def test_authoritative_reviewed_record_outranks_unreviewed_import() -> None:
    selected = choose_conservation_record(
        [
            _record("external_import", state=ConservationEvidenceState.REVIEW_REQUIRED, code="EN"),
            _record("authoritative_unreviewed", state=ConservationEvidenceState.REVIEW_REQUIRED, code="EN"),
            _record("authoritative_reviewed", state=ConservationEvidenceState.VERIFIED, code="CR"),
        ]
    )
    assert selected is not None
    assert selected.source_class == "authoritative_reviewed"
    assert selected.status_code == "CR"


def test_unknown_evidence_cannot_be_promoted_to_a_status() -> None:
    with pytest.raises(ValueError, match="UNKNOWN conservation evidence cannot silently carry a status"):
        _record("external_import", state=ConservationEvidenceState.UNKNOWN, code="CR")


def test_unavailable_matrix_is_explicit_unknown_not_fabricated_status() -> None:
    payload = build_unavailable_conservation_matrix(taxon_id="taxon:missing")
    assert payload["state"] == "UNKNOWN"
    assert payload["record"] is None
    assert payload["reason"] == "conservation_source_unavailable"
    assert payload["locality"]["state"] == "UNKNOWN"
    assert payload["production_mutation"] is False
    assert payload["taxonomy_activation"] is False


def test_snapshot_serialization_preserves_protected_locality_boundary() -> None:
    payload = serialize_conservation_snapshot(
        [_record("authoritative_reviewed", state=ConservationEvidenceState.VERIFIED, code="CR")],
        locality={
            "country": "Peru",
            "private_locality": "restricted canyon",
            "coordinates": [-6.1, -77.2],
            "catalogue_number": "ABC-123",
        },
        protected_locality=True,
    )
    encoded = json.dumps(payload).casefold()
    assert payload["state"] == "VERIFIED"
    assert payload["record"]["status_code"] == "CR"
    assert payload["locality"] == {"state": "WITHHELD", "locality": None}
    assert "restricted canyon" not in encoded
    assert "abc-123" not in encoded
    assert payload["production_mutation"] is False
    assert payload["taxonomy_activation"] is False


def test_no_records_stays_unknown_even_when_locality_summary_exists() -> None:
    payload = serialize_conservation_snapshot([], locality={"country": "Peru"})
    assert payload["state"] == "UNKNOWN"
    assert payload["record"] is None
    assert payload["reason"] == "no_reviewable_conservation_record"
    assert payload["locality"]["state"] == "AVAILABLE"
