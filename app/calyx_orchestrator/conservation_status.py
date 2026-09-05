from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

SCHEMA_VERSION = "oc.conservation-status.v1"
_SOURCE_PRECEDENCE = {
    "authoritative_reviewed": 0,
    "authoritative_unreviewed": 1,
    "external_import": 2,
}
_SENSITIVE_KEYS = {
    "latitude",
    "longitude",
    "lat",
    "lon",
    "lng",
    "coordinates",
    "exact_coordinates",
    "exact_location",
    "private_locality",
    "locality",
    "site",
    "grid_reference",
    "gps",
    "collector",
    "catalogue_number",
    "catalog_number",
    "collection_id",
    "specimen_id",
}


class ConservationEvidenceState(str, Enum):
    VERIFIED = "VERIFIED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    UNKNOWN = "UNKNOWN"


class LocalityState(str, Enum):
    AVAILABLE = "AVAILABLE"
    WITHHELD = "WITHHELD"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ConservationRecord:
    taxon_id: str
    scientific_name: str
    status_authority: str
    status_code: str | None
    assessment_date: str | None
    source_version: str | None
    source_class: str
    evidence_state: ConservationEvidenceState

    def __post_init__(self) -> None:
        if self.status_authority not in {"IUCN", "national", "regional"}:
            raise ValueError("status_authority must be IUCN, national, or regional")
        if self.source_class not in _SOURCE_PRECEDENCE:
            raise ValueError(f"unsupported source_class: {self.source_class}")
        if not self.taxon_id or not self.scientific_name:
            raise ValueError("taxon binding is required")
        if self.evidence_state is ConservationEvidenceState.UNKNOWN and self.status_code is not None:
            raise ValueError("UNKNOWN conservation evidence cannot silently carry a status")
        if self.source_class == "authoritative_reviewed" and self.evidence_state is not ConservationEvidenceState.VERIFIED:
            raise ValueError("authoritative_reviewed assessments must be VERIFIED")

    @property
    def precedence(self) -> int:
        return _SOURCE_PRECEDENCE[self.source_class]

    def to_dict(self) -> dict[str, Any]:
        return {
            "taxon_binding": {
                "taxon_id": self.taxon_id,
                "scientific_name": self.scientific_name,
            },
            "status_authority": self.status_authority,
            "status_code": self.status_code,
            "assessment_date": self.assessment_date,
            "source_version": self.source_version,
            "source_class": self.source_class,
            "evidence_state": self.evidence_state.value,
        }


def choose_conservation_record(records: Iterable[ConservationRecord]) -> ConservationRecord | None:
    ordered = sorted(
        records,
        key=lambda item: (
            item.precedence,
            item.status_authority,
            item.assessment_date or "",
            item.source_version or "",
        ),
    )
    return ordered[0] if ordered else None


def _safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _safe(item)
            for key, item in value.items()
            if str(key).casefold() not in _SENSITIVE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_safe(item) for item in value]
    return value


@dataclass(frozen=True)
class LocalityProtectionGateway:
    def serialize_locality(
        self,
        locality: dict[str, Any] | None,
        *,
        protected: bool = False,
        private: bool = False,
    ) -> dict[str, Any]:
        if protected or private:
            return {"state": LocalityState.WITHHELD.value, "locality": None}
        if locality is None:
            return {"state": LocalityState.UNKNOWN.value, "locality": None}
        safe_locality = _safe(locality)
        return {
            "state": LocalityState.AVAILABLE.value if safe_locality else LocalityState.UNKNOWN.value,
            "locality": safe_locality or None,
        }


def build_unavailable_conservation_matrix(*, taxon_id: str | None = None) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "taxon_id": taxon_id,
        "state": ConservationEvidenceState.UNKNOWN.value,
        "record": None,
        "locality": {"state": LocalityState.UNKNOWN.value, "locality": None},
        "reason": "conservation_source_unavailable",
        "production_mutation": False,
        "taxonomy_activation": False,
    }


def serialize_conservation_snapshot(
    records: Iterable[ConservationRecord],
    *,
    locality: dict[str, Any] | None = None,
    protected_locality: bool = False,
    private_locality: bool = False,
) -> dict[str, Any]:
    selected = choose_conservation_record(records)
    locality_payload = LocalityProtectionGateway().serialize_locality(
        locality,
        protected=protected_locality,
        private=private_locality,
    )
    if selected is None:
        return {
            **build_unavailable_conservation_matrix(),
            "reason": "no_reviewable_conservation_record",
            "locality": locality_payload,
        }

    return {
        "schema_version": SCHEMA_VERSION,
        "taxon_id": selected.taxon_id,
        "state": selected.evidence_state.value,
        "record": selected.to_dict(),
        "locality": locality_payload,
        "production_mutation": False,
        "taxonomy_activation": False,
    }
