from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def stable_checksum(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# BUILD-KE-305 — integrated multimedia glossary cards
class GlossaryMedia(StrictModel):
    media_id: str
    media_type: Literal["photograph", "illustration", "diagram", "animation"]
    source_uri: str
    license: str
    alt_text: str
    evidence_ids: list[str] = Field(min_length=1)


class GlossaryCard(StrictModel):
    concept_id: str
    label: str
    compact_definition: str
    expanded_definition: str
    synonym_labels: list[str] = Field(default_factory=list)
    related_concept_ids: list[str] = Field(default_factory=list)
    media: list[GlossaryMedia] = Field(default_factory=list)
    evidence_ids: list[str] = Field(min_length=1)
    status: Literal["candidate"] = "candidate"
    checksum: str


def build_glossary_card(
    concept_id: str,
    label: str,
    compact_definition: str,
    expanded_definition: str,
    synonym_labels: list[str],
    related_concept_ids: list[str],
    media: list[GlossaryMedia],
    evidence_ids: list[str],
) -> GlossaryCard:
    if not compact_definition.strip() or not expanded_definition.strip():
        raise ValueError("glossary cards require compact and expanded definitions")
    media_ids = [item.media_id for item in media]
    if len(media_ids) != len(set(media_ids)):
        raise ValueError("duplicate glossary media IDs")
    canonical = {
        "concept_id": concept_id,
        "label": label,
        "compact_definition": compact_definition,
        "expanded_definition": expanded_definition,
        "synonyms": sorted(set(synonym_labels)),
        "related": sorted(set(related_concept_ids)),
        "media": [item.model_dump(mode="json") for item in sorted(media, key=lambda item: item.media_id)],
        "evidence_ids": sorted(set(evidence_ids)),
    }
    return GlossaryCard(
        concept_id=concept_id,
        label=label,
        compact_definition=compact_definition,
        expanded_definition=expanded_definition,
        synonym_labels=canonical["synonyms"],
        related_concept_ids=canonical["related"],
        media=sorted(media, key=lambda item: item.media_id),
        evidence_ids=canonical["evidence_ids"],
        checksum=stable_checksum(canonical),
    )


# BUILD-ATLAS-406 — conservation prioritization candidates
class ConservationFactor(StrictModel):
    factor_id: str
    normalized_score: float = Field(ge=0, le=1)
    weight: float = Field(gt=0)
    evidence_id: str


class ConservationPriority(StrictModel):
    target_id: str
    priority_score: float = Field(ge=0, le=1)
    evidence_ids: list[str]
    factor_ids: list[str]
    status: Literal["candidate"] = "candidate"


def calculate_conservation_priority(target_id: str, factors: list[ConservationFactor]) -> ConservationPriority:
    if not factors:
        raise ValueError("conservation priority requires at least one factor")
    denominator = sum(item.weight for item in factors)
    score = sum(item.normalized_score * item.weight for item in factors) / denominator
    return ConservationPriority(
        target_id=target_id,
        priority_score=round(score, 8),
        evidence_ids=sorted({item.evidence_id for item in factors}),
        factor_ids=sorted(item.factor_id for item in factors),
    )


# BUILD-RS-503 — reproducible analysis manifests
class AnalysisInput(StrictModel):
    artifact_id: str
    checksum: str = Field(min_length=64, max_length=64)


class AnalysisManifest(StrictModel):
    analysis_id: str
    code_reference: str
    environment_reference: str
    inputs: list[AnalysisInput] = Field(min_length=1)
    parameters: dict[str, object]
    checksum: str
    execution_enabled: bool = False


def build_analysis_manifest(
    analysis_id: str,
    code_reference: str,
    environment_reference: str,
    inputs: list[AnalysisInput],
    parameters: dict[str, object],
) -> AnalysisManifest:
    ids = [item.artifact_id for item in inputs]
    if len(ids) != len(set(ids)):
        raise ValueError("analysis inputs must have unique artifact IDs")
    ordered = sorted(inputs, key=lambda item: item.artifact_id)
    canonical = {
        "analysis_id": analysis_id,
        "code_reference": code_reference,
        "environment_reference": environment_reference,
        "inputs": [item.model_dump(mode="json") for item in ordered],
        "parameters": parameters,
    }
    return AnalysisManifest(
        analysis_id=analysis_id,
        code_reference=code_reference,
        environment_reference=environment_reference,
        inputs=ordered,
        parameters=parameters,
        checksum=stable_checksum(canonical),
    )


# BUILD-CON-603 — QR label print jobs
class LabelRecord(StrictModel):
    specimen_id: str
    accession_number: str
    display_name: str
    qr_payload: str


class LabelPrintJob(StrictModel):
    job_id: str
    labels: list[LabelRecord] = Field(min_length=1)
    template_id: str
    checksum: str
    status: Literal["staged"] = "staged"


def stage_label_print_job(job_id: str, labels: list[LabelRecord], template_id: str) -> LabelPrintJob:
    specimen_ids = [item.specimen_id for item in labels]
    if len(specimen_ids) != len(set(specimen_ids)):
        raise ValueError("label print jobs cannot contain duplicate specimens")
    ordered = sorted(labels, key=lambda item: (item.accession_number, item.specimen_id))
    checksum = stable_checksum({
        "job_id": job_id,
        "template_id": template_id,
        "labels": [item.model_dump(mode="json") for item in ordered],
    })
    return LabelPrintJob(job_id=job_id, labels=ordered, template_id=template_id, checksum=checksum)


# BUILD-MATRIX-703 — interactive candidate elimination
class CandidateProfile(StrictModel):
    taxon_id: str
    states: dict[str, set[str]]


def eliminate_candidates(
    candidates: list[CandidateProfile],
    observations: dict[str, str],
) -> tuple[list[str], dict[str, list[str]]]:
    remaining: list[str] = []
    eliminated: dict[str, list[str]] = {}
    for candidate in sorted(candidates, key=lambda item: item.taxon_id):
        conflicts: list[str] = []
        for character_id, observed_state in sorted(observations.items()):
            allowed = candidate.states.get(character_id)
            if allowed is not None and observed_state not in allowed:
                conflicts.append(character_id)
        if conflicts:
            eliminated[candidate.taxon_id] = conflicts
        else:
            remaining.append(candidate.taxon_id)
    return remaining, eliminated


# BUILD-VISION-803 — morphology extraction candidates
class MorphologyCandidate(StrictModel):
    observation_id: str
    image_id: str
    structure: str
    character_id: str
    proposed_state: str
    confidence: float = Field(ge=0, le=1)
    evidence_region_id: str
    status: Literal["candidate"] = "candidate"


def build_morphology_candidates(items: list[MorphologyCandidate]) -> list[MorphologyCandidate]:
    ids = [item.observation_id for item in items]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate morphology observation IDs")
    return sorted(items, key=lambda item: (-item.confidence, item.observation_id))


# BUILD-PUB-903 — reusable evidence-backed report templates
class TemplateSection(StrictModel):
    section_id: str
    title: str
    required_evidence_classes: list[str] = Field(min_length=1)


class PublicationTemplate(StrictModel):
    template_id: str
    title: str
    section_order: list[str]
    sections: list[TemplateSection]
    checksum: str
    publication_enabled: bool = False


def build_publication_template(template_id: str, title: str, sections: list[TemplateSection]) -> PublicationTemplate:
    ids = [item.section_id for item in sections]
    if not sections or len(ids) != len(set(ids)):
        raise ValueError("publication template sections must be unique and non-empty")
    ordered = list(sections)
    checksum = stable_checksum([item.model_dump(mode="json") for item in ordered])
    return PublicationTemplate(
        template_id=template_id,
        title=title,
        section_order=[item.section_id for item in ordered],
        sections=ordered,
        checksum=checksum,
    )


# BUILD-INT-954 — dead-letter event handling
class DeadLetterRecord(StrictModel):
    dead_letter_id: str
    event_id: str
    event_type: str
    reason: str
    payload_checksum: str = Field(min_length=64, max_length=64)
    recorded_at: datetime
    status: Literal["open", "resolved"] = "open"


class DeadLetterQueue:
    def __init__(self) -> None:
        self._records: dict[str, DeadLetterRecord] = {}

    def record(self, event_id: str, event_type: str, reason: str, payload: dict[str, object], recorded_at: datetime) -> DeadLetterRecord:
        if recorded_at.tzinfo is None:
            raise ValueError("dead-letter timestamps must be timezone-aware")
        payload_checksum = stable_checksum(payload)
        dead_letter_id = f"dead-letter:{stable_checksum([event_id, event_type, payload_checksum])[:24]}"
        candidate = DeadLetterRecord(
            dead_letter_id=dead_letter_id,
            event_id=event_id,
            event_type=event_type,
            reason=reason,
            payload_checksum=payload_checksum,
            recorded_at=recorded_at,
        )
        existing = self._records.get(dead_letter_id)
        if existing and existing != candidate:
            raise ValueError("conflicting dead-letter identity")
        self._records[dead_letter_id] = candidate
        return candidate

    def open_records(self) -> list[DeadLetterRecord]:
        return sorted(
            [item for item in self._records.values() if item.status == "open"],
            key=lambda item: item.dead_letter_id,
        )


# BUILD-MC-204 — approval dashboard projection
class ApprovalQueueItem(StrictModel):
    item_id: str
    architecture_id: str
    review_classes: list[str] = Field(min_length=1)
    completed_review_classes: list[str] = Field(default_factory=list)


class ApprovalProjection(StrictModel):
    ready_ids: list[str]
    waiting_ids: list[str]
    missing_reviews: dict[str, list[str]]


def project_approvals(items: list[ApprovalQueueItem]) -> ApprovalProjection:
    ready: list[str] = []
    waiting: list[str] = []
    missing: dict[str, list[str]] = {}
    for item in sorted(items, key=lambda entry: entry.item_id):
        required = set(item.review_classes)
        completed = set(item.completed_review_classes)
        unresolved = sorted(required - completed)
        if unresolved:
            waiting.append(item.item_id)
            missing[item.item_id] = unresolved
        else:
            ready.append(item.item_id)
    return ApprovalProjection(ready_ids=ready, waiting_ids=waiting, missing_reviews=missing)


# BUILD-BRAIN-116 — semantic discovery index manifests
class DiscoveryDocument(StrictModel):
    object_id: str
    title: str
    text: str
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    source_uri: str


class DiscoveryIndexManifest(StrictModel):
    index_id: str
    document_ids: list[str]
    documents: list[DiscoveryDocument]
    checksum: str
    provider_enabled: bool = False


def build_discovery_index_manifest(index_id: str, documents: list[DiscoveryDocument]) -> DiscoveryIndexManifest:
    ids = [item.object_id for item in documents]
    if not documents or len(ids) != len(set(ids)):
        raise ValueError("discovery documents must be unique and non-empty")
    ordered = sorted(documents, key=lambda item: item.object_id)
    checksum = stable_checksum([item.model_dump(mode="json") for item in ordered])
    return DiscoveryIndexManifest(
        index_id=index_id,
        document_ids=[item.object_id for item in ordered],
        documents=ordered,
        checksum=checksum,
    )
