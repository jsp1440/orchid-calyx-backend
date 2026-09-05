from __future__ import annotations

import json

import pytest

from app.calyx_orchestrator.habitat_geospatial import (
    ElevationState,
    GeospatialGateway,
    HabitatEvidenceState,
    HabitatRecord,
    build_unavailable_habitat_matrix,
    classify_elevation_source,
    serialize_habitat_snapshot,
)


def _record(source: str, state: ElevationState, typical: int | None) -> HabitatRecord:
    return HabitatRecord(
        taxon_id="taxon:1",
        scientific_name="Phragmipedium kovachii",
        elevation_min_m=2400 if typical is not None else None,
        elevation_max_m=2700 if typical is not None else None,
        elevation_typical_m=typical,
        elevation_state=state,
        habitat_type="terrestrial",
        climate_zone="montane cloud forest",
        measurement_source=source,
        evidence_state=HabitatEvidenceState.VERIFIED if source == "reviewed_occurrence" else HabitatEvidenceState.REVIEW_REQUIRED,
    )


def test_unknown_elevation_never_collapses_to_zero() -> None:
    with pytest.raises(ValueError, match="UNKNOWN elevation cannot carry numeric values"):
        _record("estimated_external", ElevationState.UNKNOWN, 0)


def test_measured_source_outranks_derived_and_estimated() -> None:
    selected = classify_elevation_source([
        _record("estimated_external", ElevationState.ESTIMATED, 2500),
        _record("derived_model", ElevationState.DERIVED, 2550),
        _record("reviewed_occurrence", ElevationState.MEASURED, 2600),
    ])
    assert selected is not None
    assert selected.measurement_source == "reviewed_occurrence"
    assert selected.elevation_state is ElevationState.MEASURED


def test_unavailable_geospatial_layer_is_explicit_unknown() -> None:
    payload = GeospatialGateway(available=False).serialize({"elevation": 2600})
    assert payload["state"] == "UNKNOWN"
    assert payload["payload"] is None
    assert payload["reason"] == "geospatial_layer_unavailable"


def test_protected_locality_is_removed_before_serialization() -> None:
    payload = GeospatialGateway(available=True).serialize(
        {"latitude": -6.1, "longitude": -77.2, "region": "Amazonas"},
        protected=True,
    )
    assert payload == {"state": "UNKNOWN", "payload": None, "reason": "protected_locality_withheld"}


def test_nonprotected_payload_still_strips_raw_coordinates() -> None:
    payload = GeospatialGateway(available=True).serialize(
        {"region": "Amazonas", "coordinates": [-6.1, -77.2], "nested": {"gps": "secret", "summary": "regional only"}}
    )
    encoded = json.dumps(payload).casefold()
    assert payload["state"] == "AVAILABLE"
    assert '"coordinates"' not in encoded
    assert '"gps"' not in encoded
    assert "regional only" in encoded


def test_unavailable_habitat_matrix_is_all_unknown() -> None:
    payload = build_unavailable_habitat_matrix(taxon_id="taxon:missing")
    assert payload["evidence_state"] == "UNKNOWN"
    assert payload["elevation_state"] == "UNKNOWN"
    assert payload["record"] is None
    assert payload["production_mutation"] is False
    assert payload["taxonomy_activation"] is False


def test_serialized_snapshot_preserves_measured_vs_derived_state() -> None:
    measured = serialize_habitat_snapshot(
        [_record("reviewed_occurrence", ElevationState.MEASURED, 2600)],
        geospatial={"region": "Amazonas", "latitude": -6.1},
        geospatial_available=True,
    )
    derived = serialize_habitat_snapshot(
        [_record("derived_model", ElevationState.DERIVED, 2550)],
        geospatial_available=False,
    )
    assert measured["elevation_state"] == "MEASURED"
    assert derived["elevation_state"] == "DERIVED"
    assert measured["record"]["elevation"]["typical_m"] == 2600
    assert derived["record"]["elevation"]["typical_m"] == 2550
