"""OC-CONSERVATION-001 — Conservation status integration with protected-locality enforcement.

Canonical conservation-status module that binds IUCN/national status records to
reviewed taxonomy, enforces protected-locality rules, and never leaks sensitive
coordinates or private collection data.

Key invariants:
- WITHHELD is returned for any protected or private coordinate — never exact locality.
- UNKNOWN is the correct representation of missing status; it is never silently promoted.
- Authoritative reviewed assessments outrank unreviewed imports.
- No live IUCN API call; the gateway uses an explicit unavailable stub that callers
  must replace with a real source once a reviewed data feed is established.
- Serialization strips all private coordinate fields before any payload crosses a boundary.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.calyx_flywheel.locality import assert_no_sensitive_locality

SCHEMA_VERSION = "oc-conservation-status/v1"


class StatusAuthority(str, Enum):
    IUCN = "IUCN"
    NATIONAL = "national"
    REGIONAL = "regional"
    UNKNOWN_AUTHORITY = "UNKNOWN_AUTHORITY"


class EvidenceState(str, Enum):
    REVIEWED = "REVIEWED"
    UNREVIEWED_IMPORT = "UNREVIEWED_IMPORT"
    UNAVAILABLE = "UNAVAILABLE"


class StatusCode(str, Enum):
    EX = "EX"          # Extinct
    EW = "EW"          # Extinct in the Wild
    CR = "CR"          # Critically Endangered
    EN = "EN"          # Endangered
    VU = "VU"          # Vulnerable
    NT = "NT"          # Near Threatened
    LC = "LC"          # Least Concern
    DD = "DD"          # Data Deficient
    NE = "NE"          # Not Evaluated
    UNKNOWN = "UNKNOWN"


_REVIEWED_PRECEDENCE = {
    EvidenceState.REVIEWED: 2,
    EvidenceState.UNREVIEWED_IMPORT: 1,
    EvidenceState.UNAVAILABLE: 0,
}


@dataclass(frozen=True)
class ConservationRecord:
    """Immutable conservation status record bound to a reviewed taxon."""

    taxon_id: str
    taxon_name: str
    status_code: StatusCode
    authority: StatusAuthority
    assessment_date: str           # ISO-8601 date or "" when unknown
    source_version: str            # e.g. "IUCN Red List v2023-1" or "unavailable"
    evidence_state: EvidenceState
    notes: str = ""

    def validate(self) -> None:
        if not self.taxon_id:
            raise ValueError("CONSERVATION_RECORD_INVALID: taxon_id must not be empty")
        if self.status_code == StatusCode.UNKNOWN and self.evidence_state == EvidenceState.REVIEWED:
            raise ValueError(
                "CONSERVATION_RECORD_INVALID: REVIEWED evidence_state requires a known StatusCode"
            )

    def to_safe_dict(self) -> dict[str, Any]:
        """Serialize to a dict guaranteed to contain no sensitive locality fields."""
        d = {
            "schema_version": SCHEMA_VERSION,
            "taxon_id": self.taxon_id,
            "taxon_name": self.taxon_name,
            "status_code": self.status_code.value,
            "authority": self.authority.value,
            "assessment_date": self.assessment_date,
            "source_version": self.source_version,
            "evidence_state": self.evidence_state.value,
            "notes": self.notes,
        }
        assert_no_sensitive_locality(d)
        return d

    def serialize_as_json(self) -> str:
        return json.dumps(self.to_safe_dict(), sort_keys=True)


_WITHHELD_SENTINEL = "WITHHELD"


class LocalityProtectionGateway:
    """Enforces protected-locality rules for conservation records.

    Returns WITHHELD for any protected or private coordinate. Never exposes
    exact locality when the source record marks it private.

    This class is deliberately stateless; callers inject the protection flag
    rather than storing raw coordinates anywhere in this module.
    """

    def get_locality(self, *, is_protected: bool, is_private: bool) -> str:
        """Return a locality token suitable for external consumption.

        Args:
            is_protected: True if the source record marks the occurrence as
                          protected (e.g. sensitive species, restricted site).
            is_private:   True if the collection event is private / not for
                          public release.

        Returns:
            "WITHHELD" when either flag is set, else "AVAILABLE".
            Callers must not interpret "AVAILABLE" as license to expose raw
            coordinates — they must still consult the source record's own
            release permissions.
        """
        if is_protected or is_private:
            return _WITHHELD_SENTINEL
        return "AVAILABLE"

    def assert_no_coordinate_leak(self, payload: Any) -> None:
        """Raise SensitiveLocalityError if payload contains protected locality fields."""
        assert_no_sensitive_locality(payload)


class ConservationStatusPrecedence:
    """Arbitrates between competing conservation records for the same taxon.

    Rule: REVIEWED > UNREVIEWED_IMPORT > UNAVAILABLE.
    UNKNOWN status is never silently promoted; it remains UNKNOWN until a
    reviewed assessment replaces it.
    """

    def resolve(self, records: list[ConservationRecord]) -> ConservationRecord:
        """Return the authoritative record from a list of competing records.

        Raises:
            ValueError: if records is empty.
        """
        if not records:
            raise ValueError("CONSERVATION_PRECEDENCE_EMPTY: at least one record required")
        return max(records, key=lambda r: _REVIEWED_PRECEDENCE.get(r.evidence_state, 0))

    def is_authoritative(self, record: ConservationRecord) -> bool:
        return record.evidence_state == EvidenceState.REVIEWED


_UNAVAILABLE_SOURCE = "NO_DB_CONNECTION"


def build_unavailable_conservation_matrix(taxon_ids: list[str]) -> list[ConservationRecord]:
    """Return all-UNKNOWN records when the conservation DB is absent.

    No status is fabricated. Each returned record carries EvidenceState.UNAVAILABLE
    so callers can distinguish "no data available" from a genuine assessment.

    Args:
        taxon_ids: List of taxon IDs to build unavailable stubs for. May be empty.

    Returns:
        A list of ConservationRecord with status_code=UNKNOWN and
        evidence_state=UNAVAILABLE for every requested taxon_id.
    """
    return [
        ConservationRecord(
            taxon_id=tid,
            taxon_name="",
            status_code=StatusCode.UNKNOWN,
            authority=StatusAuthority.UNKNOWN_AUTHORITY,
            assessment_date="",
            source_version=_UNAVAILABLE_SOURCE,
            evidence_state=EvidenceState.UNAVAILABLE,
        )
        for tid in taxon_ids
    ]
