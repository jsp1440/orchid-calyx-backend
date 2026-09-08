"""Governed conservation-status contract with protected-locality enforcement.

This module is deliberately provider-free and read-only. It models reviewed
conservation evidence without connecting to a live authority or exposing
coordinates, collection identifiers, or private locality metadata.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any


class ConservationAuthority(str, Enum):
    IUCN = "iucn"
    NATIONAL = "national"
    REGIONAL = "regional"


class ConservationEvidenceState(str, Enum):
    PRESENT = "present"
    UNKNOWN = "unknown"
    WITHHELD = "withheld"
    CONTRADICTORY = "contradictory"
    UNAVAILABLE = "unavailable"


class ConservationReviewState(str, Enum):
    REVIEWED = "reviewed"
    PROVISIONAL = "provisional"
    UNREVIEWED = "unreviewed"


class LocalityDisclosureState(str, Enum):
    GENERALIZED = "generalized"
    WITHHELD = "withheld"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ConservationRecord:
    canonical_taxon_id: str
    authority: ConservationAuthority
    status_code: str | None
    assessment_date: date | None
    source_version: str | None
    evidence_state: ConservationEvidenceState
    review_state: ConservationReviewState

    def __post_init__(self) -> None:
        taxon_id = self.canonical_taxon_id.strip()
        if not taxon_id:
            raise ValueError("canonical_taxon_id must not be empty")
        object.__setattr__(self, "canonical_taxon_id", taxon_id)

        if self.evidence_state is ConservationEvidenceState.PRESENT:
            for field_name in ("status_code", "assessment_date", "source_version"):
                if getattr(self, field_name) in (None, ""):
                    raise ValueError(
                        f"present conservation evidence requires {field_name}"
                    )
        elif any(
            value is not None
            for value in (
                self.status_code,
                self.assessment_date,
                self.source_version,
            )
        ):
            raise ValueError(
                "non-present conservation evidence cannot carry assessment claims"
            )

        if self.status_code is not None:
            status_code = self.status_code.strip().upper()
            if not status_code:
                raise ValueError("status_code must not be empty")
            object.__setattr__(self, "status_code", status_code)
        if self.source_version is not None:
            source_version = self.source_version.strip()
            if not source_version:
                raise ValueError("source_version must not be empty")
            object.__setattr__(self, "source_version", source_version)

    def to_dict(self) -> dict[str, Any]:
        return {
            "canonical_taxon_id": self.canonical_taxon_id,
            "authority": self.authority.value,
            "status_code": self.status_code,
            "assessment_date": (
                self.assessment_date.isoformat()
                if self.assessment_date is not None
                else None
            ),
            "source_version": self.source_version,
            "evidence_state": self.evidence_state.value,
            "review_state": self.review_state.value,
        }


class ConservationStatusPrecedence:
    """Choose one record deterministically without promoting unknown evidence."""

    _review_rank = {
        ConservationReviewState.REVIEWED: 0,
        ConservationReviewState.PROVISIONAL: 1,
        ConservationReviewState.UNREVIEWED: 2,
    }
    _authority_rank = {
        ConservationAuthority.IUCN: 0,
        ConservationAuthority.NATIONAL: 1,
        ConservationAuthority.REGIONAL: 2,
    }

    @classmethod
    def select(
        cls,
        records: Iterable[ConservationRecord],
    ) -> ConservationRecord | None:
        eligible = [
            record
            for record in records
            if record.evidence_state is ConservationEvidenceState.PRESENT
        ]
        if not eligible:
            return None
        return min(
            eligible,
            key=lambda record: (
                cls._review_rank[record.review_state],
                cls._authority_rank[record.authority],
                -(record.assessment_date or date.min).toordinal(),
                record.canonical_taxon_id.casefold(),
                (record.source_version or "").casefold(),
            ),
        )


class LocalityProtectionGateway:
    """Project locality policy to a disclosure state, never to coordinates."""

    @staticmethod
    def classify(
        *,
        source_available: bool,
        is_protected: bool,
        is_private: bool,
    ) -> LocalityDisclosureState:
        if not source_available:
            return LocalityDisclosureState.UNAVAILABLE
        if is_protected or is_private:
            return LocalityDisclosureState.WITHHELD
        return LocalityDisclosureState.GENERALIZED


@dataclass(frozen=True, slots=True)
class ConservationMatrix:
    canonical_taxon_id: str
    records: tuple[ConservationRecord, ...]
    locality_state: LocalityDisclosureState

    def __post_init__(self) -> None:
        taxon_id = self.canonical_taxon_id.strip()
        if not taxon_id:
            raise ValueError("canonical_taxon_id must not be empty")
        object.__setattr__(self, "canonical_taxon_id", taxon_id)
        if any(record.canonical_taxon_id != taxon_id for record in self.records):
            raise ValueError("all conservation records must bind to the matrix taxon")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "conservation-matrix-v1",
            "canonical_taxon_id": self.canonical_taxon_id,
            "records": [record.to_dict() for record in self.records],
            "locality_state": self.locality_state.value,
            "taxonomy_activation_authorized": False,
            "publication_authorized": False,
        }


def build_unavailable_conservation_matrix(
    canonical_taxon_id: str,
) -> ConservationMatrix:
    records = tuple(
        ConservationRecord(
            canonical_taxon_id=canonical_taxon_id,
            authority=authority,
            status_code=None,
            assessment_date=None,
            source_version=None,
            evidence_state=ConservationEvidenceState.UNKNOWN,
            review_state=ConservationReviewState.UNREVIEWED,
        )
        for authority in ConservationAuthority
    )
    return ConservationMatrix(
        canonical_taxon_id=canonical_taxon_id,
        records=records,
        locality_state=LocalityDisclosureState.UNAVAILABLE,
    )
