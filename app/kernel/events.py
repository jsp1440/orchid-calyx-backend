"""Immutable Scientific Kernel event contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .exceptions import ScientificObjectValidationError
from .identity import OCID, OCIDFactory, OCIDKind
from .models import ScientificObject


class EventType(str, Enum):
    """Canonical domain events emitted by Scientific Kernel engines."""

    EVIDENCE_REGISTERED = "evidence_registered"
    ASSERTION_PUBLISHED = "assertion_published"
    RELATIONSHIP_CREATED = "relationship_created"
    PUBLICATION_PREPARED = "publication_prepared"
    PUBLICATION_COMMITTED = "publication_committed"
    PUBLICATION_REJECTED = "publication_rejected"
    KNOWLEDGE_OBJECT_PUBLISHED = "knowledge_object_published"
    OBJECT_SUPERSEDED = "object_superseded"
    OBJECT_DISPUTED = "object_disputed"
    OBJECT_REJECTED = "object_rejected"


@dataclass(frozen=True, slots=True)
class ScientificEvent(ScientificObject):
    """Immutable event emitted after a Scientific Kernel state transition."""

    ocid: OCID = field(default_factory=lambda: OCIDFactory.new(OCIDKind.EVENT))
    object_type: str = "event"
    event_type: EventType = EventType.EVIDENCE_REGISTERED
    subject_ocid: OCID = field(default_factory=OCIDFactory.new)
    actor: str | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    publication_ocid: OCID | None = None
    correlation_ocid: OCID | None = None
    causation_event_ocid: OCID | None = None
    sequence: int = 1
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ScientificObject.__post_init__(self)
        if self.ocid.kind is not OCIDKind.EVENT:
            raise ScientificObjectValidationError("scientific event requires an EVENT OCID")
        if self.publication_ocid is not None and self.publication_ocid.kind is not OCIDKind.PUBLICATION:
            raise ScientificObjectValidationError(
                "publication_ocid must use a PUBLICATION OCID"
            )
        if (
            self.causation_event_ocid is not None
            and self.causation_event_ocid.kind is not OCIDKind.EVENT
        ):
            raise ScientificObjectValidationError(
                "causation_event_ocid must use an EVENT OCID"
            )
        if self.causation_event_ocid == self.ocid:
            raise ScientificObjectValidationError("scientific event cannot cause itself")
        if self.sequence < 1:
            raise ScientificObjectValidationError("event sequence must be at least 1")
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ScientificObjectValidationError("occurred_at must be timezone-aware")

        actor = self.actor.strip() if self.actor is not None else None
        object.__setattr__(self, "actor", actor or None)
        object.__setattr__(self, "occurred_at", self.occurred_at.astimezone(timezone.utc))
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    @property
    def is_publication_scoped(self) -> bool:
        """Return whether the event belongs to an atomic publication transaction."""

        return self.publication_ocid is not None
