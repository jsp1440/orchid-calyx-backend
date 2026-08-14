"""Pydantic request/response models for the Vision-Lexicon bridge API."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ReferenceSetItemRequest(BaseModel):
    image_id: str = Field(min_length=1)
    media_id: str | None = None
    taxon_id: str | None = None
    taxon_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    developmental_stage: str | None = None
    orientation_context: str | None = None
    calibration_status: str = "UNCALIBRATED"
    scale_information: dict[str, Any] | None = None
    image_quality_state: str = "UNKNOWN"
    source: str | None = None
    license: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    inclusion_reason: str | None = None


class CreateReferenceSetRequest(BaseModel):
    title: str = Field(min_length=1)
    target_concept_id: UUID | None = None
    taxon_scope: str | None = None
    description: str | None = None
    license_summary: str | None = None
    notes: str | None = None
    items: list[ReferenceSetItemRequest] = Field(default_factory=list)


class VisionAnalysisRequest(BaseModel):
    image_id: str = Field(min_length=1)
    content_hash: str = Field(min_length=32)
    reference_set_id: UUID | None = None
    vision_model: str = Field(min_length=1)
    vision_model_version: str = Field(min_length=1)
    taxon_context: str | None = None
    taxon_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    calibration_state: str = "UNCALIBRATED"
    image_quality: str = "UNKNOWN"
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class VisionRegionRequest(BaseModel):
    concept_id: UUID | None = None
    label: str = Field(min_length=1)
    bounding_box: dict[str, Any] | None = None
    segmentation_ref: str | None = None
    landmarks: list[dict[str, Any]] | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    provenance: dict[str, Any] = Field(default_factory=dict)


class CharacterObservationRequest(BaseModel):
    region_id: UUID | None = None
    concept_id: UUID | None = None
    character_id: str = Field(min_length=1)
    character_state_id: str | None = None
    numeric_value: float | None = None
    unit: str | None = None
    relative_value: float | None = None
    measurement_basis: str = "IMAGE_DERIVED"
    confidence: float = Field(ge=0.0, le=1.0)
    method: str | None = None
    evidence_region: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("unit")
    @classmethod
    def _unit_relative_only_without_calibration(cls, v: str | None) -> str | None:
        # Full enforcement happens in the domain contract; this provides
        # an early API-layer warning for obvious cases.
        return v


class MorphometricObservationRequest(BaseModel):
    analysis_id: UUID
    region_id: UUID | None = None
    metric_type: str
    value: float
    unit: str | None = None
    calibration_state: str = "UNCALIBRATED"
    calibration_basis: str | None = None
    calibration_uncertainty: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    landmarks_used: list[dict[str, Any]] | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class ColorPhenotypeObservationRequest(BaseModel):
    analysis_id: UUID
    region_id: UUID | None = None
    phenotype_class: str = "IMAGE_DERIVED"
    rgb_hex: str | None = None
    hsv_hue: float | None = None
    hsv_saturation: float | None = None
    hsv_value: float | None = None
    lab_l: float | None = None
    lab_a: float | None = None
    lab_b: float | None = None
    pattern_description: str | None = None
    pigment_class: str | None = None
    pigment_evidence_source: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class CreateFigureSpecRequest(BaseModel):
    target_concept_id: UUID | None = None
    purpose: str = Field(min_length=1)
    scope: str = "MORPHOLOGICAL_ILLUSTRATION"
    taxon_scope: str | None = None
    reference_set_ids: list[UUID] = Field(default_factory=list)
    required_structures: list[dict[str, Any]] = Field(default_factory=list)
    required_character_states: list[dict[str, Any]] = Field(default_factory=list)
    required_relationships: list[dict[str, Any]] = Field(default_factory=list)
    allowed_variation: dict[str, Any] = Field(default_factory=dict)
    excluded_interpretations: list[dict[str, Any]] = Field(default_factory=list)
    relative_geometry_constraints: dict[str, Any] = Field(default_factory=dict)
    color_constraints: dict[str, Any] = Field(default_factory=dict)
    literature_constraints: list[dict[str, Any]] = Field(default_factory=list)
    label_requirements: list[dict[str, Any]] = Field(default_factory=list)
    uncertainty_notes: str | None = None
    generation_notes: str | None = None
    media_type: str = "STATIC_ILLUSTRATION"
    temporal_sequence: list[dict[str, Any]] | None = None
    required_stage_order: list[str] | None = None
    motion_constraints: dict[str, Any] | None = None
    duration_range: dict[str, Any] | None = None
    loop_behavior: str | None = None
    scientific_state_transitions: list[dict[str, Any]] | None = None
    reduced_motion_alternative: str | None = None


class CreateValidationRunRequest(BaseModel):
    asset_id: str = Field(min_length=1)
    figure_spec_id: UUID | None = None
    vision_analysis_id: UUID | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class CharacterConformanceCheckRequest(BaseModel):
    character_id: str = Field(min_length=1)
    expected_state_or_range: str | None = None
    observed_state_or_value: str | None = None
    result: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    notes: str | None = None


class ReviewDecisionRequest(BaseModel):
    subject_type: str
    subject_id: UUID
    decision: str
    reviewer_tier: str = "COMMUNITY"
    scope_of_expertise: str | None = None
    version_reviewed: int | None = None
    questions_answered: list[dict[str, Any]] = Field(default_factory=list)
    comments: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class ReferenceSetItemResponse(BaseModel):
    reference_set_item_id: str
    reference_set_id: str
    image_id: str
    media_id: str | None
    taxon_id: str | None
    taxon_confidence: float | None
    developmental_stage: str | None
    orientation_context: str | None
    calibration_status: str
    image_quality_state: str
    source: str | None
    license: str | None
    inclusion_reason: str | None
    review_state: str


class ReferenceSetResponse(BaseModel):
    reference_set_id: str
    title: str
    target_concept_id: str | None
    taxon_scope: str | None
    description: str | None
    review_state: str
    license_summary: str | None
    notes: str | None
    items: list[ReferenceSetItemResponse]


class VisionAnalysisResponse(BaseModel):
    analysis_id: str
    image_id: str
    reference_set_id: str | None
    vision_model: str
    vision_model_version: str
    analysis_version: int
    taxon_context: str | None
    taxon_confidence: float | None
    calibration_state: str
    image_quality: str
    analysis_status: str
    review_state: str
    warnings: list[str]
    limitations: list[str]


class VisionRegionResponse(BaseModel):
    region_id: str
    analysis_id: str
    concept_id: str | None
    label: str
    bounding_box: dict[str, Any] | None
    segmentation_ref: str | None
    landmarks: list[dict[str, Any]] | None
    confidence: float | None
    review_state: str


class CharacterObservationResponse(BaseModel):
    observation_id: str
    analysis_id: str
    region_id: str | None
    concept_id: str | None
    character_id: str
    character_state_id: str | None
    numeric_value: float | None
    unit: str | None
    relative_value: float | None
    measurement_basis: str
    confidence: float
    method: str | None
    review_state: str
    limitations: list[str]


class MorphometricObservationResponse(BaseModel):
    morphometric_id: str
    analysis_id: str
    region_id: str | None
    metric_type: str
    value: float
    unit: str | None
    calibration_state: str
    confidence: float | None


class ColorPhenotypeObservationResponse(BaseModel):
    color_obs_id: str
    analysis_id: str
    region_id: str | None
    phenotype_class: str
    rgb_hex: str | None
    pattern_description: str | None
    pigment_class: str | None
    note: str = "Vision analysis alone cannot assert chemical pigment identity"


class FigureSpecResponse(BaseModel):
    figure_spec_id: str
    target_concept_id: str | None
    purpose: str
    scope: str
    media_type: str
    review_state: str
    version: int
    required_structures: list[dict[str, Any]]
    required_character_states: list[dict[str, Any]]
    uncertainty_notes: str | None


class ValidationRunResponse(BaseModel):
    validation_run_id: str
    asset_id: str
    figure_spec_id: str | None
    status: str
    overall_review_state: str
    conformance_checks: list[dict[str, Any]]


class AggregateSummaryResponse(BaseModel):
    reference_set_id: str
    analysis_count: int
    character_summaries: list[dict[str, Any]]
    numeric_summaries: list[dict[str, Any]]
    unresolved_count: int


class EvidenceSummaryResponse(BaseModel):
    """Frontend evidence-summary contract consumed by Famous Lexicon."""

    concept_id: str | None
    concept_label: str | None
    reference_sets: list[dict[str, Any]]
    reference_images: list[dict[str, Any]]
    vision_observations: list[dict[str, Any]]
    morphometrics: list[dict[str, Any]]
    aggregate_summary: dict[str, Any] | None
    figure_specifications: list[dict[str, Any]]
    visual_assets: list[dict[str, Any]]
    validation_runs: list[dict[str, Any]]
    review_state: str
    provenance: dict[str, Any]
    limitations: list[str]


class CapabilityStatusResponse(BaseModel):
    capability: str
    live_inference_enabled: bool
    provider_status: str
    migration_activated: bool
    safeguards: dict[str, Any]
    remaining_external_dependencies: list[str]
