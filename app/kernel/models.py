"""Foundational immutable scientific object model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Mapping, Any

from .exceptions import ScientificObjectValidationError
from .identity import OCID, OCIDFactory, OCIDKind


@dataclass(frozen=True, slots=True)
class ScientificObject:
    """Base contract shared by all durable Scientific Kernel objects.

    Instances are immutable, globally identified, timestamped in UTC, and carry
    read-only metadata suitable for extension by more specialized kernel models.
    """

    ocid: OCID = field(default_factory=OCIDFactory.new)
    object_type: str = "scientific_object"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object_type = self.object_type.strip()
        if not object_type:
            raise ScientificObjectValidationError("object_type must not be empty")
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ScientificObjectValidationError("created_at must be timezone-aware")
        if self.ocid.kind is OCIDKind.SCIENTIFIC_OBJECT and object_type != "scientific_object":
            raise ScientificObjectValidationError(
                "specialized object_type values require a specialized OCID kind"
            )
        object.__setattr__(self, "object_type", object_type)
        object.__setattr__(self, "created_at", self.created_at.astimezone(timezone.utc))
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
