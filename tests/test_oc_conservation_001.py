"""Tests for OC-CONSERVATION-001.

Covers:
- WITHHELD enforcement in LocalityProtectionGateway
- UNKNOWN fallback in build_unavailable_conservation_matrix
- Fabricated-status prohibition (REVIEWED evidence requires known status code)
- Source precedence (REVIEWED > UNREVIEWED_IMPORT > UNAVAILABLE)
- Serialization safety (no sensitive locality fields)
"""
from __future__ import annotations

import json

import pytest

from app.calyx_flywheel.locality import SensitiveLocalityError
from app.scientific_adapter_lab.conservation_status import (
    SCHEMA_VERSION,
    ConservationRecord,
    ConservationStatusPrecedence,
    EvidenceState,
    LocalityProtectionGateway,
    StatusAuthority,
    StatusCode,
    build_unavailable_conservation_matrix,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _record(
    taxon_id: str = "taxon-001",
    taxon_name: str = "Cattleya labiata",
    status_code: StatusCode = StatusCode.VU,
    authority: StatusAuthority = StatusAuthority.IUCN,
    assessment_date: str = "2023-01-01",
    source_version: str = "IUCN Red List v2023-1",
    evidence_state: EvidenceState = EvidenceState.REVIEWED,
    notes: str = "",
) -> ConservationRecord:
    return ConservationRecord(
        taxon_id=taxon_id,
        taxon_name=taxon_name,
        status_code=status_code,
        authority=authority,
        assessment_date=assessment_date,
        source_version=source_version,
        evidence_state=evidence_state,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# LocalityProtectionGateway — WITHHELD enforcement
# ---------------------------------------------------------------------------


class TestLocalityProtectionGateway:
    def test_protected_returns_withheld(self):
        gw = LocalityProtectionGateway()
        assert gw.get_locality(is_protected=True, is_private=False) == "WITHHELD"

    def test_private_returns_withheld(self):
        gw = LocalityProtectionGateway()
        assert gw.get_locality(is_protected=False, is_private=True) == "WITHHELD"

    def test_both_returns_withheld(self):
        gw = LocalityProtectionGateway()
        assert gw.get_locality(is_protected=True, is_private=True) == "WITHHELD"

    def test_neither_returns_available(self):
        gw = LocalityProtectionGateway()
        assert gw.get_locality(is_protected=False, is_private=False) == "AVAILABLE"

    def test_assert_no_coordinate_leak_clean_dict(self):
        gw = LocalityProtectionGateway()
        gw.assert_no_coordinate_leak({"status": "VU", "taxon": "Cattleya"})  # must not raise

    def test_assert_no_coordinate_leak_raises_on_lat(self):
        gw = LocalityProtectionGateway()
        with pytest.raises(SensitiveLocalityError):
            gw.assert_no_coordinate_leak({"lat": 10.5, "status": "VU"})

    def test_assert_no_coordinate_leak_raises_on_longitude(self):
        gw = LocalityProtectionGateway()
        with pytest.raises(SensitiveLocalityError):
            gw.assert_no_coordinate_leak({"longitude": -84.1})

    def test_assert_no_coordinate_leak_raises_on_nested_locality(self):
        gw = LocalityProtectionGateway()
        with pytest.raises(SensitiveLocalityError):
            gw.assert_no_coordinate_leak({"meta": {"locality": "Cloud forest, Ecuador"}})

    def test_assert_no_coordinate_leak_raises_on_collector(self):
        gw = LocalityProtectionGateway()
        with pytest.raises(SensitiveLocalityError):
            gw.assert_no_coordinate_leak({"collector": "J. Smith"})


# ---------------------------------------------------------------------------
# UNKNOWN fallback — build_unavailable_conservation_matrix
# ---------------------------------------------------------------------------


class TestBuildUnavailableConservationMatrix:
    def test_returns_unknown_status_for_each_taxon(self):
        records = build_unavailable_conservation_matrix(["t1", "t2", "t3"])
        assert all(r.status_code == StatusCode.UNKNOWN for r in records)

    def test_returns_unavailable_evidence_state(self):
        records = build_unavailable_conservation_matrix(["t1"])
        assert records[0].evidence_state == EvidenceState.UNAVAILABLE

    def test_taxon_ids_preserved(self):
        taxon_ids = ["taxon-A", "taxon-B"]
        records = build_unavailable_conservation_matrix(taxon_ids)
        assert [r.taxon_id for r in records] == taxon_ids

    def test_empty_input_returns_empty_list(self):
        records = build_unavailable_conservation_matrix([])
        assert records == []

    def test_source_version_indicates_no_db(self):
        records = build_unavailable_conservation_matrix(["t1"])
        assert "NO_DB" in records[0].source_version


# ---------------------------------------------------------------------------
# Fabricated-status prohibition
# ---------------------------------------------------------------------------


class TestFabricatedStatusProhibition:
    def test_reviewed_with_known_status_is_valid(self):
        rec = _record(status_code=StatusCode.VU, evidence_state=EvidenceState.REVIEWED)
        rec.validate()  # must not raise

    def test_reviewed_with_unknown_status_raises(self):
        rec = _record(status_code=StatusCode.UNKNOWN, evidence_state=EvidenceState.REVIEWED)
        with pytest.raises(ValueError, match="CONSERVATION_RECORD_INVALID"):
            rec.validate()

    def test_unreviewed_with_unknown_status_is_valid(self):
        rec = _record(status_code=StatusCode.UNKNOWN, evidence_state=EvidenceState.UNREVIEWED_IMPORT)
        rec.validate()  # must not raise

    def test_unavailable_with_unknown_status_is_valid(self):
        rec = _record(status_code=StatusCode.UNKNOWN, evidence_state=EvidenceState.UNAVAILABLE)
        rec.validate()  # must not raise

    def test_empty_taxon_id_raises(self):
        rec = _record(taxon_id="")
        with pytest.raises(ValueError, match="taxon_id"):
            rec.validate()


# ---------------------------------------------------------------------------
# Source precedence
# ---------------------------------------------------------------------------


class TestConservationStatusPrecedence:
    def test_reviewed_beats_unreviewed_import(self):
        reviewed = _record(status_code=StatusCode.VU, evidence_state=EvidenceState.REVIEWED)
        unreviewed = _record(status_code=StatusCode.LC, evidence_state=EvidenceState.UNREVIEWED_IMPORT)
        prec = ConservationStatusPrecedence()
        winner = prec.resolve([unreviewed, reviewed])
        assert winner.evidence_state == EvidenceState.REVIEWED
        assert winner.status_code == StatusCode.VU

    def test_reviewed_beats_unavailable(self):
        reviewed = _record(status_code=StatusCode.EN, evidence_state=EvidenceState.REVIEWED)
        unavail = _record(status_code=StatusCode.UNKNOWN, evidence_state=EvidenceState.UNAVAILABLE)
        prec = ConservationStatusPrecedence()
        winner = prec.resolve([unavail, reviewed])
        assert winner.evidence_state == EvidenceState.REVIEWED

    def test_unreviewed_beats_unavailable(self):
        unreviewed = _record(status_code=StatusCode.NT, evidence_state=EvidenceState.UNREVIEWED_IMPORT)
        unavail = _record(status_code=StatusCode.UNKNOWN, evidence_state=EvidenceState.UNAVAILABLE)
        prec = ConservationStatusPrecedence()
        winner = prec.resolve([unavail, unreviewed])
        assert winner.evidence_state == EvidenceState.UNREVIEWED_IMPORT

    def test_single_record_returned_directly(self):
        rec = _record()
        prec = ConservationStatusPrecedence()
        assert prec.resolve([rec]) is rec

    def test_empty_list_raises(self):
        prec = ConservationStatusPrecedence()
        with pytest.raises(ValueError, match="CONSERVATION_PRECEDENCE_EMPTY"):
            prec.resolve([])

    def test_is_authoritative_true_for_reviewed(self):
        rec = _record(evidence_state=EvidenceState.REVIEWED)
        prec = ConservationStatusPrecedence()
        assert prec.is_authoritative(rec) is True

    def test_is_authoritative_false_for_unreviewed(self):
        rec = _record(evidence_state=EvidenceState.UNREVIEWED_IMPORT)
        prec = ConservationStatusPrecedence()
        assert prec.is_authoritative(rec) is False


# ---------------------------------------------------------------------------
# Serialization safety
# ---------------------------------------------------------------------------


class TestSerializationSafety:
    def test_to_safe_dict_has_schema_version(self):
        rec = _record()
        d = rec.to_safe_dict()
        assert d["schema_version"] == SCHEMA_VERSION

    def test_to_safe_dict_has_status_code(self):
        rec = _record(status_code=StatusCode.VU)
        d = rec.to_safe_dict()
        assert d["status_code"] == "VU"

    def test_to_safe_dict_has_evidence_state(self):
        rec = _record(evidence_state=EvidenceState.REVIEWED)
        d = rec.to_safe_dict()
        assert d["evidence_state"] == "REVIEWED"

    def test_serialize_as_json_roundtrip(self):
        rec = _record()
        raw = rec.serialize_as_json()
        parsed = json.loads(raw)
        assert parsed["schema_version"] == SCHEMA_VERSION
        assert parsed["taxon_id"] == "taxon-001"
        assert parsed["status_code"] == "VU"

    def test_serialize_as_json_no_private_coordinate_fields(self):
        rec = _record()
        raw = rec.serialize_as_json()
        parsed = json.loads(raw)
        forbidden = {"lat", "lon", "latitude", "longitude", "locality", "collector"}
        assert not forbidden & set(parsed.keys())

    def test_unavailable_matrix_records_serialize_safely(self):
        records = build_unavailable_conservation_matrix(["taxon-001"])
        for rec in records:
            raw = rec.serialize_as_json()
            parsed = json.loads(raw)
            assert parsed["status_code"] == "UNKNOWN"
            assert parsed["evidence_state"] == "UNAVAILABLE"
