"""OC-VISION-001 — Vision/image intelligence pipeline schema, license attribution, and identification contract.

Governed image/vision pipeline schema with canonical license attribution, image-source
classification, broken-image detection, and identification-candidate contract.

Key invariants:
- automatic_publication=False enforced on ImageIdentificationCandidate at construction.
- RESTRICTED license is never silently promoted to a usable license.
- UNKNOWN/UNAVAILABLE is returned when image DB is absent; no counts fabricated.
- Curator-reviewed canonical bindings outrank automated suggestions.
- No restricted collection locality coordinates appear in serialized output.
- No production DB mutation, no taxonomy activation, no automated identification publication.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

SCHEMA_VERSION = "oc-vision-image-pipeline/v1"


class ImageType(str, Enum):
    HERBARIUM = "HERBARIUM"
    FIELD = "FIELD"
    COLLECTION = "COLLECTION"
    ILLUSTRATION = "ILLUSTRATION"
    UNKNOWN_TYPE = "UNKNOWN_TYPE"


class LicenseState(str, Enum):
    CC0 = "CC0"
    CC_BY = "CC_BY"
    CC_BY_SA = "CC_BY_SA"
    CC_BY_NC = "CC_BY_NC"
    RESTRICTED = "RESTRICTED"
    UNKNOWN = "UNKNOWN"


_USABLE_LICENSES: frozenset[LicenseState] = frozenset({
    LicenseState.CC0,
    LicenseState.CC_BY,
    LicenseState.CC_BY_SA,
    LicenseState.CC_BY_NC,
})


class ImageEvidenceState(str, Enum):
    CURATOR_REVIEWED = "CURATOR_REVIEWED"
    AUTOMATED_SUGGESTION = "AUTOMATED_SUGGESTION"
    UNVERIFIED = "UNVERIFIED"
    UNAVAILABLE = "UNAVAILABLE"


class IdentificationStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    REVIEWED_ACCEPTED = "REVIEWED_ACCEPTED"
    REVIEWED_REJECTED = "REVIEWED_REJECTED"
    PENDING = "PENDING"


_IMAGE_SOURCE_PRECEDENCE = {
    ImageEvidenceState.CURATOR_REVIEWED: 3,
    ImageEvidenceState.UNVERIFIED: 2,
    ImageEvidenceState.AUTOMATED_SUGGESTION: 1,
    ImageEvidenceState.UNAVAILABLE: 0,
}

_IMAGE_COUNT_UNKNOWN = None  # None = UNKNOWN, never a fabricated count


@dataclass(frozen=True)
class ImageRecord:
    """Immutable image catalog record with type, license, attribution, and evidence state."""

    image_id: str
    taxon_id: str
    taxon_name: str
    image_type: ImageType
    license_state: LicenseState
    attribution: str
    source_authority: str
    evidence_state: ImageEvidenceState
    is_broken: bool = False       # True when image URL returns error / content unavailable
    is_sensitive_locality: bool = False

    def validate(self) -> None:
        if not self.image_id:
            raise ValueError("IMAGE_RECORD_INVALID: image_id must not be empty")
        if not self.taxon_id:
            raise ValueError("IMAGE_RECORD_INVALID: taxon_id must not be empty")
        if (
            self.license_state not in (_USABLE_LICENSES | {LicenseState.UNKNOWN})
            and self.license_state != LicenseState.RESTRICTED
        ):
            raise ValueError(f"IMAGE_RECORD_INVALID: unrecognized license_state {self.license_state!r}")

    def is_usable(self) -> bool:
        """Return True only if the license is known-usable and image is not broken."""
        return self.license_state in _USABLE_LICENSES and not self.is_broken

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "image_id": self.image_id,
            "taxon_id": self.taxon_id,
            "taxon_name": self.taxon_name,
            "image_type": self.image_type.value,
            "license_state": self.license_state.value,
            "attribution": self.attribution,
            "source_authority": self.source_authority,
            "evidence_state": self.evidence_state.value,
            "is_broken": self.is_broken,
        }

    def serialize_as_json(self) -> str:
        return json.dumps(self.to_safe_dict(), sort_keys=True)


@dataclass
class ImageIdentificationCandidate:
    """Identification candidate produced by a vision model or curator.

    Enforces automatic_publication=False at construction. Identification
    results are never published autonomously; a human-review step is always
    required to move from CANDIDATE to REVIEWED_ACCEPTED.
    """

    candidate_taxon_id: str
    candidate_taxon_name: str
    confidence: float
    model_identifier: str
    status: IdentificationStatus = IdentificationStatus.CANDIDATE
    automatic_publication: bool = False

    def __post_init__(self) -> None:
        if self.automatic_publication:
            raise ValueError(
                "VISION_PIPELINE_GOVERNANCE_VIOLATION: automatic_publication must be False; "
                "no autonomous identification publication is permitted"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"IMAGE_CANDIDATE_INVALID: confidence must be in [0.0, 1.0], got {self.confidence}"
            )

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "candidate_taxon_id": self.candidate_taxon_id,
            "candidate_taxon_name": self.candidate_taxon_name,
            "confidence": self.confidence,
            "model_identifier": self.model_identifier,
            "status": self.status.value,
            "automatic_publication": self.automatic_publication,
        }

    def serialize_as_json(self) -> str:
        return json.dumps(self.to_safe_dict(), sort_keys=True)


class ImageGateway:
    """Read-through gateway for image data.

    Returns UNKNOWN/UNAVAILABLE when the image DB is absent. Never fabricates
    image counts or records.
    """

    def __init__(self, *, available: bool = False) -> None:
        self._available = available

    def get_image_count(self, taxon_id: str) -> int | None:
        """Return image count, or None (UNKNOWN) when DB unavailable.

        Returns:
            None in stub mode — never a fabricated number.
        """
        if not self._available:
            return _IMAGE_COUNT_UNKNOWN
        raise NotImplementedError(
            "IMAGE_GATEWAY_NOT_IMPLEMENTED: real image DB connectivity not available "
            "in this slice; use stub (available=False) or connect a real image adapter"
        )

    def is_available(self) -> bool:
        return self._available


class ImageSourcePrecedence:
    """Arbitrates between competing image records.

    Rule: CURATOR_REVIEWED > UNVERIFIED > AUTOMATED_SUGGESTION > UNAVAILABLE.
    """

    def resolve(self, records: list[ImageRecord]) -> ImageRecord:
        if not records:
            raise ValueError("IMAGE_SOURCE_EMPTY: at least one record required")
        return max(records, key=lambda r: _IMAGE_SOURCE_PRECEDENCE.get(r.evidence_state, 0))

    def is_curator_reviewed(self, record: ImageRecord) -> bool:
        return record.evidence_state == ImageEvidenceState.CURATOR_REVIEWED


def build_unavailable_image_matrix(taxon_ids: list[str]) -> list[ImageRecord]:
    """Return all-UNKNOWN/UNAVAILABLE image stubs when the image DB is absent.

    No counts or records are fabricated.

    Args:
        taxon_ids: Taxon IDs to build unavailable stubs for.

    Returns:
        A list of ImageRecord with evidence_state=UNAVAILABLE and
        license_state=UNKNOWN for every requested taxon_id.
    """
    return [
        ImageRecord(
            image_id=f"unavailable:{tid}",
            taxon_id=tid,
            taxon_name="",
            image_type=ImageType.UNKNOWN_TYPE,
            license_state=LicenseState.UNKNOWN,
            attribution="",
            source_authority="NO_DB_CONNECTION",
            evidence_state=ImageEvidenceState.UNAVAILABLE,
            is_broken=True,
        )
        for tid in taxon_ids
    ]
