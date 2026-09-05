from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

SCHEMA_VERSION = "oc.habitat-geospatial.v1"
_SOURCE_PRECEDENCE = {"reviewed_occurrence": 0, "derived_model": 1, "estimated_external": 2}
_SENSITIVE_KEYS = {"latitude", "longitude", "lat", "lon", "lng", "coordinates", "gps", "exact_location", "private_locality", "locality", "site", "grid_reference"}


class ElevationState(str, Enum):
    MEASURED = "MEASURED"
    DERIVED = "DERIVED"
    ESTIMATED = "ESTIMATED"
    UNKNOWN = "UNKNOWN"


class HabitatEvidenceState(str, Enum):
    VERIFIED = "VERIFIED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class HabitatRecord:
    taxon_id: str
    scientific_name: str
    elevation_min_m: int | None
    elevation_max_m: int | None
    elevation_typical_m: int | None
    elevation_state: ElevationState
    habitat_type: str | None
    climate_zone: str | None
    measurement_source: str
    evidence_state: HabitatEvidenceState

    def __post_init__(self) -> None:
        if self.measurement_source not in _SOURCE_PRECEDENCE:
            raise ValueError(f"unsupported measurement_source: {self.measurement_source}")
        if not self.taxon_id or not self.scientific_name:
            raise ValueError("taxon binding is required")
        values = (self.elevation_min_m, self.elevation_max_m, self.elevation_typical_m)
        if self.elevation_state is ElevationState.UNKNOWN and any(value is not None for value in values):
            raise ValueError("UNKNOWN elevation cannot carry numeric values")
        if self.elevation_state is not ElevationState.UNKNOWN and all(value is None for value in values):
            raise ValueError("known elevation state requires at least one value")

    @property
    def precedence(self) -> int:
        return _SOURCE_PRECEDENCE[self.measurement_source]

    def to_dict(self) -> dict[str, Any]:
        return {
            "taxon_binding": {"taxon_id": self.taxon_id, "scientific_name": self.scientific_name},
            "elevation": {
                "min_m": self.elevation_min_m,
                "max_m": self.elevation_max_m,
                "typical_m": self.elevation_typical_m,
                "state": self.elevation_state.value,
            },
            "habitat_type": self.habitat_type,
            "climate_zone": self.climate_zone,
            "measurement_source": self.measurement_source,
            "evidence_state": self.evidence_state.value,
        }


def classify_elevation_source(records: Iterable[HabitatRecord]) -> HabitatRecord | None:
    ordered = sorted(records, key=lambda item: (item.precedence, item.taxon_id, item.scientific_name))
    return ordered[0] if ordered else None


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items() if str(k).casefold() not in _SENSITIVE_KEYS}
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    return value


@dataclass(frozen=True)
class GeospatialGateway:
    available: bool

    def serialize(self, payload: dict[str, Any] | None, *, protected: bool = False) -> dict[str, Any]:
        if not self.available:
            return {"state": ElevationState.UNKNOWN.value, "payload": None, "reason": "geospatial_layer_unavailable"}
        if protected:
            return {"state": ElevationState.UNKNOWN.value, "payload": None, "reason": "protected_locality_withheld"}
        safe_payload = _safe(payload or {})
        return {"state": "AVAILABLE" if safe_payload else ElevationState.UNKNOWN.value, "payload": safe_payload or None}


def build_unavailable_habitat_matrix(*, taxon_id: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "taxon_id": taxon_id,
        "evidence_state": HabitatEvidenceState.UNKNOWN.value,
        "elevation_state": ElevationState.UNKNOWN.value,
        "record": None,
        "geospatial": {"state": ElevationState.UNKNOWN.value, "payload": None},
        "production_mutation": False,
        "taxonomy_activation": False,
    }


def serialize_habitat_snapshot(records: Iterable[HabitatRecord], *, geospatial: dict[str, Any] | None = None, geospatial_available: bool = False, protected_locality: bool = False) -> dict[str, Any]:
    selected = classify_elevation_source(records)
    if selected is None:
        result = build_unavailable_habitat_matrix()
    else:
        result = {
            "schema_version": SCHEMA_VERSION,
            "taxon_id": selected.taxon_id,
            "evidence_state": selected.evidence_state.value,
            "elevation_state": selected.elevation_state.value,
            "record": selected.to_dict(),
            "production_mutation": False,
            "taxonomy_activation": False,
        }
    result["geospatial"] = GeospatialGateway(available=geospatial_available).serialize(geospatial, protected=protected_locality)
    return result
