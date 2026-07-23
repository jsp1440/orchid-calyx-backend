"""Evidence-backed scientific assertion models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .exceptions import ScientificObjectValidationError
from .identity import OCID, OCIDFactory, OCIDKind
from .models import ScientificObject


class AssertionStatus(str, Enum):
    """Lifecycle states for scientific assertions."""

    DRAFT = "draft"
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    DISPUTED = "disputed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class Confidence:
    """Normalized confidence score with a transparent assessment basis."""

    score: float
    method: str = "unspecified"
    rationale: str | None = None

    def __post_init__(self) -> None:
        score = float(self.score)
        if not 0.0 <= score <= 1.0:
            raise ScientificObjectValidationError("confidence score must be between 0 and 1")
        method = self.method.strip()
        if not method:
            raise ScientificObjectValidationError("confidence method must not be empty")
        rationale = self.rationale.strip() if self.rationale is not None else None
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "rationale", rationale or None)


@dataclass(frozen=True, slots=True)
class AssertionObject:
    """Object side of an assertion, represented by an OCID or literal value."""

    ocid: OCID | None = None
    value: Any | None = None
    datatype: str | None = None
    unit: str | None = None

    def __post_init__(self) -> None:
        if (self.ocid is None) == (self.value is None):
            raise ScientificObjectValidationError(
                "assertion object requires exactly one of ocid or value"
            )
        datatype = self.datatype.strip() if self.datatype is not None else None
        unit = self.unit.strip() if self.unit is not None else None
        if self.ocid is not None and (datatype or unit):
            raise ScientificObjectValidationError(
                "datatype and unit apply only to literal assertion objects"
            )
        object.__setattr__(self, "datatype", datatype or None)
        object.__setattr__(self, "unit", unit or None)


@dataclass(frozen=True, slots=True)
class Assertion(ScientificObject):
    """Immutable subject-predicate-object claim supported by scientific evidence."""

    ocid: OCID = field(default_factory=lambda: OCIDFactory.new(OCIDKind.ASSERTION))
    object_type: str = "assertion"
    subject_ocid: OCID = field(default_factory=OCIDFactory.new)
    predicate: str = ""
    assertion_object: AssertionObject = field(
        default_factory=lambda: AssertionObject(value="unspecified")
    )
    evidence_ocids: tuple[OCID, ...] = field(default_factory=tuple)
    confidence: Confidence = field(default_factory=lambda: Confidence(0.0))
    status: AssertionStatus = AssertionStatus.DRAFT
    asserted_by: str | None = None
    reviewed_by: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    qualifiers: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.ocid.kind is not OCIDKind.ASSERTION:
            raise ScientificObjectValidationError("assertion requires an ASSERTION OCID")
        predicate = self.predicate.strip()
        if not predicate:
            raise ScientificObjectValidationError("assertion predicate must not be empty")
        if any(ocid.kind is not OCIDKind.EVIDENCE for ocid in self.evidence_ocids):
            raise ScientificObjectValidationError(
                "assertion evidence_ocids must contain only EVIDENCE OCIDs"
            )
        if len(set(self.evidence_ocids)) != len(self.evidence_ocids):
            raise ScientificObjectValidationError("assertion evidence_ocids must be unique")
        if self.status in {
            AssertionStatus.ACCEPTED,
            AssertionStatus.DISPUTED,
            AssertionStatus.REJECTED,
            AssertionStatus.SUPERSEDED,
        } and not self.evidence_ocids:
            raise ScientificObjectValidationError(
                f"{self.status.value} assertions require at least one evidence OCID"
            )
        valid_from = _normalize_datetime(self.valid_from, "valid_from")
        valid_until = _normalize_datetime(self.valid_until, "valid_until")
        if valid_from is not None and valid_until is not None and valid_until <= valid_from:
            raise ScientificObjectValidationError("valid_until must be later than valid_from")
        asserted_by = self.asserted_by.strip() if self.asserted_by is not None else None
        reviewed_by = self.reviewed_by.strip() if self.reviewed_by is not None else None
        object.__setattr__(self, "predicate", predicate)
        object.__setattr__(self, "asserted_by", asserted_by or None)
        object.__setattr__(self, "reviewed_by", reviewed_by or None)
        object.__setattr__(self, "valid_from", valid_from)
        object.__setattr__(self, "valid_until", valid_until)
        object.__setattr__(self, "qualifiers", MappingProxyType(dict(self.qualifiers)))
        object.__setattr__(self, "evidence_ocids", tuple(self.evidence_ocids))

    @property
    def is_evidence_backed(self) -> bool:
        """Return whether this assertion cites one or more evidence objects."""

        return bool(self.evidence_ocids)


def _normalize_datetime(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ScientificObjectValidationError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)
