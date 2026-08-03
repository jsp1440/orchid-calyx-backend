from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.candidate_knowledge.dependencies import get_candidate_components
from app.candidate_knowledge.models import CandidateKind, EvidenceInput, SourceAnchor

DOMAIN_KINDS: dict[str, CandidateKind] = {
    "taxonomy": CandidateKind.TAXON,
    "trait": CandidateKind.TRAIT,
    "morphology": CandidateKind.MORPHOLOGY_TERM,
    "ecology": CandidateKind.ECOLOGICAL_RELATIONSHIP,
    "geography": CandidateKind.GEOGRAPHIC_OCCURRENCE,
    "phenology": CandidateKind.PHENOLOGY_EVENT,
    "conservation": CandidateKind.CONSERVATION_ASSERTION,
    "measurement": CandidateKind.MEASUREMENT,
    "molecular": CandidateKind.MOLECULAR_MARKER,
    "cultivation": CandidateKind.CULTIVATION_OBSERVATION,
}


class BrainEvidenceAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    anchor_id: int = Field(gt=0)
    ordered_span: int = Field(default=0, ge=0)
    page_number: int | None = Field(default=None, ge=1)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    block_id: str | None = None
    logical_unit: str | None = None
    locator: dict[str, Any] = Field(default_factory=dict)


class BrainCandidateHandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reasoning_id: str = Field(min_length=1, max_length=240)
    domain: Literal[
        "taxonomy",
        "trait",
        "morphology",
        "ecology",
        "geography",
        "phenology",
        "conservation",
        "measurement",
        "molecular",
        "cultivation",
    ]
    subject: str = Field(min_length=1, max_length=500)
    predicate: str = Field(min_length=1, max_length=240)
    object_value: str | None = Field(default=None, max_length=12000)
    numeric_value: float | None = None
    unit: str | None = Field(default=None, max_length=80)
    confidence: float = Field(ge=0, le=1)
    evidence_text: str = Field(min_length=1, max_length=50000)
    source_object_type: str = Field(min_length=1, max_length=120)
    source_object_id: int = Field(gt=0)
    revision_id: int = Field(gt=0)
    extraction_run_id: int = Field(gt=0)
    source_anchors: list[BrainEvidenceAnchor] = Field(min_length=1)
    provenance: dict[str, Any] = Field(default_factory=dict)
    qualifiers: dict[str, Any] = Field(default_factory=dict)
    display_policy: str = "UNKNOWN_REQUIRES_REVIEW"
    internal_use_permission: bool = False
    language: str = "en"

    def model_post_init(self, __context: Any, /) -> None:
        if self.object_value is None and self.numeric_value is None:
            raise ValueError("CANDIDATE_VALUE_REQUIRED")


def handoff_brain_candidate(payload: BrainCandidateHandoffRequest) -> dict[str, Any]:
    repository, service = get_candidate_components()
    kind = DOMAIN_KINDS[payload.domain]
    evidence = EvidenceInput(
        source_object_type=payload.source_object_type,
        source_object_id=payload.source_object_id,
        revision_id=payload.revision_id,
        extraction_run_id=payload.extraction_run_id,
        text=payload.evidence_text,
        source_anchors=tuple(SourceAnchor(**anchor.model_dump()) for anchor in payload.source_anchors),
        display_policy=payload.display_policy,
        internal_use_permission=payload.internal_use_permission,
        language=payload.language,
        metadata={
            "reasoning_id": payload.reasoning_id,
            "source_confidence": payload.confidence,
            "provenance": payload.provenance,
            "candidate_facts": [
                {
                    "kind": kind.value,
                    "subject": payload.subject,
                    "predicate": payload.predicate,
                    "object_value": payload.object_value,
                    "numeric_value": payload.numeric_value,
                    "unit": payload.unit,
                    "qualifiers": {
                        **payload.qualifiers,
                        "reasoning_id": payload.reasoning_id,
                        "provenance": payload.provenance,
                    },
                    "confidence": payload.confidence,
                    "method": "CALYX_BRAIN_REASONING_HANDOFF_V1",
                }
            ],
        },
    )
    preview = service.preview(
        [evidence],
        {
            "adapter": "brain-candidate-handoff-004",
            "reasoning_id": payload.reasoning_id,
            "domain": payload.domain,
        },
    )
    result = service.execute(preview["candidate_run_id"])
    candidates = repository.candidates_for_run(preview["candidate_run_id"])
    return {
        "reasoning_id": payload.reasoning_id,
        "candidate_run_id": preview["candidate_run_id"],
        "state": result["state"],
        "candidate_ids": sorted(item["candidate_id"] for item in candidates),
        "review_required": True,
        "published": False,
        "graph_mutation": False,
        "scientific_publication_authority": False,
    }
