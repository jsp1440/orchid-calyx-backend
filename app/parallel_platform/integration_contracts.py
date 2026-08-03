from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class MatrixNeighborDimensionInput(BaseModel):
    availability: str = "unavailable"
    score: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)
    provenance: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class MatrixNeighborCandidateInput(BaseModel):
    taxon_id: str = Field(min_length=1)
    accepted_name: str = Field(min_length=1)
    dimensions: dict[str, MatrixNeighborDimensionInput] = Field(default_factory=dict)


class MatrixNeighborhoodRequest(BaseModel):
    subject_taxon_id: str = Field(min_length=1)
    candidates: list[MatrixNeighborCandidateInput] = Field(default_factory=list)
    weights: dict[str, float] = Field(default_factory=dict)
    limit: int = Field(default=20, ge=1, le=100)


class IdentificationObservationInput(BaseModel):
    character: str = Field(min_length=1)
    state: str
    value: Any = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    source_media_ids: list[str] = Field(default_factory=list)
    notes: str | None = None


class IdentificationSessionCandidateInput(BaseModel):
    taxon_id: str = Field(min_length=1)
    scientific_name: str = Field(min_length=1)
    features: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)


class IdentificationSessionRequest(BaseModel):
    observation_id: str = Field(min_length=1)
    observations: list[IdentificationObservationInput] = Field(default_factory=list)
    candidates: list[IdentificationSessionCandidateInput] = Field(default_factory=list)
    provenance: list[str] = Field(default_factory=list)


class HomepageFeatureCandidateInput(BaseModel):
    taxon_id: str = Field(min_length=1)
    scientific_name: str = Field(min_length=1)
    content_score: float = Field(ge=0, le=1)
    source: str = Field(min_length=1)
    image_url: str | None = None
    image_license: str | None = None
    image_attribution: str | None = None
    image_kind: str | None = None
    freshness_at: str | None = None
    evidence: list[str] = Field(default_factory=list)


class HomepageSelectionRequest(BaseModel):
    feature_type: str
    candidates: list[HomepageFeatureCandidateInput] = Field(default_factory=list)
