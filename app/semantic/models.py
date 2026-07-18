from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ExtractionStage(StrEnum):
    QUEUED = "QUEUED"
    PARSING = "PARSING"
    ENTITY_EXTRACTION = "ENTITY_EXTRACTION"
    RELATIONSHIP_EXTRACTION = "RELATIONSHIP_EXTRACTION"
    EVIDENCE_GENERATION = "EVIDENCE_GENERATION"
    CANDIDATE_GENERATION = "CANDIDATE_GENERATION"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    FAILED = "FAILED"


STAGE_TRANSITIONS: dict[ExtractionStage, frozenset[ExtractionStage]] = {
    ExtractionStage.QUEUED: frozenset({ExtractionStage.PARSING, ExtractionStage.FAILED}),
    ExtractionStage.PARSING: frozenset({ExtractionStage.ENTITY_EXTRACTION, ExtractionStage.FAILED}),
    ExtractionStage.ENTITY_EXTRACTION: frozenset({ExtractionStage.RELATIONSHIP_EXTRACTION, ExtractionStage.FAILED}),
    ExtractionStage.RELATIONSHIP_EXTRACTION: frozenset({ExtractionStage.EVIDENCE_GENERATION, ExtractionStage.FAILED}),
    ExtractionStage.EVIDENCE_GENERATION: frozenset({ExtractionStage.CANDIDATE_GENERATION, ExtractionStage.FAILED}),
    ExtractionStage.CANDIDATE_GENERATION: frozenset({ExtractionStage.READY_FOR_REVIEW, ExtractionStage.FAILED}),
    ExtractionStage.READY_FOR_REVIEW: frozenset(),
    ExtractionStage.FAILED: frozenset(),
}


def validate_transition(current: ExtractionStage, target: ExtractionStage) -> None:
    if target not in STAGE_TRANSITIONS[current]:
        raise ValueError(f"INVALID_EXTRACTION_TRANSITION:{current}:{target}")


@dataclass(frozen=True)
class EntityDraft:
    entity_type: str
    name: str
    normalized_name: str
    confidence: float
    start_offset: int
    end_offset: int
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RelationshipDraft:
    subject_index: int
    predicate: str
    object_index: int
    confidence: float
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class EvidenceDraft:
    evidence_type: str
    exact_text: str
    start_offset: int
    end_offset: int
    source_sha256: str
    provenance: dict[str, Any]


@dataclass(frozen=True)
class CandidateEntity:
    id: int
    session_id: int
    entity_type: str
    name: str
    normalized_name: str
    confidence: float
    review_status: str
    version: int


@dataclass(frozen=True)
class CandidateRelationship:
    id: int
    session_id: int
    subject_candidate_id: int
    predicate: str
    object_candidate_id: int
    evidence_id: int
    confidence: float
    review_status: str
    version: int


@dataclass(frozen=True)
class EvidenceObject:
    id: int
    session_id: int
    evidence_type: str
    exact_text: str
    start_offset: int
    end_offset: int
    source_sha256: str
    provenance: dict[str, Any]
