"""Atomic publication transaction models for the Scientific Kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .exceptions import ScientificObjectValidationError
from .identity import OCID, OCIDFactory, OCIDKind
from .models import ScientificObject


class PublicationStatus(str, Enum):
    """Lifecycle states for a scientific publication transaction."""

    DRAFT = "draft"
    PREPARED = "prepared"
    COMMITTED = "committed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class PublicationManifest:
    """Immutable set of scientific objects included in one atomic publication."""

    object_ocids: tuple[OCID, ...]
    root_ocids: tuple[OCID, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        object_ocids = tuple(self.object_ocids)
        root_ocids = tuple(self.root_ocids)
        if not object_ocids:
            raise ScientificObjectValidationError(
                "publication manifest requires at least one object OCID"
            )
        if len(set(object_ocids)) != len(object_ocids):
            raise ScientificObjectValidationError(
                "publication manifest object_ocids must be unique"
            )
        if len(set(root_ocids)) != len(root_ocids):
            raise ScientificObjectValidationError(
                "publication manifest root_ocids must be unique"
            )
        if any(root not in object_ocids for root in root_ocids):
            raise ScientificObjectValidationError(
                "publication manifest roots must also appear in object_ocids"
            )
        object.__setattr__(self, "object_ocids", object_ocids)
        object.__setattr__(self, "root_ocids", root_ocids)


@dataclass(frozen=True, slots=True)
class Publication(ScientificObject):
    """Immutable, atomic release of one or more scientific objects."""

    ocid: OCID = field(default_factory=lambda: OCIDFactory.new(OCIDKind.PUBLICATION))
    object_type: str = "publication"
    manifest: PublicationManifest = field(
        default_factory=lambda: PublicationManifest((OCIDFactory.new(),))
    )
    status: PublicationStatus = PublicationStatus.DRAFT
    prepared_by: str | None = None
    committed_by: str | None = None
    committed_at: datetime | None = None
    supersedes_publication_ocid: OCID | None = None
    rejection_reason: str | None = None
    annotations: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ScientificObject.__post_init__(self)
        if self.ocid.kind is not OCIDKind.PUBLICATION:
            raise ScientificObjectValidationError(
                "publication requires a PUBLICATION OCID"
            )
        if (
            self.supersedes_publication_ocid is not None
            and self.supersedes_publication_ocid.kind is not OCIDKind.PUBLICATION
        ):
            raise ScientificObjectValidationError(
                "supersedes_publication_ocid must use a PUBLICATION OCID"
            )

        prepared_by = self.prepared_by.strip() if self.prepared_by is not None else None
        committed_by = self.committed_by.strip() if self.committed_by is not None else None
        rejection_reason = (
            self.rejection_reason.strip() if self.rejection_reason is not None else None
        )
        committed_at = _normalize_datetime(self.committed_at, "committed_at")

        if self.status is PublicationStatus.PREPARED and not prepared_by:
            raise ScientificObjectValidationError(
                "prepared publications require prepared_by"
            )
        if self.status is PublicationStatus.COMMITTED:
            if not prepared_by or not committed_by or committed_at is None:
                raise ScientificObjectValidationError(
                    "committed publications require prepared_by, committed_by, and committed_at"
                )
            if committed_at < self.created_at:
                raise ScientificObjectValidationError(
                    "committed_at must not precede created_at"
                )
        elif committed_at is not None or committed_by:
            raise ScientificObjectValidationError(
                "committed_by and committed_at are valid only for committed publications"
            )
        if self.status is PublicationStatus.REJECTED and not rejection_reason:
            raise ScientificObjectValidationError(
                "rejected publications require rejection_reason"
            )
        if self.status is not PublicationStatus.REJECTED and rejection_reason:
            raise ScientificObjectValidationError(
                "rejection_reason is valid only for rejected publications"
            )
        if (
            self.status is PublicationStatus.SUPERSEDED
            and self.supersedes_publication_ocid is None
        ):
            raise ScientificObjectValidationError(
                "superseded publications require supersedes_publication_ocid"
            )
        if self.supersedes_publication_ocid == self.ocid:
            raise ScientificObjectValidationError(
                "publication cannot supersede itself"
            )

        object.__setattr__(self, "prepared_by", prepared_by or None)
        object.__setattr__(self, "committed_by", committed_by or None)
        object.__setattr__(self, "committed_at", committed_at)
        object.__setattr__(self, "rejection_reason", rejection_reason or None)
        object.__setattr__(self, "annotations", MappingProxyType(dict(self.annotations)))

    @property
    def is_committed(self) -> bool:
        """Return whether the publication has completed its atomic commit."""

        return self.status is PublicationStatus.COMMITTED

    @property
    def object_count(self) -> int:
        """Return the number of scientific objects in the publication manifest."""

        return len(self.manifest.object_ocids)


def _normalize_datetime(value: datetime | None, field_name: str) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None or value.utcoffset() is None:
        raise ScientificObjectValidationError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)
