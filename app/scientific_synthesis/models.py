from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EvidenceClass(str, Enum):
    DIRECT_TRACER = "DIRECT_TRACER"
    CONTROLLED_EXPERIMENT = "CONTROLLED_EXPERIMENT"
    OBSERVATIONAL = "OBSERVATIONAL"
    EXPERT_PRACTICE = "EXPERT_PRACTICE"
    COMMERCIAL_CLAIM = "COMMERCIAL_CLAIM"
    MECHANISTIC_INFERENCE = "MECHANISTIC_INFERENCE"


class VerificationState(str, Enum):
    VERIFIED_AUTHORITY = "VERIFIED_AUTHORITY"
    VERIFIED_PUBLISHER = "VERIFIED_PUBLISHER"
    UNVERIFIED = "UNVERIFIED"


class ClaimKind(str, Enum):
    DIRECT = "DIRECT"
    SYNTHESIS = "SYNTHESIS"
    INFERENCE = "INFERENCE"


@dataclass(frozen=True)
class BibliographicRecord:
    source_id: str
    title: str
    authors: tuple[str, ...]
    year: int | None
    journal: str | None
    doi: str | None
    verification_state: VerificationState
    verification_provider: str | None = None
    verification_identifier: str | None = None


@dataclass(frozen=True)
class EvidenceAnchor:
    anchor_id: str
    source_id: str
    source_revision_id: str
    locator: dict[str, Any]
    content_hash: str
    excerpt_hash: str


@dataclass(frozen=True)
class EvidenceMatrixRow:
    evidence_id: str
    source_id: str
    evidence_class: EvidenceClass
    anchors: tuple[EvidenceAnchor, ...]
    taxon: str | None = None
    intervention: str | None = None
    comparator: str | None = None
    outcome: str | None = None
    method: str | None = None
    result: str | None = None
    sample_size: str | None = None
    uncertainty: str | None = None
    limitations: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SynthesisClaim:
    claim_id: str
    text: str
    kind: ClaimKind
    supporting_evidence_ids: tuple[str, ...]
    conflicting_evidence_ids: tuple[str, ...] = ()
    inference_rationale: str | None = None


@dataclass(frozen=True)
class ArticleSentence:
    sentence_id: str
    text: str
    scientific: bool
    claim_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ArticleDraft:
    article_id: str
    title: str
    sentences: tuple[ArticleSentence, ...]
    audience: str
    format: str
    bibliography_source_ids: tuple[str, ...]
