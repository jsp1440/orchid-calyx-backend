from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl, model_validator


class DossierEvidenceState(str, Enum):
    AVAILABLE = "available"
    PROVISIONAL = "provisional"
    CONFLICTING = "conflicting"
    MODELED = "modeled"
    INFERRED = "inferred"
    UNAVAILABLE = "unavailable"


class EvidenceReceipt(BaseModel):
    source_id: str
    source_name: str
    source_url: HttpUrl | None = None
    record_id: str | None = None
    retrieved_at: datetime | None = None
    license: str | None = None
    attribution: str | None = None
    evidence_state: DossierEvidenceState
    confidence: float | None = Field(default=None, ge=0, le=1)
    notes: str | None = None


class DossierSection(BaseModel):
    state: DossierEvidenceState
    summary: str | None = None
    items: list[dict[str, Any]] = Field(default_factory=list)
    receipts: list[EvidenceReceipt] = Field(default_factory=list)
    unavailable_reason: str | None = None

    @model_validator(mode="after")
    def unavailable_requires_reason(self) -> "DossierSection":
        if self.state == DossierEvidenceState.UNAVAILABLE and not self.unavailable_reason:
            raise ValueError("unavailable dossier sections require unavailable_reason")
        return self


class AtlasPoint(BaseModel):
    occurrence_id: str
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    coordinate_uncertainty_m: float | None = Field(default=None, ge=0)
    event_date: str | None = None
    country_code: str | None = None
    elevation_m: float | None = None
    evidence_state: DossierEvidenceState
    receipt: EvidenceReceipt


class AtlasLayer(BaseModel):
    layer_id: Literal[
        "occurrences",
        "countries",
        "elevation",
        "phenology",
        "habitat",
        "climate",
        "pollinators",
        "pollinator_routes",
        "mycorrhizae",
        "protected_areas",
        "threats",
        "historical_records",
    ]
    label: str
    state: DossierEvidenceState
    point_count: int | None = Field(default=None, ge=0)
    feature_count: int | None = Field(default=None, ge=0)
    points: list[AtlasPoint] = Field(default_factory=list)
    features: list[dict[str, Any]] = Field(default_factory=list)
    receipts: list[EvidenceReceipt] = Field(default_factory=list)
    unavailable_reason: str | None = None

    @model_validator(mode="after")
    def unavailable_layer_requires_reason(self) -> "AtlasLayer":
        if self.state == DossierEvidenceState.UNAVAILABLE and not self.unavailable_reason:
            raise ValueError("unavailable Atlas layers require unavailable_reason")
        return self


class SpeciesIdentity(BaseModel):
    taxon_id: str
    display_name: str
    full_scientific_name: str
    accepted_name: str
    authorship: str | None = None
    rank: str = "species"
    genus: str
    specific_epithet: str | None = None
    taxonomic_status: str | None = None
    synonyms: list[str] = Field(default_factory=list)


class PartnerPermissionSet(BaseModel):
    linking: bool = True
    indexing: bool = False
    quotation: bool = False
    images: bool = False
    trait_extraction: bool = False
    api_access: bool = False


class PartnerReference(BaseModel):
    partner_id: str
    partner_name: str
    source_url: HttpUrl
    attribution_text: str
    permissions: PartnerPermissionSet
    match_state: Literal["accepted_name", "synonym", "manual", "unresolved"]
    last_verified_at: datetime | None = None


class SpeciesAtlasEnvelope(BaseModel):
    contract_version: Literal["oc-species-atlas-v1"] = "oc-species-atlas-v1"
    taxon_id: str
    generated_at: datetime
    layers: list[AtlasLayer]
    unavailable_layers: list[str] = Field(default_factory=list)
    provenance: list[EvidenceReceipt] = Field(default_factory=list)


class SpeciesDossierEnvelope(BaseModel):
    contract_version: Literal["oc-species-dossier-v1"] = "oc-species-dossier-v1"
    generated_at: datetime
    identity: SpeciesIdentity
    nomenclature: DossierSection
    protologue: DossierSection
    type_material: DossierSection
    historical_media: DossierSection
    living_media: DossierSection
    morphology: DossierSection
    distribution: DossierSection
    ecology: DossierSection
    phenology: DossierSection
    pollinators: DossierSection
    mycorrhizae: DossierSection
    conservation: DossierSection
    literature: DossierSection
    cultivation: DossierSection
    knowledge_graph: DossierSection
    calyx_narrative: DossierSection
    research_gaps: DossierSection
    atlas: SpeciesAtlasEnvelope
    related_species: list[dict[str, Any]] = Field(default_factory=list)
    matrix_url: str
    partner_references: list[PartnerReference] = Field(default_factory=list)
    provenance: list[EvidenceReceipt] = Field(default_factory=list)


class FederationResolveRequest(BaseModel):
    name: str | None = None
    taxon_id: str | None = None
    source_url: HttpUrl | None = None
    partner_slug: str | None = None
    partner_species_slug: str | None = None

    @model_validator(mode="after")
    def at_least_one_identifier(self) -> "FederationResolveRequest":
        if not any((self.name, self.taxon_id, self.source_url, self.partner_species_slug)):
            raise ValueError("at least one species identifier is required")
        return self


class FederationResolveResult(BaseModel):
    status: Literal["resolved", "ambiguous", "unresolved", "invalid"]
    incoming_name: str | None = None
    matched_name: str | None = None
    match_state: Literal["taxon_id", "accepted_name", "synonym", "partner_slug", "none"]
    taxon_id: str | None = None
    canonical_dossier_url: str | None = None
    candidates: list[dict[str, str]] = Field(default_factory=list)
    partner_slug: str | None = None
    reciprocal_source_url: HttpUrl | None = None
    explanation: str
