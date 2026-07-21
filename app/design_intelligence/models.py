from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import StrEnum
from typing import Any


class DesignDomain(StrEnum):
    USER_EXPERIENCE = "USER_EXPERIENCE"
    USER_INTERFACE = "USER_INTERFACE"
    GRAPHIC_DESIGN = "GRAPHIC_DESIGN"
    INFORMATION_ARCHITECTURE = "INFORMATION_ARCHITECTURE"
    INTERACTION_DESIGN = "INTERACTION_DESIGN"
    DASHBOARD_DESIGN = "DASHBOARD_DESIGN"
    ACCESSIBILITY = "ACCESSIBILITY"
    MOTION_AND_ANIMATION = "MOTION_AND_ANIMATION"
    EDUCATIONAL_DESIGN = "EDUCATIONAL_DESIGN"
    LEARNING_SCIENCES = "LEARNING_SCIENCES"
    SCIENTIFIC_VISUALIZATION = "SCIENTIFIC_VISUALIZATION"
    BRANDING_AND_VISUAL_IDENTITY = "BRANDING_AND_VISUAL_IDENTITY"
    DESIGN_SYSTEMS = "DESIGN_SYSTEMS"
    COMPONENT_LIBRARIES = "COMPONENT_LIBRARIES"


class DesignKnowledgeType(StrEnum):
    DESIGN_PRINCIPLE = "DESIGN_PRINCIPLE"
    PATTERN = "PATTERN"
    ANTI_PATTERN = "ANTI_PATTERN"
    GUIDELINE = "GUIDELINE"
    STANDARD = "STANDARD"
    BEST_PRACTICE = "BEST_PRACTICE"
    EDUCATIONAL_THEORY = "EDUCATIONAL_THEORY"
    ACCESSIBILITY_REQUIREMENT = "ACCESSIBILITY_REQUIREMENT"
    VISUALIZATION_TECHNIQUE = "VISUALIZATION_TECHNIQUE"
    INTERACTION_PATTERN = "INTERACTION_PATTERN"


class PublicationStatus(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"
    RETRACTED = "RETRACTED"


class ReviewState(StrEnum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class DesignProvenance:
    source_system: str
    source_id: str
    revision_id: int
    extraction_run_id: int
    anchor_ids: tuple[int, ...]
    content_hash: str
    evidence_link_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not self.source_system.strip() or not self.source_id.strip():
            raise ValueError("DESIGN_SOURCE_IDENTITY_REQUIRED")
        if min(self.revision_id, self.extraction_run_id) <= 0 or not self.anchor_ids:
            raise ValueError("DESIGN_EXACT_PROVENANCE_REQUIRED")
        if len(self.content_hash) != 64:
            raise ValueError("DESIGN_CONTENT_HASH_REQUIRED")


@dataclass(frozen=True)
class DesignDocumentInput:
    logical_key: str
    title: str
    content: str
    document_type: str
    authors: tuple[str, ...]
    publication_date: date | None
    license_metadata: dict[str, Any]
    provenance: DesignProvenance
    topics: tuple[str, ...] = ()
    requested_domains: tuple[DesignDomain, ...] = ()
    requested_types: tuple[DesignKnowledgeType, ...] = ()
    source_metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (self.logical_key, self.title, self.content, self.document_type)
        ):
            raise ValueError("INCOMPLETE_DESIGN_DOCUMENT")
        if not self.authors or not self.license_metadata.get("license"):
            raise ValueError("DESIGN_AUTHOR_AND_LICENSE_REQUIRED")


@dataclass(frozen=True)
class DesignDocument:
    document_id: int
    logical_key: str
    version: int
    title: str
    content: str
    document_type: str
    authors: tuple[str, ...]
    publication_date: date | None
    license_metadata: dict[str, Any]
    provenance: DesignProvenance
    domains: tuple[DesignDomain, ...]
    knowledge_types: tuple[DesignKnowledgeType, ...]
    topics: tuple[str, ...]
    classification_confidence: float
    classification_version: str
    source_metadata: dict[str, Any]
    created_at: datetime


@dataclass(frozen=True)
class DesignReviewDecision:
    state: ReviewState
    actor: str
    rationale: str
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.state is ReviewState.PENDING:
            raise ValueError("REVIEW_DECISION_MUST_BE_TERMINAL")
        if not self.actor.strip() or not self.rationale.strip():
            raise ValueError("DESIGN_REVIEW_AUDIT_REQUIRED")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
