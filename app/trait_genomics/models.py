from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class EvidenceKind(StrEnum):
    OBSERVED_TRAIT = "observed_trait"
    INFERRED_TRAIT = "inferred_trait"
    PREDICTED_TRAIT = "predicted_trait"
    ECOLOGICAL_INTERACTION = "ecological_interaction"
    GENETIC_ASSOCIATION = "genetic_association"
    EXPRESSION_ASSOCIATION = "expression_association"
    SELECTION_ASSOCIATION = "selection_association"
    PHYLOGENETIC_EVIDENCE = "phylogenetic_evidence"


class EvidenceRecord(BaseModel):
    evidence_id: str = Field(min_length=1)
    taxon_id: str = Field(min_length=1)
    taxon_name: str | None = None
    kind: EvidenceKind
    predicate: str = Field(min_length=1)
    value: str | float | int | bool | None = None
    unit: str | None = None
    target_taxon_id: str | None = None
    target_taxon_name: str | None = None
    gene_id: str | None = None
    protein_id: str | None = None
    sequence_accession: str | None = None
    pathway_id: str | None = None
    source_id: str = Field(min_length=1)
    source_uri: str | None = None
    evidence_text: str | None = None
    method: str | None = None
    locality: str | None = None
    life_stage: str | None = None
    organ: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    direct_observation: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiscoveryDataset(BaseModel):
    dataset_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    records: list[EvidenceRecord]
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_snapshot_ids: list[str] = Field(default_factory=list)


class DiscoveryHypothesis(BaseModel):
    hypothesis_id: str
    taxon_scope: list[str]
    trait_predicate: str
    interaction_predicate: str | None = None
    interaction_target: str | None = None
    molecular_feature: str | None = None
    support_count: int = Field(ge=0)
    independent_taxa_count: int = Field(ge=0)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[str]
    status: str = "candidate"
    causal_claim: bool = False
    rationale: str


class DiscoveryResult(BaseModel):
    dataset_id: str
    hypotheses: list[DiscoveryHypothesis]
    evidence_count: int
    trait_count: int
    interaction_count: int
    molecular_count: int
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
