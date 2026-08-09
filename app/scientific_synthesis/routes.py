from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .models import (
    ArticleDraft,
    ArticleSentence,
    BibliographicRecord,
    ClaimKind,
    EvidenceAnchor,
    EvidenceClass,
    EvidenceMatrixRow,
    SynthesisClaim,
    VerificationState,
)
from .service import ScientificSynthesisService


SERVICE = ScientificSynthesisService()
router = APIRouter(prefix="/synthesis", tags=["scientific-synthesis"])


class BibliographicRecordIn(BaseModel):
    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    authors: list[str] = Field(min_length=1)
    year: int | None = None
    journal: str | None = None
    doi: str | None = None
    verification_state: VerificationState
    verification_provider: str | None = None
    verification_identifier: str | None = None


class EvidenceAnchorIn(BaseModel):
    anchor_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_revision_id: str = Field(min_length=1)
    locator: dict[str, Any]
    content_hash: str = Field(min_length=1)
    excerpt_hash: str = Field(min_length=1)


class EvidenceRowIn(BaseModel):
    evidence_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    evidence_class: EvidenceClass
    anchors: list[EvidenceAnchorIn] = Field(min_length=1)
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


class ClaimIn(BaseModel):
    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    kind: ClaimKind
    supporting_evidence_ids: list[str] = Field(min_length=1)
    conflicting_evidence_ids: list[str] = []
    inference_rationale: str | None = None


class ArticleSentenceIn(BaseModel):
    sentence_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    scientific: bool
    claim_ids: list[str] = []


class ArticleDraftIn(BaseModel):
    article_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    sentences: list[ArticleSentenceIn] = Field(min_length=1)
    audience: str = Field(min_length=1)
    format: str = Field(min_length=1)
    bibliography_source_ids: list[str]


class SynthesisValidationIn(BaseModel):
    bibliography: list[BibliographicRecordIn]
    evidence_rows: list[EvidenceRowIn]
    claims: list[ClaimIn]
    article: ArticleDraftIn


@router.post("/validate")
def validate_synthesis(payload: SynthesisValidationIn):
    bibliography = tuple(
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
        for value in payload.bibliography
    )
    evidence_rows = tuple(
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
        for value in payload.evidence_rows
    )
    claims = tuple(
        SynthesisClaim(
            claim_id=value.claim_id,
            text=value.text,
            kind=value.kind,
            supporting_evidence_ids=tuple(value.supporting_evidence_ids),
            conflicting_evidence_ids=tuple(value.conflicting_evidence_ids),
            inference_rationale=value.inference_rationale,
        )
        for value in payload.claims
    )
    article = ArticleDraft(
        article_id=payload.article.article_id,
        title=payload.article.title,
        sentences=tuple(
            ArticleSentence(
                sentence_id=value.sentence_id,
                text=value.text,
                scientific=value.scientific,
                claim_ids=tuple(value.claim_ids),
            )
            for value in payload.article.sentences
        ),
        audience=payload.article.audience,
        format=payload.article.format,
        bibliography_source_ids=tuple(payload.article.bibliography_source_ids),
    )
    return SERVICE.validate(
        bibliography=bibliography,
        evidence_rows=evidence_rows,
        claims=claims,
        article=article,
    )


@router.get("/health")
def health():
    return {
        "status": "ok",
        "validator_version": "CALYX-SYN-001",
        "generates_prose": False,
        "requires_claim_grounding": True,
        "requires_verified_article_sources": True,
        "publishes_knowledge": False,
    }
