"""OC-HABITAT-001 — Habitat, elevation, and geospatial reconciliation pipeline.

Governed habitat/elevation/climate schema that reconciles occurrence-derived
measurements with authoritative elevation models, preserves measured vs. derived
distinctions, and enforces locality protection throughout.

Key invariants:
- ElevationState is MEASURED/DERIVED/ESTIMATED/UNKNOWN; never fabricated zero.
- Protected coordinates are cleared before serialization; raw coordinates never
  cross a serialization boundary for sensitive localities.
- UNKNOWN is the correct sentinel when data is absent; no fabricated value substituted.
- Reviewed occurrence-derived measurements outrank modeled/derived values.
- No live GIS API required; GeospatialGateway uses an explicit unavailable stub.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.calyx_flywheel.locality import assert_no_sensitive_locality

SCHEMA_VERSION = "oc-habitat-elevation/v1"

_UNKNOWN_FLOAT = None  # typed as float | None; None = UNKNOWN, never zero


class ElevationState(str, Enum):
    MEASURED = "MEASURED"        # from reviewed occurrence data
    DERIVED = "DERIVED"          # inferred from authoritative elevation model
    ESTIMATED = "ESTIMATED"      # rough estimate from range literature
    UNKNOWN = "UNKNOWN"          # no data; never silently promoted


class HabitatType(str, Enum):
    FOREST = "forest"
    EPIPHYTE = "epiphyte"
    LITHOPHYTE = "lithophyte"
    TERRESTRIAL = "terrestrial"
    UNKNOWN_HABITAT = "UNKNOWN_HABITAT"


class ClimateZone(str, Enum):
    TROPICAL = "tropical"
    SUBTROPICAL = "subtropical"
    TEMPERATE = "temperate"
    MONTANE = "montane"
    UNKNOWN_CLIMATE = "UNKNOWN_CLIMATE"


class HabitatEvidenceState(str, Enum):
    REVIEWED_OCCURRENCE = "reviewed_occurrence"
    MODELED = "modeled"
    ESTIMATED = "estimated"
    UNAVAILABLE = "UNAVAILABLE"


_MEASUREMENT_PRECEDENCE = {
    HabitatEvidenceState.REVIEWED_OCCURRENCE: 3,
    HabitatEvidenceState.MODELED: 2,
    HabitatEvidenceState.ESTIMATED: 1,
    HabitatEvidenceState.UNAVAILABLE: 0,
}


@dataclass(frozen=True)
class HabitatRecord:
    """Immutable habitat record with elevation range, type, and climate binding."""

    taxon_id: str
    taxon_name: str
    habitat_type: HabitatType
    climate_zone: ClimateZone
    elevation_min_m: float | None      # None = UNKNOWN
    elevation_max_m: float | None      # None = UNKNOWN
    elevation_typical_m: float | None  # None = UNKNOWN
    elevation_state: ElevationState
    measurement_source: str
    evidence_state: HabitatEvidenceState
    provenance_chain: tuple[str, ...]
    # is_sensitive_locality must be True to trigger coordinate withholding at serialize time
    is_sensitive_locality: bool = False

    def validate(self) -> None:
        if not self.taxon_id:
            raise ValueError("HABITAT_RECORD_INVALID: taxon_id must not be empty")
        if (
            self.elevation_state != ElevationState.UNKNOWN
            and self.elevation_min_m is None
            and self.elevation_max_m is None
            and self.elevation_typical_m is None
        ):
            raise ValueError(
                "HABITAT_RECORD_INVALID: elevation_state is not UNKNOWN but all elevation "
                "fields are None — use ElevationState.UNKNOWN when no data is available"
            )

    def to_safe_dict(self) -> dict[str, Any]:
        """Serialize to a dict; clears elevation fields for sensitive localities."""
        elev_min = None if self.is_sensitive_locality else self.elevation_min_m
        elev_max = None if self.is_sensitive_locality else self.elevation_max_m
        elev_typical = None if self.is_sensitive_locality else self.elevation_typical_m

        d = {
            "schema_version": SCHEMA_VERSION,
            "taxon_id": self.taxon_id,
            "taxon_name": self.taxon_name,
            "habitat_type": self.habitat_type.value,
            "climate_zone": self.climate_zone.value,
            "elevation_min_m": elev_min,
            "elevation_max_m": elev_max,
            "elevation_typical_m": elev_typical,
            "elevation_state": self.elevation_state.value,
            "measurement_source": self.measurement_source,
            "evidence_state": self.evidence_state.value,
            "provenance_chain": list(self.provenance_chain),
        }
        # Belt-and-braces: confirm no sensitive locality field leaked in
        assert_no_sensitive_locality(d)
        return d

    def serialize_as_json(self) -> str:
        return json.dumps(self.to_safe_dict(), sort_keys=True)


class GeospatialGateway:
    """Read-through gateway for geospatial data.

    Returns UNKNOWN when the geospatial layer is unavailable. Never fabricates
    presence, coordinates, or elevation values.
    """

    def __init__(self, *, available: bool = False) -> None:
        self._available = available

    def get_elevation_m(self, lat: float, lon: float) -> float | None:
        """Return elevation in metres, or None (UNKNOWN) when unavailable.

        Args:
            lat: Latitude (used only when gateway is actually connected).
            lon: Longitude (used only when gateway is actually connected).

        Returns:
            None in stub/unavailable mode — never a fabricated number.
        """
        if not self._available:
            return None
        raise NotImplementedError(
            "GEOSPATIAL_GATEWAY_NOT_IMPLEMENTED: real GIS connectivity not available "
            "in this slice; use stub (available=False) or connect a real GIS adapter"
        )

    def is_available(self) -> bool:
        return self._available


def classify_elevation_source(
    records: list[HabitatRecord],
) -> HabitatRecord:
    """Return the record with the highest-precedence elevation source.

    Precedence: reviewed_occurrence > modeled > estimated > unavailable.

    Raises:
        ValueError: if records is empty.
    """
    if not records:
        raise ValueError("HABITAT_CLASSIFY_EMPTY: at least one record required")
    return max(records, key=lambda r: _MEASUREMENT_PRECEDENCE.get(r.evidence_state, 0))


def build_unavailable_habitat_matrix(taxon_ids: list[str]) -> list[HabitatRecord]:
    """Return all-UNKNOWN habitat stubs when the DB is absent.

    No status is fabricated. All elevation fields are None (UNKNOWN) and
    evidence_state=UNAVAILABLE.

    Args:
        taxon_ids: Taxon IDs to build unavailable stubs for.

    Returns:
        A list of HabitatRecord with elevation_state=UNKNOWN and
        evidence_state=UNAVAILABLE for every requested taxon_id.
    """
    return [
        HabitatRecord(
            taxon_id=tid,
            taxon_name="",
            habitat_type=HabitatType.UNKNOWN_HABITAT,
            climate_zone=ClimateZone.UNKNOWN_CLIMATE,
            elevation_min_m=None,
            elevation_max_m=None,
            elevation_typical_m=None,
            elevation_state=ElevationState.UNKNOWN,
            measurement_source="NO_DB_CONNECTION",
            evidence_state=HabitatEvidenceState.UNAVAILABLE,
            provenance_chain=("NO_DB_CONNECTION",),
        )
        for tid in taxon_ids
    ]
