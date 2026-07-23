"""Evidence-backed first-class scientific relationship models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .assertions import Confidence
from .exceptions import ScientificObjectValidationError
from .identity import OCID, OCIDFactory, OCIDKind
from .models import ScientificObject


class RelationshipType(str, Enum):
    """Canonical relationship categories used across the Continuum."""

    HAS_PARENT = "has_parent"
    HAS_POLLINATOR = "has_pollinator"
    ASSOCIATED_WITH_MYCORRHIZA = "associated_with_mycorrhiza"
    OCCURS_IN = "occurs_in"
    HAS_TRAIT = "has_trait"
    SUPPORTS = "supports"
    DERIVED_FROM = "derived_from"
    SYNONYM_OF = "synonym_of"
    INTERACTS_WITH = "interacts_with"
    RELATED_TO = "related_to"


class RelationshipDirection(str, Enum):
    """Traversal semantics for a relationship."""

    DIRECTED = "directed"
    BIDIRECTIONAL = "bidirectional"


class RelationshipStatus(str, Enum):
    """Lifecycle states for scientific relationships."""

    DRAFT = "draft"
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    DISPUTED = "disputed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class Relationship(ScientificObject):
    """Immutable evidence-backed connection between two scientific objects."""

    ocid: OCID = field(default_factory=lambda: OCIDFactory.new(OCIDKind.RELATIONSHIP))
    object_type: str = "relationship"
    source_ocid: OCID = field(default_factory=OCIDFactory.new)
    target_ocid: OCID = field(default_factory=OCIDFactory.new)
    relationship_type: RelationshipType = RelationshipType.RELATED_TO
    direction: RelationshipDirection = RelationshipDirection.DIRECTED
    evidence_ocids: tuple[OCID, ...] = field(default_factory=tuple)
    confidence: Confidence = field(default_factory=lambda: Confidence(0.0))
    status: RelationshipStatus = RelationshipStatus.DRAFT
    asserted_by: str | None = None
    reviewed_by: str | None = None
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    qualifiers: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ScientificObject.__post_init__(self)
        if self.ocid.kind is not OCIDKind.RELATIONSHIP:
            raise ScientificObjectValidationError(
                "relationship requires a RELATIONSHIP OCID"
            )
        if self.source_ocid == self.target_ocid:
            raise ScientificObjectValidationError(
                "relationship source_ocid and target_ocid must differ"
            )
        if any(ocid.kind is not OCIDKind.EVIDENCE for ocid in self.evidence_ocids):
            raise ScientificObjectValidationError(
                "relationship evidence_ocids must contain only EVIDENCE OCIDs"
            )
        if len(set(self.evidence_ocids)) != len(self.evidence_ocids):
            raise ScientificObjectValidationError(
                "relationship evidence_ocids must be unique"
            )
        if self.status in {
            RelationshipStatus.ACCEPTED,
            RelationshipStatus.DISPUTED,
            RelationshipStatus.REJECTED,
            RelationshipStatus.SUPERSEDED,
        } and not self.evidence_ocids:
            raise ScientificObjectValidationError(
                f"{self.status.value} relationships require at least one evidence OCID"
            )

        valid_from = _normalize_datetime(self.valid_from, "valid_from")
        valid_until = _normalize_datetime(self.valid_until, "valid_until")
        if valid_from is not None and valid_until is not None and valid_until <= valid_from:
            raise ScientificObjectValidationError(
                "valid_until must be later than valid_from"
            )

        asserted_by = self.asserted_by.strip() if self.asserted_by is not None else None
        reviewed_by = self.reviewed_by.strip() if self.reviewed_by is not None else None
        object.__setattr__(self, "asserted_by", asserted_by or None)
        object.__setattr__(self, "reviewed_by", reviewed_by or None)
        object.__setattr__(self, "valid_from", valid_from)
        object.__setattr__(self, "valid_until", valid_until)
        object.__setattr__(self, "qualifiers", MappingProxyType(dict(self.qualifiers)))
        object.__setattr__(self, "evidence_ocids", tuple(self.evidence_ocids))

    @property
    def is_evidence_backed(self) -> bool:
        """Return whether this relationship cites one or more evidence objects."""

        return bool(self.evidence_ocids)

    def connects(self, ocid: OCID) -> bool:
        """Return whether the relationship touches the supplied object."""

        return ocid in {self.source_ocid, self.target_ocid}

    def traversable_from(self, ocid: OCID) -> bool:
        """Return whether traversal may begin from the supplied object."""

        if self.direction is RelationshipDirection.BIDIRECTIONAL:
            return self.connects(ocid)
        return ocid == self.source_ocid


def _normalize_datetime(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ScientificObjectValidationError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)
