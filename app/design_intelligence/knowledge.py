from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class SemanticUnitType(StrEnum):
    HEADING = "HEADING"
    SECTION = "SECTION"
    PARAGRAPH = "PARAGRAPH"
    BULLET_LIST = "BULLET_LIST"
    NUMBERED_PROCEDURE = "NUMBERED_PROCEDURE"
    TABLE = "TABLE"
    CAPTION = "CAPTION"
    CODE_EXAMPLE = "CODE_EXAMPLE"
    QUOTED_GUIDANCE = "QUOTED_GUIDANCE"
    RECOMMENDATION = "RECOMMENDATION"
    WARNING = "WARNING"
    ANTI_PATTERN = "ANTI_PATTERN"
    BEST_PRACTICE = "BEST_PRACTICE"


class SemanticDesignDomain(StrEnum):
    UX = "UX"
    UI = "UI"
    INTERACTION_DESIGN = "INTERACTION_DESIGN"
    DASHBOARD_DESIGN = "DASHBOARD_DESIGN"
    INFORMATION_ARCHITECTURE = "INFORMATION_ARCHITECTURE"
    ACCESSIBILITY = "ACCESSIBILITY"
    MOTION_DESIGN = "MOTION_DESIGN"
    ANIMATION = "ANIMATION"
    TYPOGRAPHY = "TYPOGRAPHY"
    COLOR_SYSTEMS = "COLOR_SYSTEMS"
    BRANDING = "BRANDING"
    DESIGN_SYSTEMS = "DESIGN_SYSTEMS"
    COMPONENT_LIBRARIES = "COMPONENT_LIBRARIES"
    EDUCATIONAL_PSYCHOLOGY = "EDUCATIONAL_PSYCHOLOGY"
    LEARNING_SCIENCES = "LEARNING_SCIENCES"
    SCIENTIFIC_VISUALIZATION = "SCIENTIFIC_VISUALIZATION"
    KNOWLEDGE_GRAPH_VISUALIZATION = "KNOWLEDGE_GRAPH_VISUALIZATION"
    SCIENTIFIC_COMMUNICATION = "SCIENTIFIC_COMMUNICATION"


class EducationalClassification(StrEnum):
    BLOOM = "BLOOM"
    MAYER_MULTIMEDIA_LEARNING = "MAYER_MULTIMEDIA_LEARNING"
    COGNITIVE_LOAD_THEORY = "COGNITIVE_LOAD_THEORY"
    UNIVERSAL_DESIGN_FOR_LEARNING = "UNIVERSAL_DESIGN_FOR_LEARNING"
    ACTIVE_LEARNING = "ACTIVE_LEARNING"
    INQUIRY_LEARNING = "INQUIRY_LEARNING"


class RelationshipType(StrEnum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    EXTENDS = "EXTENDS"
    SPECIALIZES = "SPECIALIZES"
    RELATED_TO = "RELATED_TO"
    USED_BY = "USED_BY"
    IMPROVES = "IMPROVES"
    REQUIRES = "REQUIRES"
    REFERENCES = "REFERENCES"


@dataclass(frozen=True)
class SourceLocation:
    format: str
    start: int
    end: int
    locator: dict[str, Any]
    content_hash: str


@dataclass(frozen=True)
class SemanticUnit:
    unit_id: str
    document_id: int
    document_version: int
    ordinal: int
    unit_type: SemanticUnitType
    text: str
    source_location: SourceLocation
    parent_unit_id: str | None = None
    domains: tuple[SemanticDesignDomain, ...] = ()
    educational_classifications: tuple[EducationalClassification, ...] = ()
    knowledge_types: tuple[str, ...] = ()
    classification_confidence: float = 0.0
    classification_evidence: tuple[str, ...] = ()
    classification_version: str = "089b-rules-1"
    embedding: tuple[float, ...] = ()
    embedding_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DesignRelationship:
    relationship_id: str
    source_unit_id: str
    target_unit_id: str
    relationship_type: RelationshipType
    confidence: float
    rationale: str
    provenance: dict[str, Any]
    generator_version: str = "089b-relationships-1"
