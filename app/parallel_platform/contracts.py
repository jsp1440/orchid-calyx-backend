from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

CONTRACT_VERSION = "oc-parallel-v1"
MATRIX_DIMENSIONS = (
    "taxonomy",
    "morphology",
    "ecology",
    "geography",
    "phenology",
    "pollinator",
    "mycorrhiza",
    "conservation",
    "cultivation",
    "literature",
    "knowledge_graph",
)


class MatrixDimensionInput(BaseModel):
    available: bool = True
    score: float | None = Field(default=None, ge=0, le=1)
    weight: float = Field(default=1, ge=0)
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: list[str] = Field(default_factory=list)


class MatrixRequest(BaseModel):
    subject_taxon_id: str = Field(min_length=1)
    object_taxon_id: str = Field(min_length=1)
    dimensions: dict[str, MatrixDimensionInput] = Field(default_factory=dict)


class IdentificationCandidateInput(BaseModel):
    taxon_id: str = Field(min_length=1)
    scientific_name: str = Field(min_length=1)
    features: dict[str, Any] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list)


class IdentificationRequest(BaseModel):
    observation_id: str = Field(min_length=1)
    features: dict[str, Any] = Field(default_factory=dict)
    candidates: list[IdentificationCandidateInput] = Field(default_factory=list)


class BrainRecommendation(BaseModel):
    recommendation_id: str
    domain: Literal["homepage", "education", "design", "matrix", "identification"]
    status: Literal["proposed", "review_required", "approved", "rejected"] = "proposed"
    summary: str
    evidence: list[str] = Field(default_factory=list)
    implementation_spec: dict[str, Any] = Field(default_factory=dict)
    automatic_implementation: bool = False
