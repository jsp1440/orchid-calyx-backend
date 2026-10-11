"""Server-side Atlas locality-safety policy.

This is a deliberate port of the canonical frontend rule in
``orchid-continuum-frontend/src/lib/atlasLocalitySafety.ts`` so that the API
never relies on a browser to protect a sensitive site. The two implementations
share the parity vectors in ``contracts/atlas_locality_policy_vectors_v1.json``;
a change to either side must keep those vectors passing.

Rules (fail closed):

* Threatened taxa (IUCN CR/EN/VU, or an equivalent free-text status) are
  snapped to a 1° / 0.5° / 0.25° grid-cell centre for public callers.
* A stated coordinate uncertainty is never drawn more precisely than stated.
* A record whose conservation assessment could not be resolved receives a
  precautionary 0.05° floor for public callers. That is not a threat claim.
* Coordinates are never jittered: a snapped point is the centre of the cell,
  so the display communicates an area instead of inventing a false site.
* Free-text locality is withheld whenever a threat or precaution cell applies.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

AccessLevel = Literal["public", "research"]
SensitivityReason = Literal[
    "iucn-threatened",
    "conservation-status",
    "coordinate-uncertainty",
    "unresolved-assessment",
    "none",
]

UNRESOLVED_FLOOR_DEG = 0.05
THREATENED_CODES = frozenset({"CR", "EN", "VU"})
TIER_CELL_DEG: dict[str, float] = {"CR": 1.0, "EN": 0.5, "VU": 0.25}
METRES_PER_DEGREE = 111_320


@dataclass(frozen=True)
class LocalityPolicy:
    generalised: bool
    cell_deg: float
    reason: SensitivityReason
    locality_text_allowed: bool
    notice: str


@dataclass(frozen=True)
class DisplayedLocation:
    lat: float
    lng: float
    policy: LocalityPolicy


def threat_tier(iucn_code: str | None, conservation_status: str | None) -> str | None:
    code = (iucn_code or "").strip().upper()
    if code in THREATENED_CODES:
        return code
    status = (conservation_status or "").strip().lower()
    if not status:
        return None
    if "critically endangered" in status:
        return "CR"
    if "endangered" in status:
        return "EN"
    if "vulnerable" in status:
        return "VU"
    return None


def uncertainty_to_cell_deg(uncertainty_m: float | None) -> float:
    if uncertainty_m is None or not math.isfinite(uncertainty_m) or uncertainty_m <= 0:
        return 0.0
    deg = uncertainty_m / METRES_PER_DEGREE
    if deg <= 0.02:
        return 0.0
    if deg <= 0.1:
        return 0.1
    if deg <= 0.25:
        return 0.25
    if deg <= 0.5:
        return 0.5
    return 1.0


def snap_to_cell(lat: float, lng: float, cell_deg: float) -> tuple[float, float]:
    if cell_deg <= 0:
        return lat, lng

    def snap(value: float) -> float:
        return (math.floor(value / cell_deg) + 0.5) * cell_deg

    snapped_lat = max(-90.0, min(90.0, snap(lat)))
    snapped_lng = ((snap(lng) + 180) % 360 + 360) % 360 - 180
    return snapped_lat, snapped_lng


def _js_round(value: float) -> int:
    """Math.round semantics (half rounds up), so notices match the frontend text."""
    return math.floor(value + 0.5)


def _km(deg: float) -> int:
    return _js_round(deg * 111)


def resolve_location(
    *,
    lat: float,
    lng: float,
    iucn_code: str | None = None,
    conservation_status: str | None = None,
    coordinate_uncertainty_m: float | None = None,
    assessment_resolved: bool | None = None,
    access: AccessLevel = "public",
    floor_cell_deg: float = 0.0,
) -> DisplayedLocation:
    tier = threat_tier(iucn_code, conservation_status)
    uncertainty_cell = uncertainty_to_cell_deg(coordinate_uncertainty_m)
    unresolved = assessment_resolved is False and tier is None
    precaution_cell = (
        UNRESOLVED_FLOOR_DEG if unresolved and access != "research" else 0.0
    )
    threat_cell = TIER_CELL_DEG[tier] if tier and access != "research" else 0.0

    cell_deg = max(threat_cell, uncertainty_cell, precaution_cell, floor_cell_deg)
    shown_lat, shown_lng = snap_to_cell(lat, lng, cell_deg)

    reason: SensitivityReason = "none"
    notice = ""
    if (
        threat_cell > 0
        and threat_cell >= uncertainty_cell
        and threat_cell >= precaution_cell
    ):
        reason = "iucn-threatened" if iucn_code else "conservation-status"
        notice = (
            f"Location generalised to about {_km(threat_cell)} km because this taxon is "
            f"assessed as threatened ({tier}); precise sites are withheld to reduce collection risk."
        )
    elif uncertainty_cell > 0 and uncertainty_cell >= precaution_cell:
        reason = "coordinate-uncertainty"
        notice = (
            f"Shown as an area of about {_km(uncertainty_cell)} km because the source record "
            f"states {_js_round(coordinate_uncertainty_m or 0)} m coordinate uncertainty."
        )
    elif precaution_cell > 0:
        reason = "unresolved-assessment"
        notice = (
            f"Location generalised to about {_km(precaution_cell)} km because the Continuum could "
            "not resolve a conservation assessment for this name. This precaution is not a claim "
            "that the taxon is threatened."
        )

    return DisplayedLocation(
        lat=shown_lat,
        lng=shown_lng,
        policy=LocalityPolicy(
            generalised=cell_deg > 0,
            cell_deg=cell_deg,
            reason=reason,
            locality_text_allowed=threat_cell == 0 and precaution_cell == 0,
            notice=notice,
        ),
    )
