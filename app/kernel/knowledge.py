"""Curated knowledge-object models for the Scientific Kernel."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

from .exceptions import ScientificObjectValidationError
from .identity import OCID, OCIDFactory, OCIDKind
from .models import ScientificObject


class KnowledgeObjectType(str, Enum):
    """Canonical curated knowledge categories."""

    TAXON = "taxon"
    TRAIT_PROFILE = "trait_profile"
    DISTRIBUTION_PROFILE = "distribution_profile"
    ECOLOGICAL_PROFILE = "ecological_profile"
    CULTURE_PROFILE = "culture_profile"
    CONSERVATION_PROFILE = "conservation_profile"
    LITERATURE_SYNTHESIS = "literature_synthesis"
    CONCEPT = "concept"
    GENERIC = "generic"


class KnowledgeStatus(str, Enum):
    """Lifecycle states for curated knowledge objects."""

    DRAFT = "draft"
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    DISPUTED = "disputed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class KnowledgeObject(ScientificObject):
    """Immutable synthesis built from assertions, relationships, and evidence."""

    ocid: OCID = field(default_factory=lambda: OCIDFactory.new(OCIDKind.KNOWLEDGE_OBJECT))
    object_type: str = "knowledge_object"
    knowledge_type: KnowledgeObjectType = KnowledgeObjectType.GENERIC
    subject_ocids: tuple[OCID, ...] = field(default_factory=tuple)
    assertion_ocids: tuple[OCID, ...] = field(default_factory=tuple)
    relationship_ocids: tuple[OCID, ...] = field(default_factory=tuple)
    evidence_ocids: tuple[OCID, ...] = field(default_factory=tuple)
    publication_ocids: tuple[OCID, ...] = field(default_factory=tuple)
    status: KnowledgeStatus = KnowledgeStatus.DRAFT
    title: str = ""
    summary: str | None = None
    curated_by: str | None = None
    reviewed_by: str | None = None
    supersedes_knowledge_ocid: OCID | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        ScientificObject.__post_init__(self)
        if self.ocid.kind is not OCIDKind.KNOWLEDGE_OBJECT:
            raise ScientificObjectValidationError(
                "knowledge object requires a KNOWLEDGE_OBJECT OCID"
            )

        title = self.title.strip()
        if not title:
            raise ScientificObjectValidationError("knowledge object title must not be empty")

        summary = self.summary.strip() if self.summary is not None else None
        curated_by = self.curated_by.strip() if self.curated_by is not None else None
        reviewed_by = self.reviewed_by.strip() if self.reviewed_by is not None else None

        object_sets = {
            "subject_ocids": tuple(self.subject_ocids),
            "assertion_ocids": tuple(self.assertion_ocids),
            "relationship_ocids": tuple(self.relationship_ocids),
            "evidence_ocids": tuple(self.evidence_ocids),
            "publication_ocids": tuple(self.publication_ocids),
        }
        for field_name, values in object_sets.items():
            if len(set(values)) != len(values):
                raise ScientificObjectValidationError(f"{field_name} must be unique")

        if any(ocid.kind is not OCIDKind.ASSERTION for ocid in object_sets["assertion_ocids"]):
            raise ScientificObjectValidationError(
                "assertion_ocids must contain only ASSERTION OCIDs"
            )
        if any(
            ocid.kind is not OCIDKind.RELATIONSHIP
            for ocid in object_sets["relationship_ocids"]
        ):
            raise ScientificObjectValidationError(
                "relationship_ocids must contain only RELATIONSHIP OCIDs"
            )
        if any(ocid.kind is not OCIDKind.EVIDENCE for ocid in object_sets["evidence_ocids"]):
            raise ScientificObjectValidationError(
                "evidence_ocids must contain only EVIDENCE OCIDs"
            )
        if any(
            ocid.kind is not OCIDKind.PUBLICATION
            for ocid in object_sets["publication_ocids"]
        ):
            raise ScientificObjectValidationError(
                "publication_ocids must contain only PUBLICATION OCIDs"
            )

        if self.status in {
            KnowledgeStatus.ACCEPTED,
            KnowledgeStatus.DISPUTED,
            KnowledgeStatus.REJECTED,
            KnowledgeStatus.SUPERSEDED,
        } and not (
            object_sets["assertion_ocids"]
            or object_sets["relationship_ocids"]
            or object_sets["evidence_ocids"]
            or object_sets["publication_ocids"]
        ):
            raise ScientificObjectValidationError(
                f"{self.status.value} knowledge objects require supporting scientific objects"
            )

        if self.status is KnowledgeStatus.ACCEPTED and not reviewed_by:
            raise ScientificObjectValidationError(
                "accepted knowledge objects require reviewed_by"
            )

        if self.supersedes_knowledge_ocid is not None:
            if self.supersedes_knowledge_ocid.kind is not OCIDKind.KNOWLEDGE_OBJECT:
                raise ScientificObjectValidationError(
                    "supersedes_knowledge_ocid must use a KNOWLEDGE_OBJECT OCID"
                )
            if self.supersedes_knowledge_ocid == self.ocid:
                raise ScientificObjectValidationError(
                    "knowledge object cannot supersede itself"
                )
        if (
            self.status is KnowledgeStatus.SUPERSEDED
            and self.supersedes_knowledge_ocid is None
        ):
            raise ScientificObjectValidationError(
                "superseded knowledge objects require supersedes_knowledge_ocid"
            )

        object.__setattr__(self, "title", title)
        object.__setattr__(self, "summary", summary or None)
        object.__setattr__(self, "curated_by", curated_by or None)
        object.__setattr__(self, "reviewed_by", reviewed_by or None)
        for field_name, values in object_sets.items():
            object.__setattr__(self, field_name, values)
        object.__setattr__(self, "attributes", MappingProxyType(dict(self.attributes)))

    @property
    def support_count(self) -> int:
        """Return the total number of linked supporting scientific objects."""

        return (
            len(self.assertion_ocids)
            + len(self.relationship_ocids)
            + len(self.evidence_ocids)
            + len(self.publication_ocids)
        )

    @property
    def is_supported(self) -> bool:
        """Return whether the knowledge object links to supporting objects."""

        return self.support_count > 0
