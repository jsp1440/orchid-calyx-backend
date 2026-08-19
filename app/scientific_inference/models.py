from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class InferenceDomain(StrEnum):
    TAXONOMY = "TAXONOMY"
    ECOLOGY = "ECOLOGY"
    RELATIONSHIP = "RELATIONSHIP"
    CONSERVATION = "CONSERVATION"
    GENERAL = "GENERAL"


class InferenceState(StrEnum):
    CANDIDATE = "CANDIDATE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    CONFLICT_REVIEW_REQUIRED = "CONFLICT_REVIEW_REQUIRED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True)
class ScientificInferenceEnvelope:
    schema: str
    inference_id: str
    domain: InferenceDomain
    statement: str
    state: InferenceState
    aggregate_refs: tuple[dict[str, Any], ...]
    source_anchor_refs: tuple[dict[str, Any], ...]
    confidence_score: float
    confidence_band: str
    confidence_components: dict[str, float | None]
    conflict_summary: dict[str, int]
    assumptions: tuple[str, ...] = ()
    known_limitations: tuple[str, ...] = ()
    confidence_interpretation: str = "HEURISTIC_EVIDENCE_SUPPORT_INDEX"
    confidence_is_probability: bool = False
    confidence_calibrated: bool = False
    review_required: bool = True
    reviewed_conclusion: bool = False
    published: bool = False
    scientific_publication_authorized: bool = False
    knowledge_graph_mutation_authorized: bool = False
    provenance: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.statement.strip():
            raise ValueError("INFERENCE_STATEMENT_REQUIRED")
        if not self.aggregate_refs:
            raise ValueError("CANONICAL_EVIDENCE_AGGREGATES_REQUIRED")
        if not 0.0 <= self.confidence_score <= 1.0:
            raise ValueError("INVALID_INFERENCE_CONFIDENCE")
        if self.confidence_is_probability or self.confidence_calibrated:
            raise ValueError("INFERENCE_CONFIDENCE_IS_NOT_A_CALIBRATED_PROBABILITY")
        if self.reviewed_conclusion or self.published:
            raise ValueError("INFERENCE_ENVELOPE_CANNOT_SELF_PROMOTE")
        if self.scientific_publication_authorized or self.knowledge_graph_mutation_authorized:
            raise ValueError("INFERENCE_ENVELOPE_HAS_NO_PUBLICATION_AUTHORITY")
