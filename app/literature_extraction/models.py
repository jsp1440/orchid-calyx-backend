from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Identifier(StrictModel):
    scheme: Literal["doi", "pmid", "isbn", "uri", "local", "other"]
    value: str = Field(min_length=1)


class SourceSpan(StrictModel):
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    section_id: str | None = None
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)


class Provenance(StrictModel):
    method: Literal[
        "source_reported",
        "rule_extracted",
        "model_extracted",
        "human_annotated",
        "inferred",
        "imported",
    ]
    confidence: float = Field(ge=0, le=1)
    extractor: str | None = None
    extractor_version: str | None = None
    review_status: Literal["unreviewed", "accepted", "corrected", "rejected"] = "unreviewed"
    reviewer_note: str | None = None


class SourceDocument(StrictModel):
    content_hash: str = Field(min_length=16)
    media_type: str
    original_filename: str = Field(min_length=1)
    storage_uri: str | None = None
    ingested_at: datetime | None = None
    ocr_applied: bool = False
    language: str | None = None


class PaperMetadata(StrictModel):
    title: str | None = None
    subtitle: str | None = None
    authors: list[str] = Field(default_factory=list)
    journal: str | None = None
    publisher: str | None = None
    publication_year: int | None = Field(default=None, ge=1500, le=3000)
    volume: str | None = None
    issue: str | None = None
    pages: str | None = None
    abstract: str | None = None
    identifiers: list[Identifier] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)


class Section(StrictModel):
    section_id: str
    heading: str | None = None
    canonical_type: Literal[
        "title",
        "abstract",
        "introduction",
        "methods",
        "results",
        "discussion",
        "conclusion",
        "acknowledgements",
        "references",
        "supplement",
        "other",
    ] = "other"
    text: str
    order: int = Field(ge=0)
    span: SourceSpan = Field(default_factory=SourceSpan)


class Entity(StrictModel):
    entity_id: str
    entity_type: Literal[
        "taxon",
        "person",
        "institution",
        "location",
        "habitat",
        "anatomical_structure",
        "trait",
        "method",
        "chemical",
        "environmental_factor",
        "other",
    ]
    name: str
    normalized_name: str | None = None
    external_ids: list[Identifier] = Field(default_factory=list)
    mentions: list[SourceSpan] = Field(default_factory=list)
    attributes: dict[str, Any] = Field(default_factory=dict)
    provenance: Provenance


class GlossaryTerm(StrictModel):
    term_id: str
    term: str
    normalized_term: str | None = None
    status: Literal["matched", "candidate", "new", "ambiguous"]
    glossary_entry_id: str | None = None
    senses: list[str] = Field(default_factory=list)
    mentions: list[SourceSpan] = Field(default_factory=list)
    provenance: Provenance


class Measurement(StrictModel):
    measurement_id: str
    subject_id: str
    property: str
    value: float | None = None
    value_text: str
    unit: str | None = None
    qualifier: str | None = None
    sample_size: int | None = Field(default=None, ge=0)
    evidence_ids: list[str] = Field(default_factory=list)
    provenance: Provenance


class Claim(StrictModel):
    claim_id: str
    statement: str
    claim_type: Literal[
        "observation",
        "result",
        "interpretation",
        "hypothesis",
        "methodological",
        "background",
        "limitation",
        "recommendation",
    ]
    subject_ids: list[str] = Field(default_factory=list)
    predicate: str | None = None
    object_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    polarity: Literal["positive", "negative", "mixed", "uncertain"] = "uncertain"
    provenance: Provenance


class Evidence(StrictModel):
    evidence_id: str
    excerpt: str
    span: SourceSpan
    evidence_type: Literal["text", "table", "figure", "caption", "reference", "supplement"]
    supports_ids: list[str] = Field(default_factory=list)
    contradicts_ids: list[str] = Field(default_factory=list)


class NormalizedEvidenceRecord(StrictModel):
    record_id: str
    source_claim_id: str
    evidence_ids: list[str] = Field(default_factory=list)
    statement: str
    normalized_statement: str
    domain: Literal[
        "taxonomy",
        "trait",
        "occurrence",
        "habitat",
        "ecological_interaction",
        "conservation",
        "cultivation",
        "other",
    ]
    polarity: Literal["positive", "negative", "mixed", "uncertain"] = "uncertain"
    canonical_entity_ids: list[str] = Field(default_factory=list)
    unresolved_entities: list[str] = Field(default_factory=list)
    extraction_confidence: float = Field(ge=0, le=1)
    normalization_confidence: float = Field(ge=0, le=1)
    review_status: Literal["unreviewed", "accepted", "corrected", "rejected"] = "unreviewed"
    validation_notes: list[str] = Field(default_factory=list)
    source_excerpts: list[str] = Field(default_factory=list)
    reconciliation_group_id: str | None = None
    provenance: Provenance


class ReconciliationRelation(StrictModel):
    relation_id: str
    subject_record_id: str
    object_record_id: str
    relation_type: Literal["duplicate", "supports", "potential_contradiction"]
    reason: str


class ReviewItem(StrictModel):
    review_item_id: str
    source_record_id: str
    reconciliation_group_id: str | None = None
    priority: int = Field(ge=0)
    priority_reasons: list[Literal[
        "unresolved_entities",
        "potential_contradiction",
        "low_normalization_confidence",
        "duplicate_group",
        "standard_review",
    ]] = Field(default_factory=list)
    source_record_fingerprint: str
    status: Literal["pending", "decided"] = "pending"


class ReviewDecision(StrictModel):
    decision_id: str
    review_item_id: str
    decision: Literal[
        "accept",
        "accept_with_corrections",
        "reject",
        "defer",
        "needs_expert_review",
    ]
    reviewer_id: str = Field(min_length=1)
    decided_at: datetime
    reason_codes: list[str] = Field(default_factory=list)
    notes: str | None = None
    corrections: dict[str, Any] = Field(default_factory=dict)
    source_record_fingerprint: str


class PublicationDecision(StrictModel):
    publication_decision_id: str
    review_item_id: str
    source_record_id: str
    status: Literal[
        "eligible_for_publication",
        "blocked",
        "deferred",
        "rejected",
    ]
    reason_codes: list[str] = Field(default_factory=list)
    based_on_decision_id: str | None = None


class Relationship(StrictModel):
    relationship_id: str
    subject_id: str
    predicate: str
    object_id: str
    qualifiers: dict[str, Any] = Field(default_factory=dict)
    evidence_ids: list[str] = Field(default_factory=list)
    provenance: Provenance


class Figure(StrictModel):
    figure_id: str
    label: str | None = None
    caption: str | None = None
    page: int | None = Field(default=None, ge=1)
    asset_uri: str | None = None
    entity_ids: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class Table(StrictModel):
    table_id: str
    label: str | None = None
    caption: str | None = None
    page: int | None = Field(default=None, ge=1)
    columns: list[str] = Field(default_factory=list)
    rows: list[list[str | float | int | bool | None]] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class Reference(StrictModel):
    reference_id: str
    raw_citation: str
    title: str | None = None
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    identifiers: list[Identifier] = Field(default_factory=list)
    resolved: bool = False


class UnknownTerm(StrictModel):
    unknown_term_id: str
    text: str
    context: str
    suggested_category: str
    span: SourceSpan = Field(default_factory=SourceSpan)
    provenance: Provenance


class ExtractorRun(StrictModel):
    name: str
    version: str
    status: Literal["pending", "running", "completed", "failed", "skipped"]
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None
    output_count: int = Field(default=0, ge=0)


class AnalysisManifest(StrictModel):
    analysis_id: str
    analysis_version: int = Field(ge=1)
    previous_analysis_id: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    pipeline_version: str
    schema_version: Literal["1.0.0"] = "1.0.0"
    ocr_engine: str | None = None
    ocr_version: str | None = None
    glossary_version: str | None = None
    ontology_version: str | None = None
    relationship_model_version: str | None = None
    model_provider: str | None = None
    model_name: str | None = None
    prompt_bundle_version: str | None = None
    extractors: list[ExtractorRun] = Field(default_factory=list)
    status: Literal["pending", "running", "completed", "completed_with_warnings", "failed"]
    warnings: list[str] = Field(default_factory=list)
    input_fingerprint: str | None = None
    configuration_fingerprint: str | None = None


class PaperKnowledge(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    paper_id: str = Field(min_length=1)
    source: SourceDocument
    metadata: PaperMetadata
    sections: list[Section] = Field(default_factory=list)
    entities: list[Entity] = Field(default_factory=list)
    glossary_terms: list[GlossaryTerm] = Field(default_factory=list)
    measurements: list[Measurement] = Field(default_factory=list)
    claims: list[Claim] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    normalized_evidence_records: list[NormalizedEvidenceRecord] = Field(default_factory=list)
    reconciliation_relations: list[ReconciliationRelation] = Field(default_factory=list)
    review_items: list[ReviewItem] = Field(default_factory=list)
    review_decisions: list[ReviewDecision] = Field(default_factory=list)
    publication_decisions: list[PublicationDecision] = Field(default_factory=list)
    relationships: list[Relationship] = Field(default_factory=list)
    figures: list[Figure] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)
    references: list[Reference] = Field(default_factory=list)
    unknown_terms: list[UnknownTerm] = Field(default_factory=list)
    analysis_manifest: AnalysisManifest
