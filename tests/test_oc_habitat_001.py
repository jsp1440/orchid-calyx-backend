"""Tests for OC-HABITAT-001 — Habitat, elevation, and geospatial reconciliation pipeline.

Covers:
- UNKNOWN fallback (GeospatialGateway unavailable, build_unavailable_habitat_matrix)
- Measured-vs-derived distinction (ElevationState enum, validate())
- Locality protection (sensitive locality clears elevation fields in serialization)
- Source precedence (reviewed_occurrence > modeled > estimated > unavailable)
- Serialization safety (no raw coordinates)
"""
from __future__ import annotations

import json

import pytest

from app.scientific_adapter_lab.habitat_elevation import (
    SCHEMA_VERSION,
    ClimateZone,
    ElevationState,
    GeospatialGateway,
    HabitatEvidenceState,
    HabitatRecord,
    HabitatType,
    build_unavailable_habitat_matrix,
    classify_elevation_source,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _record(
    taxon_id: str = "taxon-001",
    taxon_name: str = "Masdevallia coccinea",
    habitat_type: HabitatType = HabitatType.EPIPHYTE,
    climate_zone: ClimateZone = ClimateZone.MONTANE,
    elevation_min_m: float | None = 1800.0,
    elevation_max_m: float | None = 3200.0,
    elevation_typical_m: float | None = 2500.0,
    elevation_state: ElevationState = ElevationState.MEASURED,
    measurement_source: str = "idigbio:occurrence:2023",
    evidence_state: HabitatEvidenceState = HabitatEvidenceState.REVIEWED_OCCURRENCE,
    provenance_chain: tuple[str, ...] = ("source:idigbio", "reviewed:2023-01-01"),
    is_sensitive_locality: bool = False,
) -> HabitatRecord:
    return HabitatRecord(
        taxon_id=taxon_id,
        taxon_name=taxon_name,
        habitat_type=habitat_type,
        climate_zone=climate_zone,
        elevation_min_m=elevation_min_m,
        elevation_max_m=elevation_max_m,
        elevation_typical_m=elevation_typical_m,
        elevation_state=elevation_state,
        measurement_source=measurement_source,
        evidence_state=evidence_state,
        provenance_chain=provenance_chain,
        is_sensitive_locality=is_sensitive_locality,
    )


# ---------------------------------------------------------------------------
# ElevationState — measured vs. derived distinction
# ---------------------------------------------------------------------------


class TestElevationState:
    def test_measured_state_preserved(self):
        rec = _record(elevation_state=ElevationState.MEASURED)
        assert rec.elevation_state == ElevationState.MEASURED

    def test_derived_state_preserved(self):
        rec = _record(elevation_state=ElevationState.DERIVED)
        assert rec.elevation_state == ElevationState.DERIVED

    def test_estimated_state_preserved(self):
        rec = _record(elevation_state=ElevationState.ESTIMATED)
        assert rec.elevation_state == ElevationState.ESTIMATED

    def test_unknown_state_preserved(self):
        rec = _record(
            elevation_state=ElevationState.UNKNOWN,
            elevation_min_m=None,
            elevation_max_m=None,
            elevation_typical_m=None,
        )
        assert rec.elevation_state == ElevationState.UNKNOWN

    def test_unknown_elevation_is_none_not_zero(self):
        matrix = build_unavailable_habitat_matrix(["t1"])
        rec = matrix[0]
        assert rec.elevation_min_m is None
        assert rec.elevation_max_m is None
        assert rec.elevation_typical_m is None

    def test_non_unknown_state_with_all_none_elevations_raises(self):
        rec = _record(
            elevation_state=ElevationState.MEASURED,
            elevation_min_m=None,
            elevation_max_m=None,
            elevation_typical_m=None,
        )
        with pytest.raises(ValueError, match=r"ElevationState\.UNKNOWN"):
            rec.validate()

    def test_valid_record_passes_validate(self):
        rec = _record()
        rec.validate()  # must not raise


# ---------------------------------------------------------------------------
# GeospatialGateway — UNKNOWN fallback
# ---------------------------------------------------------------------------


class TestGeospatialGateway:
    def test_unavailable_returns_none(self):
        gw = GeospatialGateway(available=False)
        assert gw.get_elevation_m(lat=1.0, lon=2.0) is None

    def test_unavailable_never_returns_zero(self):
        gw = GeospatialGateway(available=False)
        assert gw.get_elevation_m(lat=0.0, lon=0.0) != 0

    def test_available_gateway_raises_not_implemented(self):
        gw = GeospatialGateway(available=True)
        with pytest.raises(NotImplementedError, match="GEOSPATIAL_GATEWAY_NOT_IMPLEMENTED"):
            gw.get_elevation_m(lat=1.0, lon=2.0)

    def test_default_gateway_is_unavailable(self):
        gw = GeospatialGateway()
        assert gw.is_available() is False

    def test_unavailable_stub_is_available_false(self):
        gw = GeospatialGateway(available=False)
        assert gw.is_available() is False


# ---------------------------------------------------------------------------
# Locality protection — sensitive locality clears elevation fields
# ---------------------------------------------------------------------------


class TestLocalityProtection:
    def test_sensitive_locality_clears_elevation_in_dict(self):
        rec = _record(is_sensitive_locality=True)
        d = rec.to_safe_dict()
        assert d["elevation_min_m"] is None
        assert d["elevation_max_m"] is None
        assert d["elevation_typical_m"] is None

    def test_non_sensitive_locality_preserves_elevation(self):
        rec = _record(is_sensitive_locality=False)
        d = rec.to_safe_dict()
        assert d["elevation_min_m"] == 1800.0
        assert d["elevation_max_m"] == 3200.0
        assert d["elevation_typical_m"] == 2500.0

    def test_to_safe_dict_never_contains_lat_lon_keys(self):
        rec = _record()
        d = rec.to_safe_dict()
        forbidden = {"lat", "lon", "latitude", "longitude", "locality", "collector"}
        assert not forbidden & set(d.keys())

    def test_unavailable_matrix_has_no_sensitive_locality_keys(self):
        records = build_unavailable_habitat_matrix(["t1"])
        for rec in records:
            d = rec.to_safe_dict()
            forbidden = {"lat", "lon", "latitude", "longitude", "locality", "collector"}
            assert not forbidden & set(d.keys())


# ---------------------------------------------------------------------------
# Source precedence
# ---------------------------------------------------------------------------


class TestClassifyElevationSource:
    def test_reviewed_beats_modeled(self):
        reviewed = _record(evidence_state=HabitatEvidenceState.REVIEWED_OCCURRENCE, taxon_id="t1")
        modeled = _record(evidence_state=HabitatEvidenceState.MODELED, taxon_id="t1")
        winner = classify_elevation_source([modeled, reviewed])
        assert winner.evidence_state == HabitatEvidenceState.REVIEWED_OCCURRENCE

    def test_reviewed_beats_estimated(self):
        reviewed = _record(evidence_state=HabitatEvidenceState.REVIEWED_OCCURRENCE)
        estimated = _record(evidence_state=HabitatEvidenceState.ESTIMATED)
        winner = classify_elevation_source([estimated, reviewed])
        assert winner.evidence_state == HabitatEvidenceState.REVIEWED_OCCURRENCE

    def test_modeled_beats_estimated(self):
        modeled = _record(evidence_state=HabitatEvidenceState.MODELED)
        estimated = _record(evidence_state=HabitatEvidenceState.ESTIMATED)
        winner = classify_elevation_source([estimated, modeled])
        assert winner.evidence_state == HabitatEvidenceState.MODELED

    def test_any_beats_unavailable(self):
        estimated = _record(evidence_state=HabitatEvidenceState.ESTIMATED)
        unavail = _record(evidence_state=HabitatEvidenceState.UNAVAILABLE,
                          elevation_state=ElevationState.UNKNOWN,
                          elevation_min_m=None, elevation_max_m=None, elevation_typical_m=None)
        winner = classify_elevation_source([unavail, estimated])
        assert winner.evidence_state == HabitatEvidenceState.ESTIMATED

    def test_empty_raises(self):
        with pytest.raises(ValueError, match="HABITAT_CLASSIFY_EMPTY"):
            classify_elevation_source([])

    def test_single_record_returned(self):
        rec = _record()
        assert classify_elevation_source([rec]) is rec


# ---------------------------------------------------------------------------
# build_unavailable_habitat_matrix
# ---------------------------------------------------------------------------


class TestBuildUnavailableHabitatMatrix:
    def test_all_unknown_elevation_state(self):
        records = build_unavailable_habitat_matrix(["t1", "t2"])
        assert all(r.elevation_state == ElevationState.UNKNOWN for r in records)

    def test_all_unavailable_evidence_state(self):
        records = build_unavailable_habitat_matrix(["t1"])
        assert records[0].evidence_state == HabitatEvidenceState.UNAVAILABLE

    def test_taxon_ids_preserved(self):
        records = build_unavailable_habitat_matrix(["taxon-A", "taxon-B"])
        assert [r.taxon_id for r in records] == ["taxon-A", "taxon-B"]

    def test_empty_input_returns_empty(self):
        assert build_unavailable_habitat_matrix([]) == []

    def test_elevation_fields_are_none(self):
        records = build_unavailable_habitat_matrix(["t1"])
        r = records[0]
        assert r.elevation_min_m is None
        assert r.elevation_max_m is None
        assert r.elevation_typical_m is None


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestHabitatSerialization:
    def test_schema_version_present(self):
        rec = _record()
        assert rec.to_safe_dict()["schema_version"] == SCHEMA_VERSION

    def test_serialize_as_json_roundtrip(self):
        rec = _record()
        parsed = json.loads(rec.serialize_as_json())
        assert parsed["schema_version"] == SCHEMA_VERSION
        assert parsed["taxon_id"] == "taxon-001"
        assert parsed["elevation_state"] == "MEASURED"

    def test_unavailable_stubs_serialize_correctly(self):
        stubs = build_unavailable_habitat_matrix(["taxon-001"])
        parsed = json.loads(stubs[0].serialize_as_json())
        assert parsed["evidence_state"] == "UNAVAILABLE"
        assert parsed["elevation_state"] == "UNKNOWN"
        assert parsed["elevation_min_m"] is None

    def test_sensitive_locality_clears_elevation_in_json(self):
        rec = _record(is_sensitive_locality=True)
        parsed = json.loads(rec.serialize_as_json())
        assert parsed["elevation_min_m"] is None
        assert parsed["elevation_max_m"] is None
