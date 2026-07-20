from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ContextForm(StrEnum):
    PARAGRAPH = "PARAGRAPH"
    LINKED_SENTENCES = "LINKED_SENTENCES"
    TABLE_WITH_HEADERS = "TABLE_WITH_HEADERS"
    FIGURE_WITH_CAPTION = "FIGURE_WITH_CAPTION"
    METHODS_RESULTS = "METHODS_RESULTS"
    TAXONOMIC_TREATMENT = "TAXONOMIC_TREATMENT"
    SEMANTIC_CONTEXT = "SEMANTIC_CONTEXT"


class CompletenessState(StrEnum):
    PRESENT = "PRESENT"
    EXPLICITLY_ABSENT = "EXPLICITLY_ABSENT"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    AMBIGUOUS = "AMBIGUOUS"
    UNKNOWN = "UNKNOWN"


class PromotionPath(StrEnum):
    AUTOMATIC_PROMOTION = "AUTOMATIC_PROMOTION"
    PROVISIONAL_SCIENTIFIC_ASSERTION = "PROVISIONAL_SCIENTIFIC_ASSERTION"
    EXCEPTION_REVIEW = "EXCEPTION_REVIEW"


CONTEXT_DIMENSIONS = (
    "taxon",
    "anatomical_structure",
    "trait_or_relationship",
    "measurement",
    "units",
    "life_stage",
    "population_or_sample",
    "geographic_locality",
    "temporal_scope",
    "experimental_conditions",
    "environmental_conditions",
    "methods_and_controls",
    "qualifiers",
    "negation",
    "comparison",
    "citations",
    "biological_context",
)


@dataclass(frozen=True)
class SourceAnchorReference:
    anchor_id: int
    order: int
    anchor_type: str
    locator: dict[str, Any]
    content_hash: str
    relationship: str = "CONTEXT"

    def __post_init__(self) -> None:
        if self.anchor_id <= 0 or self.order < 0:
            raise ValueError("INVALID_SOURCE_ANCHOR")
        if not self.anchor_type.strip() or not self.content_hash.strip() or not self.locator:
            raise ValueError("INCOMPLETE_SOURCE_ANCHOR")


@dataclass(frozen=True)
class SourceEvidenceReference:
    source_object_type: str
    source_object_id: int
    source_revision_id: int
    publication_metadata: dict[str, Any]
    copyright_policy: str
    provenance: dict[str, Any]
    anchors: tuple[SourceAnchorReference, ...]

    def __post_init__(self) -> None:
        if min(self.source_object_id, self.source_revision_id) <= 0:
            raise ValueError("INVALID_IMMUTABLE_SOURCE_IDENTITY")
        if not self.source_object_type.strip() or not self.copyright_policy.strip():
            raise ValueError("INCOMPLETE_SOURCE_EVIDENCE")
        if not self.provenance or not self.anchors:
            raise ValueError("SOURCE_PROVENANCE_AND_ANCHORS_REQUIRED")
        if len({anchor.order for anchor in self.anchors}) != len(self.anchors):
            raise ValueError("DUPLICATE_ANCHOR_ORDER")


@dataclass(frozen=True)
class RoutingPolicy:
    policy_name: str
    version: str
    minimum_confidence: float = 0.9
    provisional_confidence: float = 0.6
    minimum_independent_sources: int = 2
    allowed_model_versions: tuple[str, ...] = ()
    mandatory_review_impact_classes: tuple[str, ...] = (
        "CONSERVATION_HIGH_IMPACT",
        "SAFETY_HIGH_IMPACT",
        "NOMENCLATURAL_ACT",
    )
    healthy: bool = True
    calibration_cohort: str = "unconfigured"

    def __post_init__(self) -> None:
        if not self.policy_name.strip() or not self.version.strip():
            raise ValueError("VERSIONED_POLICY_REQUIRED")
        if not 0 <= self.provisional_confidence <= self.minimum_confidence <= 1:
            raise ValueError("INVALID_POLICY_THRESHOLDS")
        if self.minimum_independent_sources < 1:
            raise ValueError("INVALID_INDEPENDENCE_THRESHOLD")


@dataclass(frozen=True)
class InterpretationRequest:
    packet_ids: tuple[int, ...]
    interpretation_key: str
    statement: dict[str, Any]
    reasoning: dict[str, Any]
    confidence_factors: dict[str, float]
    ambiguities: tuple[dict[str, Any], ...] = ()
    alternatives: tuple[dict[str, Any], ...] = ()
    model_version: str = "deterministic-1"
    ruleset_version: str = "build-087b-1"
    vocabulary_versions: dict[str, str] = field(default_factory=dict)
    configuration: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.packet_ids or not self.interpretation_key.strip() or not self.statement:
            raise ValueError("INCOMPLETE_INTERPRETATION_REQUEST")
        if not self.reasoning or not self.confidence_factors:
            raise ValueError("REASONING_AND_CONFIDENCE_REQUIRED")
        if any(not 0 <= value <= 1 for value in self.confidence_factors.values()):
            raise ValueError("INVALID_CONFIDENCE_FACTOR")


@dataclass(frozen=True)
class AssertionRequest:
    assertion_key: str
    normalized_statement: dict[str, Any]
    scientific_scope: dict[str, Any]
    supporting_interpretation_ids: tuple[int, ...]
    conflicting_interpretation_ids: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if not self.assertion_key.strip() or not self.normalized_statement or not self.scientific_scope:
            raise ValueError("INCOMPLETE_ASSERTION_REQUEST")
        if not self.supporting_interpretation_ids:
            raise ValueError("ASSERTION_SUPPORT_REQUIRED")
