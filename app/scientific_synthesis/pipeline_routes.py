from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .models import (
    BibliographicRecord,
    EvidenceAnchor,
    EvidenceClass,
    EvidenceMatrixRow,
    VerificationState,
)
from .pipeline import (
    EvidenceClassificationDecision,
    ResearchToArticleMissionService,
)

SERVICE = ResearchToArticleMissionService()
router = APIRouter(prefix="/research-article", tags=["scientific-synthesis"])


class BibliographyIn(BaseModel):
    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    authors: list[str] = Field(min_length=1)
    year: int | None = None
    journal: str | None = None
    doi: str | None = None
    verification_state: VerificationState
    verification_provider: str | None = None
    verification_identifier: str | None = None


class AnchorIn(BaseModel):
    anchor_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_revision_id: str = Field(min_length=1)
    locator: dict[str, Any]
    content_hash: str = Field(min_length=1)
    excerpt_hash: str = Field(min_length=1)


class EvidenceIn(BaseModel):
    evidence_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    evidence_class: EvidenceClass
    anchors: list[AnchorIn] = Field(min_length=1)
    taxon: str | None = None
    intervention: str | None = None
    comparator: str | None = None
    outcome: str | None = None
    method: str | None = None
    result: str | None = None
    sample_size: str | None = None
    uncertainty: str | None = None
    limitations: list[str] = []
    metadata: dict[str, Any] = {}


class ClassificationIn(BaseModel):
    evidence_id: str = Field(min_length=1)
    evidence_class: EvidenceClass
    reviewer_id: str = Field(min_length=1)
    rationale: str = Field(min_length=1)


class ResearchArticleIn(BaseModel):
    question: str = Field(min_length=1)
    title: str = Field(min_length=1)
    audience: str = Field(min_length=1)
    format: str = Field(min_length=1)
    bibliography: list[BibliographyIn] = Field(min_length=1)
    evidence_rows: list[EvidenceIn] = Field(min_length=1)
    classification_decisions: list[ClassificationIn] = []


def _bibliography(values: list[BibliographyIn]) -> tuple[BibliographicRecord, ...]:
    return tuple(
        BibliographicRecord(
            source_id=value.source_id,
            title=value.title,
            authors=tuple(value.authors),
            year=value.year,
            journal=value.journal,
            doi=value.doi,
            verification_state=value.verification_state,
            verification_provider=value.verification_provider,
            verification_identifier=value.verification_identifier,
        )
        for value in values
    )


def _evidence(values: list[EvidenceIn]) -> tuple[EvidenceMatrixRow, ...]:
    return tuple(
        EvidenceMatrixRow(
            evidence_id=value.evidence_id,
            source_id=value.source_id,
            evidence_class=value.evidence_class,
            anchors=tuple(EvidenceAnchor(**anchor.model_dump()) for anchor in value.anchors),
            taxon=value.taxon,
            intervention=value.intervention,
            comparator=value.comparator,
            outcome=value.outcome,
            method=value.method,
            result=value.result,
            sample_size=value.sample_size,
            uncertainty=value.uncertainty,
            limitations=tuple(value.limitations),
            metadata=value.metadata,
        )
        for value in values
    )


@router.post("/run")
def run_research_article(payload: ResearchArticleIn):
    try:
        return SERVICE.run(
            question=payload.question,
            title=payload.title,
            audience=payload.audience,
            format=payload.format,
            bibliography=_bibliography(payload.bibliography),
            evidence_rows=_evidence(payload.evidence_rows),
            classification_decisions=tuple(
                EvidenceClassificationDecision(**value.model_dump())
                for value in payload.classification_decisions
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc


@router.get("/health")
def health():
    return {
        "status": "ok",
        "cross_study_synthesis": True,
        "grounded_authoring": True,
        "quantitative_audit": True,
        "figure_evidence_briefs": True,
        "human_review_required": True,
        "publishes_knowledge": False,
    }
