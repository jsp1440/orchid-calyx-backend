from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class CandidateKind(StrEnum):
    TAXON = "TAXON"
    TRAIT = "TRAIT"
    MORPHOLOGY_TERM = "MORPHOLOGY_TERM"
    ECOLOGICAL_RELATIONSHIP = "ECOLOGICAL_RELATIONSHIP"
    GEOGRAPHIC_OCCURRENCE = "GEOGRAPHIC_OCCURRENCE"
    PHENOLOGY_EVENT = "PHENOLOGY_EVENT"
    CONSERVATION_ASSERTION = "CONSERVATION_ASSERTION"
    MEASUREMENT = "MEASUREMENT"
    MOLECULAR_MARKER = "MOLECULAR_MARKER"
    CULTIVATION_OBSERVATION = "CULTIVATION_OBSERVATION"


@dataclass(frozen=True)
class SourceAnchor:
    anchor_id: int
    ordered_span: int = 0
    page_number: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    block_id: str | None = None
    logical_unit: str | None = None
    bounding_region: dict[str, Any] | None = None
    locator: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.anchor_id <= 0:
            raise ValueError("EXACT_SOURCE_ANCHOR_REQUIRED")
        if self.char_start is not None and self.char_end is not None and self.char_end < self.char_start:
            raise ValueError("INVALID_SOURCE_ANCHOR_RANGE")


@dataclass(frozen=True)
class EvidenceInput:
    source_object_type: str
    source_object_id: int
    revision_id: int
    extraction_run_id: int
    text: str
    source_anchors: tuple[SourceAnchor, ...]
    display_policy: str = "UNKNOWN_REQUIRES_REVIEW"
    internal_use_permission: bool = False
    language: str = "en"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if min(self.source_object_id, self.revision_id, self.extraction_run_id) <= 0:
            raise ValueError("INVALID_CANONICAL_SOURCE_IDENTITY")
        if not self.source_anchors:
            raise ValueError("EXACT_SOURCE_ANCHORS_REQUIRED")
        if not self.text.strip():
            raise ValueError("EMPTY_EVIDENCE")


@dataclass(frozen=True)
class CandidateFact:
    kind: CandidateKind
    subject: str
    predicate: str
    object_value: str | None = None
    numeric_value: float | None = None
    unit: str | None = None
    qualifiers: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.5
    method: str = "DETERMINISTIC_RULE"

    def __post_init__(self) -> None:
        if not self.subject.strip() or not self.predicate.strip():
            raise ValueError("CANDIDATE_SUBJECT_AND_PREDICATE_REQUIRED")
        if self.object_value is None and self.numeric_value is None:
            raise ValueError("CANDIDATE_VALUE_REQUIRED")
        if not 0 <= self.confidence <= 1:
            raise ValueError("INVALID_CONFIDENCE")
