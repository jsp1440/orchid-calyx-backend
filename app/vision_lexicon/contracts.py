"""Immutable domain contracts for the Vision-Lexicon bridge.

All domain objects are frozen dataclasses so that service code cannot
accidentally mutate scientific records after creation.

Key design rules
----------------
1. CalibrationState controls what morphometric outputs are allowed.
   UNCALIBRATED -> only ratios, angles, normalised distances, shape descriptors.
   Anything else -> absolute dimensions also allowed.

2. ColorPhenotypeClass controls the strength of colour evidence.
   IMAGE_DERIVED   -> Vision alone may assert this.
   INFERRED_PIGMENT_CLASS -> requires independent secondary evidence_source.
   CHEMICALLY_VERIFIED    -> requires chemical / analytical evidence_source.
   Vision MUST NOT elevate image colour into a chemically verified pigment
   identity without external evidence.

3. VisionAnalysisReviewState distinguishes machine output from reviewed science.
   MACHINE_GENERATED is the entry state for all Vision outputs.
   No automatic promotion to APPROVED without human review.

4. CharacterConformanceResult.CANNOT_DETERMINE is preserved as a first-class
   outcome and must never be silently collapsed into PASS or FAIL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from uuid import UUID

# ---------------------------------------------------------------------------
# Shared enumerations
# ---------------------------------------------------------------------------


class CalibrationState(StrEnum):
    UNCALIBRATED = "UNCALIBRATED"
    SCALE_BAR_PRESENT = "SCALE_BAR_PRESENT"
    KNOWN_REFERENCE_OBJECT = "KNOWN_REFERENCE_OBJECT"
    RULER_PRESENT = "RULER_PRESENT"
    FIELD_CALIBRATED = "FIELD_CALIBRATED"

    def is_calibrated(self) -> bool:
        return self != CalibrationState.UNCALIBRATED


class ImageQualityState(StrEnum):
    UNKNOWN = "UNKNOWN"
    ACCEPTABLE = "ACCEPTABLE"
    CROPPED = "CROPPED"
    DETACHED_SPECIMEN = "DETACHED_SPECIMEN"
    LOW_RESOLUTION = "LOW_RESOLUTION"
    OBSTRUCTED = "OBSTRUCTED"


class VisionReviewState(StrEnum):
    MACHINE_GENERATED = "MACHINE_GENERATED"
    COMMUNITY_REVIEWED = "COMMUNITY_REVIEWED"
    EXPERT_REVIEWED = "EXPERT_REVIEWED"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SCIENTIFIC_APPROVAL_PENDING = "SCIENTIFIC_APPROVAL_PENDING"

    def is_machine_only(self) -> bool:
        return self == VisionReviewState.MACHINE_GENERATED

    def is_approved(self) -> bool:
        return self == VisionReviewState.APPROVED


class MeasurementBasis(StrEnum):
    IMAGE_DERIVED = "IMAGE_DERIVED"
    CALIBRATED_SCALE = "CALIBRATED_SCALE"
    LITERATURE_REFERENCE = "LITERATURE_REFERENCE"
    RELATIVE_PROPORTION = "RELATIVE_PROPORTION"
    CANNOT_DETERMINE = "CANNOT_DETERMINE"


class MetricType(StrEnum):
    RATIO = "RATIO"
    NORMALIZED_DISTANCE = "NORMALIZED_DISTANCE"
    ANGLE = "ANGLE"
    SHAPE_DESCRIPTOR = "SHAPE_DESCRIPTOR"
    AREA_RATIO = "AREA_RATIO"
    ORIENTATION_VECTOR = "ORIENTATION_VECTOR"
    RELATIVE_PROPORTION = "RELATIVE_PROPORTION"
    ABSOLUTE_LENGTH = "ABSOLUTE_LENGTH"
    ABSOLUTE_AREA = "ABSOLUTE_AREA"
    ABSOLUTE_VOLUME = "ABSOLUTE_VOLUME"

    def requires_calibration(self) -> bool:
        return self in {
            MetricType.ABSOLUTE_LENGTH,
            MetricType.ABSOLUTE_AREA,
            MetricType.ABSOLUTE_VOLUME,
        }


class ColorPhenotypeClass(StrEnum):
    IMAGE_DERIVED = "IMAGE_DERIVED"
    INFERRED_PIGMENT_CLASS = "INFERRED_PIGMENT_CLASS"
    CHEMICALLY_VERIFIED = "CHEMICALLY_VERIFIED"


class AssertionState(StrEnum):
    MACHINE_CANDIDATE = "MACHINE_CANDIDATE"
    COMMUNITY_REVIEWED = "COMMUNITY_REVIEWED"
    EXPERT_REVIEWED = "EXPERT_REVIEWED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class CharacterConformanceResult(StrEnum):
    PASS = "PASS"
    PARTIAL = "PARTIAL"
    FAIL = "FAIL"
    CANNOT_DETERMINE = "CANNOT_DETERMINE"


class ValidationRunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class AnalysisStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CANNOT_DETERMINE = "CANNOT_DETERMINE"


class MediaType(StrEnum):
    STATIC_ILLUSTRATION = "STATIC_ILLUSTRATION"
    ANNOTATED_PHOTO = "ANNOTATED_PHOTO"
    INTERACTIVE_DIAGRAM = "INTERACTIVE_DIAGRAM"
    ANIMATION = "ANIMATION"
    VIDEO = "VIDEO"
    THREE_D_INTERACTIVE = "3D_INTERACTIVE"


class ReviewerTier(StrEnum):
    COMMUNITY = "COMMUNITY"
    EXPERT = "EXPERT"
    SCIENTIFIC_AUTHORITY = "SCIENTIFIC_AUTHORITY"


class ReviewDecision(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_REVISION = "REQUEST_REVISION"
    FLAG_UNCERTAIN = "FLAG_UNCERTAIN"


# ---------------------------------------------------------------------------
# Reference Image Set
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReferenceImageSetItem:
    reference_set_item_id: UUID
    reference_set_id: UUID
    image_id: str
    media_id: str | None
    taxon_id: str | None
    taxon_confidence: float | None
    developmental_stage: str | None
    orientation_context: str | None
    calibration_status: CalibrationState
    scale_information: dict[str, Any] | None
    image_quality_state: ImageQualityState
    source: str | None
    license: str | None
    provenance: dict[str, Any]
    inclusion_reason: str | None
    review_state: VisionReviewState

    def validate(self) -> None:
        if not self.image_id.strip():
            raise ValueError("IMAGE_ID_REQUIRED")
        if self.taxon_confidence is not None and not 0.0 <= self.taxon_confidence <= 1.0:
            raise ValueError("TAXON_CONFIDENCE_OUT_OF_RANGE")


@dataclass(frozen=True)
class ReferenceImageSet:
    reference_set_id: UUID
    title: str
    target_concept_id: UUID | None
    taxon_scope: str | None
    description: str | None
    created_by: str
    review_state: VisionReviewState
    provenance: dict[str, Any]
    license_summary: str | None
    notes: str | None
    items: tuple[ReferenceImageSetItem, ...] = field(default_factory=tuple)

    def validate(self) -> None:
        if not self.title.strip():
            raise ValueError("REFERENCE_SET_TITLE_REQUIRED")
        if not self.created_by.strip():
            raise ValueError("REFERENCE_SET_CREATOR_REQUIRED")
        for item in self.items:
            item.validate()


# ---------------------------------------------------------------------------
# Vision Analysis
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VisionAnalysisRecord:
    analysis_id: UUID
    image_id: str
    content_hash: str
    reference_set_id: UUID | None
    vision_model: str
    vision_model_version: str
    analysis_version: int
    taxon_context: str | None
    taxon_confidence: float | None
    calibration_state: CalibrationState
    image_quality: ImageQualityState
    analysis_status: AnalysisStatus
    review_state: VisionReviewState
    provenance: dict[str, Any]
    warnings: tuple[str, ...]
    limitations: tuple[str, ...]
    request_hash: str | None = None

    def validate(self) -> None:
        if not self.image_id.strip():
            raise ValueError("ANALYSIS_IMAGE_ID_REQUIRED")
        if len(self.content_hash) < 32:
            raise ValueError("ANALYSIS_CONTENT_HASH_INVALID")
        if not self.vision_model.strip() or not self.vision_model_version.strip():
            raise ValueError("ANALYSIS_MODEL_REQUIRED")
        if self.analysis_version < 1:
            raise ValueError("ANALYSIS_VERSION_INVALID")
        if self.taxon_confidence is not None and not 0.0 <= self.taxon_confidence <= 1.0:
            raise ValueError("TAXON_CONFIDENCE_OUT_OF_RANGE")


# ---------------------------------------------------------------------------
# Vision Region
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VisionRegion:
    region_id: UUID
    analysis_id: UUID
    concept_id: UUID | None
    label: str
    bounding_box: dict[str, Any] | None
    segmentation_ref: str | None
    landmarks: list[dict[str, Any]] | None
    confidence: float | None
    review_state: VisionReviewState
    provenance: dict[str, Any]

    def validate(self) -> None:
        if not self.label.strip():
            raise ValueError("REGION_LABEL_REQUIRED")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("REGION_CONFIDENCE_OUT_OF_RANGE")


# ---------------------------------------------------------------------------
# Character Observation
# ---------------------------------------------------------------------------

_RELATIVE_UNITS = frozenset(
    {"ratio", "angle_deg", "angle_rad", "normalized", "proportion", "cannot_determine"}
)


@dataclass(frozen=True)
class CharacterObservation:
    """Canonical character observation linked to Lexicon identifiers.

    Scientific safeguard: absolute physical units (mm, cm, m²…) are only
    permitted when measurement_basis is CALIBRATED_SCALE.  All other bases
    must use relative / dimensionless units or no unit at all.
    """

    observation_id: UUID
    analysis_id: UUID
    region_id: UUID | None
    concept_id: UUID | None
    character_id: str
    character_state_id: str | None
    numeric_value: float | None
    unit: str | None
    relative_value: float | None
    measurement_basis: MeasurementBasis
    confidence: float
    method: str | None
    evidence_region: str | None
    review_state: VisionReviewState
    provenance: dict[str, Any]
    limitations: tuple[str, ...]

    def validate(self) -> None:
        if not self.character_id.strip():
            raise ValueError("CHARACTER_ID_REQUIRED")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("CHARACTER_CONFIDENCE_OUT_OF_RANGE")
        if (
            self.unit is not None
            and self.measurement_basis != MeasurementBasis.CALIBRATED_SCALE
            and self.unit.lower() not in _RELATIVE_UNITS
        ):
            raise ValueError(
                "ABSOLUTE_UNIT_REQUIRES_CALIBRATION: "
                f"unit '{self.unit}' is only allowed when measurement_basis "
                "is CALIBRATED_SCALE"
            )


# ---------------------------------------------------------------------------
# Morphometric Observation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MorphometricObservation:
    """Morphometric record.

    Scientific safeguard: metric_type ABSOLUTE_LENGTH / ABSOLUTE_AREA /
    ABSOLUTE_VOLUME requires calibration_state != UNCALIBRATED.
    """

    morphometric_id: UUID
    analysis_id: UUID
    region_id: UUID | None
    metric_type: MetricType
    value: float
    unit: str | None
    calibration_state: CalibrationState
    calibration_basis: str | None
    calibration_uncertainty: str | None
    confidence: float | None
    landmarks_used: list[dict[str, Any]] | None
    provenance: dict[str, Any]

    def validate(self) -> None:
        if self.metric_type.requires_calibration() and not self.calibration_state.is_calibrated():
            raise ValueError(
                "ABSOLUTE_DIMENSION_REQUIRES_CALIBRATION: "
                f"metric_type '{self.metric_type}' requires a calibrated image; "
                f"current calibration_state is '{self.calibration_state}'"
            )
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("MORPHOMETRIC_CONFIDENCE_OUT_OF_RANGE")


# ---------------------------------------------------------------------------
# Color Phenotype Observation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ColorPhenotypeObservation:
    """Color phenotype observation.

    Scientific safeguard: Vision alone may only assert IMAGE_DERIVED class.
    INFERRED_PIGMENT_CLASS and CHEMICALLY_VERIFIED require an independent
    pigment_evidence_source; the domain object enforces this constraint.
    """

    color_obs_id: UUID
    analysis_id: UUID
    region_id: UUID | None
    phenotype_class: ColorPhenotypeClass
    rgb_hex: str | None
    hsv_hue: float | None
    hsv_saturation: float | None
    hsv_value: float | None
    lab_l: float | None
    lab_a: float | None
    lab_b: float | None
    pattern_description: str | None
    pigment_class: str | None
    pigment_evidence_source: str | None
    provenance: dict[str, Any]

    def validate(self) -> None:
        if (
            self.phenotype_class != ColorPhenotypeClass.IMAGE_DERIVED
            and not self.pigment_evidence_source
        ):
            raise ValueError(
                "PIGMENT_EVIDENCE_SOURCE_REQUIRED: "
                f"phenotype_class '{self.phenotype_class}' requires "
                "an independent pigment_evidence_source; "
                "Vision image analysis alone cannot assert this class"
            )
        if self.rgb_hex is not None:
            import re

            if not re.match(r"^#[0-9A-Fa-f]{6}$", self.rgb_hex):
                raise ValueError("RGB_HEX_FORMAT_INVALID")


# ---------------------------------------------------------------------------
# Vision Assertion
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VisionAssertion:
    assertion_id: UUID
    analysis_id: UUID
    subject: str
    predicate: str
    object_or_value: str
    evidence_id: str | None
    confidence: float | None
    assertion_state: AssertionState
    review_state: VisionReviewState
    provenance: dict[str, Any]

    def validate(self) -> None:
        if not self.subject.strip() or not self.predicate.strip() or not self.object_or_value.strip():
            raise ValueError("ASSERTION_SUBJECT_PREDICATE_OBJECT_REQUIRED")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("ASSERTION_CONFIDENCE_OUT_OF_RANGE")


# ---------------------------------------------------------------------------
# Figure Specification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FigureSpecification:
    figure_spec_id: UUID
    target_concept_id: UUID | None
    purpose: str
    scope: str
    taxon_scope: str | None
    reference_set_ids: tuple[UUID, ...]
    required_structures: list[dict[str, Any]]
    required_character_states: list[dict[str, Any]]
    required_relationships: list[dict[str, Any]]
    allowed_variation: dict[str, Any]
    excluded_interpretations: list[dict[str, Any]]
    relative_geometry_constraints: dict[str, Any]
    color_constraints: dict[str, Any]
    literature_constraints: list[dict[str, Any]]
    label_requirements: list[dict[str, Any]]
    uncertainty_notes: str | None
    generation_notes: str | None
    media_type: MediaType
    temporal_sequence: list[dict[str, Any]] | None
    required_stage_order: list[str] | None
    motion_constraints: dict[str, Any] | None
    duration_range: dict[str, Any] | None
    loop_behavior: str | None
    scientific_state_transitions: list[dict[str, Any]] | None
    reduced_motion_alternative: str | None
    created_by: str
    review_state: VisionReviewState
    version: int
    provenance: dict[str, Any]

    def validate(self) -> None:
        if not self.purpose.strip():
            raise ValueError("FIGURE_SPEC_PURPOSE_REQUIRED")
        if not self.created_by.strip():
            raise ValueError("FIGURE_SPEC_CREATOR_REQUIRED")
        if self.version < 1:
            raise ValueError("FIGURE_SPEC_VERSION_INVALID")


# ---------------------------------------------------------------------------
# Figure Validation Run
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FigureValidationRun:
    validation_run_id: UUID
    asset_id: str
    figure_spec_id: UUID | None
    vision_analysis_id: UUID | None
    status: ValidationRunStatus
    overall_review_state: VisionReviewState
    provenance: dict[str, Any]
    conformance_checks: tuple[CharacterConformanceCheck, ...] = field(default_factory=tuple)

    def validate(self) -> None:
        if not self.asset_id.strip():
            raise ValueError("VALIDATION_RUN_ASSET_ID_REQUIRED")


# ---------------------------------------------------------------------------
# Character Conformance Check
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CharacterConformanceCheck:
    """Per-character conformance result.

    CANNOT_DETERMINE is a first-class result and must never be silently
    collapsed into PASS or FAIL by downstream consumers.
    """

    check_id: UUID
    validation_run_id: UUID
    character_id: str
    expected_state_or_range: str | None
    observed_state_or_value: str | None
    result: CharacterConformanceResult
    confidence: float | None
    notes: str | None
    review_state: VisionReviewState

    def validate(self) -> None:
        if not self.character_id.strip():
            raise ValueError("CONFORMANCE_CHARACTER_ID_REQUIRED")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("CONFORMANCE_CONFIDENCE_OUT_OF_RANGE")


# ---------------------------------------------------------------------------
# Vision Review Record
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VisionReviewRecord:
    """Human review record for any Vision pipeline object.

    auto_promotion_blocked=True enforces the governance rule that community
    agreement alone cannot become scientific truth.
    """

    review_id: UUID
    subject_type: str
    subject_id: UUID
    reviewer_id: str
    reviewer_tier: ReviewerTier
    decision: ReviewDecision
    scope_of_expertise: str | None
    version_reviewed: int | None
    questions_answered: list[dict[str, Any]]
    comments: str | None
    auto_promotion_blocked: bool
    provenance: dict[str, Any]

    def validate(self) -> None:
        if not self.reviewer_id.strip():
            raise ValueError("REVIEWER_ID_REQUIRED")
        # Community reviews cannot auto-promote
        if self.reviewer_tier == ReviewerTier.COMMUNITY and not self.auto_promotion_blocked:
            raise ValueError(
                "COMMUNITY_AUTO_PROMOTION_BLOCKED: "
                "Community review cannot automatically promote scientific truth; "
                "auto_promotion_blocked must be True for COMMUNITY tier reviews"
            )


# ---------------------------------------------------------------------------
# Aggregate Reference-Set Summary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CharacterStateSummary:
    character_id: str
    sample_size: int
    state_frequencies: dict[str, int]
    cannot_determine_count: int
    notes: str | None


@dataclass(frozen=True)
class NumericObservationSummary:
    character_id: str
    metric_type: str
    sample_size: int
    median: float | None
    min_value: float | None
    max_value: float | None
    range_note: str | None
    cannot_determine_count: int
    contributing_analysis_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class ReferenceSetAggregateSummary:
    reference_set_id: UUID
    analysis_count: int
    character_summaries: tuple[CharacterStateSummary, ...]
    numeric_summaries: tuple[NumericObservationSummary, ...]
    unresolved_count: int
    provenance: dict[str, Any]


# ---------------------------------------------------------------------------
# Frontend Evidence Summary Contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FrontendEvidenceSummary:
    """Flat evidence-summary contract for Famous Lexicon frontend consumption.

    The frontend must not need to reconstruct scientific assertions from raw
    database tables.  All scientific logic lives in the backend.
    """

    concept_id: UUID | None
    concept_label: str | None
    reference_sets: list[dict[str, Any]]
    reference_images: list[dict[str, Any]]
    vision_observations: list[dict[str, Any]]
    morphometrics: list[dict[str, Any]]
    aggregate_summary: dict[str, Any] | None
    figure_specifications: list[dict[str, Any]]
    visual_assets: list[dict[str, Any]]
    validation_runs: list[dict[str, Any]]
    review_state: VisionReviewState
    provenance: dict[str, Any]
    limitations: list[str]
