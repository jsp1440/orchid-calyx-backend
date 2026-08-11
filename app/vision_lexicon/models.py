"""Domain models for the Vision-Lexicon bridge.

Scientific constraints enforced here:
- Uncalibrated images MUST NOT emit absolute physical measurements.
- Image-derived colour phenotype MUST NOT be elevated to chemical pigment
  identity without independent evidence.
- Machine-generated observations remain in PENDING_REVIEW state and MUST NOT
  be published as canonical knowledge without human governance.
- Cannot-determine states are first-class values, never suppressed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class ReviewState(StrEnum):
    PENDING_REVIEW = "PENDING_REVIEW"
    MACHINE_CHECKED = "MACHINE_CHECKED"
    COMMUNITY_REVIEWED = "COMMUNITY_REVIEWED"
    EXPERT_REVIEWED = "EXPERT_REVIEWED"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SCIENTIFIC_APPROVAL_PENDING = "SCIENTIFIC_APPROVAL_PENDING"


class AnalysisStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    PROVIDER_UNAVAILABLE = "PROVIDER_UNAVAILABLE"
    INSUFFICIENT_CONTEXT = "INSUFFICIENT_CONTEXT"


class CalibrationState(StrEnum):
    UNCALIBRATED = "UNCALIBRATED"
    SCALE_REFERENCE_PRESENT = "SCALE_REFERENCE_PRESENT"
    CALIBRATED = "CALIBRATED"
    CALIBRATION_UNCERTAIN = "CALIBRATION_UNCERTAIN"


class ImageQuality(StrEnum):
    SUFFICIENT = "SUFFICIENT"
    MARGINAL = "MARGINAL"
    INSUFFICIENT = "INSUFFICIENT"
    CANNOT_DETERMINE = "CANNOT_DETERMINE"


class MeasurementBasis(StrEnum):
    RELATIVE = "RELATIVE"
    RATIO = "RATIO"
    ANGLE = "ANGLE"
    NORMALIZED = "NORMALIZED"
    SHAPE_DESCRIPTOR = "SHAPE_DESCRIPTOR"
    ABSOLUTE_CALIBRATED = "ABSOLUTE_CALIBRATED"


class ConformanceResult(StrEnum):
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"
    CANNOT_DETERMINE = "CANNOT_DETERMINE"


class ColorEvidenceClass(StrEnum):
    """Strict hierarchy: image-derived < inferred pigment < verified pigment."""
    IMAGE_DERIVED_PHENOTYPE = "IMAGE_DERIVED_PHENOTYPE"
    INFERRED_PIGMENT_CLASS = "INFERRED_PIGMENT_CLASS"
    CHEMICALLY_VERIFIED_PIGMENT = "CHEMICALLY_VERIFIED_PIGMENT"


class LicenseUsage(StrEnum):
    MACHINE_ANALYSIS_ONLY = "MACHINE_ANALYSIS_ONLY"
    INTERNAL_REVIEW = "INTERNAL_REVIEW"
    PUBLIC_DISPLAY = "PUBLIC_DISPLAY"
    DERIVATIVE_ILLUSTRATION = "DERIVATIVE_ILLUSTRATION"


class MediaType(StrEnum):
    STATIC_ILLUSTRATION = "STATIC_ILLUSTRATION"
    ANNOTATED_PHOTO = "ANNOTATED_PHOTO"
    INTERACTIVE_DIAGRAM = "INTERACTIVE_DIAGRAM"
    ANIMATION = "ANIMATION"
    VIDEO = "VIDEO"
    THREE_D_INTERACTIVE = "THREE_D_INTERACTIVE"


# ---------------------------------------------------------------------------
# Reference Image Set
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReferenceImageSet:
    reference_set_id: UUID
    title: str
    target_concept_id: UUID
    taxon_scope: str | None
    description: str | None
    created_at: datetime
    created_by: str
    review_state: ReviewState
    provenance: dict[str, Any]
    license_summary: str | None
    notes: str | None


@dataclass(frozen=True)
class ReferenceImageSetItem:
    reference_set_item_id: UUID
    reference_set_id: UUID
    image_id: str
    taxon_id: str | None
    taxon_confidence: float | None
    developmental_stage: str | None
    orientation_context: str | None
    calibration_status: CalibrationState
    scale_information: dict[str, Any] | None
    image_quality_state: ImageQuality
    source: str | None
    license: str | None
    license_usages: tuple[LicenseUsage, ...]
    provenance: dict[str, Any]
    inclusion_reason: str | None
    review_state: ReviewState

    def __post_init__(self) -> None:
        if self.taxon_confidence is not None and not (0.0 <= self.taxon_confidence <= 1.0):
            raise ValueError("INVALID_TAXON_CONFIDENCE")


# ---------------------------------------------------------------------------
# Vision Analysis
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VisionAnalysis:
    analysis_id: UUID
    image_id: str
    reference_set_id: UUID | None
    vision_model: str
    vision_model_version: str
    analysis_version: int
    created_at: datetime
    taxon_context: str | None
    taxon_confidence: float | None
    calibration_state: CalibrationState
    image_quality: ImageQuality
    analysis_status: AnalysisStatus
    review_state: ReviewState
    provenance: dict[str, Any]
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.analysis_version < 1:
            raise ValueError("ANALYSIS_VERSION_MUST_BE_POSITIVE")
        if self.taxon_confidence is not None and not (0.0 <= self.taxon_confidence <= 1.0):
            raise ValueError("INVALID_TAXON_CONFIDENCE")


# ---------------------------------------------------------------------------
# Region / Structure Observations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VisionRegion:
    region_id: UUID
    analysis_id: UUID
    concept_id: UUID | None
    label: str
    bounding_box: dict[str, Any] | None
    segmentation_reference: str | None
    landmarks: dict[str, Any] | None
    confidence: float
    review_state: ReviewState
    provenance: dict[str, Any]

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("INVALID_CONFIDENCE")


# ---------------------------------------------------------------------------
# Character Observations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CharacterObservation:
    """Structured observation of a single botanical character.

    Scientific constraints:
    - numeric_value with ABSOLUTE_CALIBRATED basis requires calibration_basis.
    - colour_evidence_class controls the ceiling for colour interpretation.
    """
    observation_id: UUID
    analysis_id: UUID
    region_id: UUID | None
    concept_id: UUID | None
    character_id: UUID | None
    character_state_id: UUID | None
    numeric_value: float | None
    unit: str | None
    relative_value: float | None
    measurement_basis: MeasurementBasis | None
    calibration_basis: str | None
    confidence: float
    method: str
    evidence_region: dict[str, Any] | None
    colour_evidence_class: ColorEvidenceClass | None
    review_state: ReviewState
    provenance: dict[str, Any]
    limitations: tuple[str, ...]
    cannot_determine: bool

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("INVALID_CONFIDENCE")
        if (
            self.measurement_basis == MeasurementBasis.ABSOLUTE_CALIBRATED
            and not self.calibration_basis
        ):
            raise ValueError("ABSOLUTE_CALIBRATED_REQUIRES_CALIBRATION_BASIS")
        if (
            self.numeric_value is not None
            and self.measurement_basis == MeasurementBasis.ABSOLUTE_CALIBRATED
            and self.unit is None
        ):
            raise ValueError("CALIBRATED_ABSOLUTE_REQUIRES_UNIT")


def enforce_calibration_constraint(
    *,
    calibration_state: CalibrationState,
    measurement_basis: MeasurementBasis,
) -> None:
    """Raise if an uncalibrated image attempts to emit absolute measurements."""
    absolute_bases = {MeasurementBasis.ABSOLUTE_CALIBRATED}
    if (
        calibration_state == CalibrationState.UNCALIBRATED
        and measurement_basis in absolute_bases
    ):
        raise ValueError(
            "UNCALIBRATED_IMAGE_CANNOT_EMIT_ABSOLUTE_MEASUREMENTS: "
            "Only ratios, normalized distances, angles, and shape "
            "descriptors are permitted for uncalibrated sources."
        )


def enforce_colour_ceiling(
    *,
    evidence_class: ColorEvidenceClass,
    claimed_class: ColorEvidenceClass,
) -> None:
    """Raise if a claim elevates colour evidence beyond its evidence basis."""
    ceiling_order = [
        ColorEvidenceClass.IMAGE_DERIVED_PHENOTYPE,
        ColorEvidenceClass.INFERRED_PIGMENT_CLASS,
        ColorEvidenceClass.CHEMICALLY_VERIFIED_PIGMENT,
    ]
    if ceiling_order.index(claimed_class) > ceiling_order.index(evidence_class):
        raise ValueError(
            f"COLOUR_EVIDENCE_CEILING_VIOLATION: evidence basis {evidence_class!r} "
            f"cannot support claim at level {claimed_class!r}. "
            "Vision analysis alone cannot assert chemical pigment identity."
        )


# ---------------------------------------------------------------------------
# Morphometric Observations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MorphometricObservation:
    """Quantitative geometric / shape observation.

    Absolute physical dimensions (mm, cm, area) are only permitted when
    calibration_state == CALIBRATED and calibration_basis is documented.
    """
    morphometric_id: UUID
    analysis_id: UUID
    region_id: UUID | None
    concept_id: UUID | None
    measurement_type: str
    value: float | None
    unit: str | None
    measurement_basis: MeasurementBasis
    calibration_state: CalibrationState
    calibration_basis: str | None
    calibration_uncertainty: float | None
    landmarks: dict[str, Any] | None
    confidence: float
    review_state: ReviewState
    provenance: dict[str, Any]
    cannot_determine: bool

    def __post_init__(self) -> None:
        enforce_calibration_constraint(
            calibration_state=self.calibration_state,
            measurement_basis=self.measurement_basis,
        )
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("INVALID_CONFIDENCE")


# ---------------------------------------------------------------------------
# Vision Assertions (KG-style provenance-aware)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VisionAssertion:
    """Machine-derived assertion in provenance-aware form.

    MUST NOT be published as canonical knowledge without review governance.
    """
    assertion_id: UUID
    analysis_id: UUID
    subject: str
    predicate: str
    object_or_value: str | None
    evidence_region_id: UUID | None
    confidence: float
    assertion_state: str
    review_state: ReviewState
    created_at: datetime
    provenance: dict[str, Any]

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("INVALID_CONFIDENCE")


# ---------------------------------------------------------------------------
# Figure / Media Specification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FigureSpecification:
    """Structured specification for a scientific illustration or media asset.

    Vendor-independent: does not mandate a specific image-generation provider.
    Extensible to animation / video via MediaSpecification.
    """
    figure_spec_id: UUID
    target_concept_id: UUID
    purpose: str
    scope: str
    taxon_scope: str | None
    reference_set_ids: tuple[UUID, ...]
    required_structures: tuple[dict[str, Any], ...]
    required_character_states: tuple[dict[str, Any], ...]
    required_relationships: tuple[dict[str, Any], ...]
    allowed_variation: dict[str, Any]
    excluded_interpretations: tuple[str, ...]
    relative_geometry_constraints: dict[str, Any]
    colour_constraints: dict[str, Any]
    literature_constraints: tuple[dict[str, Any], ...]
    label_requirements: tuple[str, ...]
    uncertainty_notes: tuple[str, ...]
    generation_notes: str | None
    media_type: MediaType
    # Moving-media fields (populated only when media_type != STATIC_ILLUSTRATION)
    temporal_sequence: tuple[dict[str, Any], ...] | None
    required_stage_order: tuple[str, ...] | None
    motion_constraints: dict[str, Any] | None
    duration_range_seconds: tuple[float, float] | None
    loop_behavior: str | None
    scientific_state_transitions: tuple[dict[str, Any], ...] | None
    reduced_motion_alternative: str | None
    created_at: datetime
    created_by: str
    review_state: ReviewState
    version: int
    provenance: dict[str, Any]


# ---------------------------------------------------------------------------
# Figure Validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FigureValidationRun:
    validation_run_id: UUID
    asset_id: str
    figure_spec_id: UUID
    vision_analysis_id: UUID | None
    created_at: datetime
    status: str
    overall_review_state: ReviewState
    provenance: dict[str, Any]


@dataclass(frozen=True)
class CharacterConformanceCheck:
    """Character-level conformance check result.

    DO NOT collapse these into a single numeric "accuracy" score.
    Each check must be independently inspectable.
    """
    check_id: UUID
    validation_run_id: UUID
    character_id: UUID | None
    expected_state_or_range: dict[str, Any]
    observed_state_or_value: dict[str, Any] | None
    result: ConformanceResult
    confidence: float
    notes: str | None
    review_state: ReviewState

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("INVALID_CONFIDENCE")


# ---------------------------------------------------------------------------
# Frontend evidence summary contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConceptEvidenceSummary:
    """Frontend-facing summary of all vision evidence for a Lexicon concept.

    The frontend must not need to reconstruct scientific assertions from
    raw database tables.
    """
    concept_id: UUID
    concept_label: str
    reference_sets: tuple[dict[str, Any], ...]
    reference_images: tuple[dict[str, Any], ...]
    vision_observations: tuple[dict[str, Any], ...]
    morphometrics: tuple[dict[str, Any], ...]
    aggregate_summary: dict[str, Any]
    figure_specifications: tuple[dict[str, Any], ...]
    visual_assets: tuple[dict[str, Any], ...]
    validation_runs: tuple[dict[str, Any], ...]
    review_state: ReviewState
    provenance: dict[str, Any]
    limitations: tuple[str, ...]
