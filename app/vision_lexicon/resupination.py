"""Resupination reference implementation and fixture data.

This module provides:
1. Canonical concept identifiers for Resupination-related structures.
2. A fixture-based reference analysis for testing the full pipeline
   without a live Vision inference provider.
3. Analysis helpers specific to Resupination evidence interpretation.

Scientific notes
----------------
- Resupination is the developmental reorientation of the orchid flower
  during bud development, resulting in the labellum being positioned
  lowermost at anthesis in most Orchidaceae.
- Non-resupination occurs in genera where this rotation does not complete
  or is secondarily reversed (e.g. some Malaxis, Calanthe, Epidendrum
  secundum).
- Do NOT reduce Resupination to "flower upside down".
- Do NOT assume a single universal developmental mechanism across
  Orchidaceae; the degree and mechanism of torsion varies.
- Orientation scoring from images requires orientation context.
  A cropped or detached flower cannot reliably be scored.

This module never invents scientific observations.
Fixture data is clearly labelled as FIXTURE.
"""

from __future__ import annotations

from uuid import UUID

from .contracts import (
    AnalysisStatus,
    AssertionState,
    CalibrationState,
    CharacterConformanceCheck,
    CharacterConformanceResult,
    CharacterObservation,
    CharacterStateSummary,
    ColorPhenotypeClass,
    ColorPhenotypeObservation,
    FigureSpecification,
    FigureValidationRun,
    ImageQualityState,
    MeasurementBasis,
    MediaType,
    MetricType,
    MorphometricObservation,
    NumericObservationSummary,
    ReferenceImageSet,
    ReferenceImageSetItem,
    ReferenceSetAggregateSummary,
    ValidationRunStatus,
    VisionAnalysisRecord,
    VisionAssertion,
    VisionRegion,
    VisionReviewState,
)

# ---------------------------------------------------------------------------
# Stable fixture UUIDs
# (These are fixed so tests remain deterministic across runs.)
# ---------------------------------------------------------------------------

RESUPINATION_CONCEPT_ID = UUID("00000000-0000-0000-0000-000000000001")
NON_RESUPINATION_CONCEPT_ID = UUID("00000000-0000-0000-0000-000000000002")
LABELLUM_CONCEPT_ID = UUID("00000000-0000-0000-0000-000000000003")
COLUMN_CONCEPT_ID = UUID("00000000-0000-0000-0000-000000000004")
OVARY_CONCEPT_ID = UUID("00000000-0000-0000-0000-000000000005")
PEDICEL_CONCEPT_ID = UUID("00000000-0000-0000-0000-000000000006")
DORSAL_SEPAL_CONCEPT_ID = UUID("00000000-0000-0000-0000-000000000007")
LATERAL_SEPAL_CONCEPT_ID = UUID("00000000-0000-0000-0000-000000000008")
PETAL_CONCEPT_ID = UUID("00000000-0000-0000-0000-000000000009")

FIXTURE_REF_SET_ID = UUID("10000000-0000-0000-0000-000000000001")
FIXTURE_ITEM_ID = UUID("10000000-0000-0000-0000-000000000002")
FIXTURE_ANALYSIS_ID = UUID("10000000-0000-0000-0000-000000000003")
FIXTURE_LABELLUM_REGION_ID = UUID("10000000-0000-0000-0000-000000000004")
FIXTURE_COLUMN_REGION_ID = UUID("10000000-0000-0000-0000-000000000005")
FIXTURE_OBS_ORIENTATION_ID = UUID("10000000-0000-0000-0000-000000000006")
FIXTURE_OBS_RESUPINATION_STATE_ID = UUID("10000000-0000-0000-0000-000000000007")
FIXTURE_MORPHOMETRIC_ID = UUID("10000000-0000-0000-0000-000000000008")
FIXTURE_COLOR_OBS_ID = UUID("10000000-0000-0000-0000-000000000009")
FIXTURE_ASSERTION_ID = UUID("10000000-0000-0000-0000-000000000010")
FIXTURE_FIGURE_SPEC_ID = UUID("10000000-0000-0000-0000-000000000011")
FIXTURE_VALIDATION_RUN_ID = UUID("10000000-0000-0000-0000-000000000012")
FIXTURE_CONFORMANCE_LABELLUM_ID = UUID("10000000-0000-0000-0000-000000000013")
FIXTURE_CONFORMANCE_ORIENTATION_ID = UUID("10000000-0000-0000-0000-000000000014")

_FIXTURE_PROVENANCE = {
    "source": "FIXTURE",
    "note": "Test fixture data — not real observations. "
            "Do not publish as scientific evidence.",
}


# ---------------------------------------------------------------------------
# Resupination character vocabulary
# ---------------------------------------------------------------------------

class ResupinationCharacters:
    """Canonical character and state identifiers for Resupination scoring."""

    CHARACTER_LABELLUM_POSITION = "labellum_position_at_anthesis"
    CHARACTER_FLORAL_ORIENTATION = "floral_orientation_at_anthesis"
    CHARACTER_RESUPINATION_STATE = "resupination_state"
    CHARACTER_TORSION_ANGLE = "pedicel_ovary_torsion_angle"
    CHARACTER_DEVELOPMENTAL_STAGE = "developmental_stage"

    STATE_LABELLUM_LOWERMOST = "LOWERMOST"
    STATE_LABELLUM_UPPERMOST = "UPPERMOST"
    STATE_LABELLUM_LATERAL = "LATERAL"
    STATE_LABELLUM_CANNOT_DETERMINE = "CANNOT_DETERMINE"

    STATE_RESUPINATE = "RESUPINATE"
    STATE_NON_RESUPINATE = "NON_RESUPINATE"
    STATE_RESUPINATION_CANNOT_DETERMINE = "CANNOT_DETERMINE"

    STATE_STAGE_ANTHESIS = "ANTHESIS"
    STATE_STAGE_PRE_ANTHESIS = "PRE_ANTHESIS"
    STATE_STAGE_POST_ANTHESIS = "POST_ANTHESIS"
    STATE_STAGE_UNKNOWN = "UNKNOWN"


# ---------------------------------------------------------------------------
# Resupination orientation scoring helper
# ---------------------------------------------------------------------------


def score_resupination_from_observation(
    *,
    labellum_position_state: str | None,
    image_quality: ImageQualityState,
    developmental_stage_state: str | None,
    orientation_context: str | None,
) -> tuple[str, list[str]]:
    """Return (resupination_state, warnings).

    Returns ResupinationCharacters state constants or CANNOT_DETERMINE.
    Warnings are populated when context is insufficient.

    This function never invents evidence.  Insufficient information results
    in CANNOT_DETERMINE, not a best-guess.

    Parameters
    ----------
    labellum_position_state:
        Observed labellum position state from image analysis.
    image_quality:
        Quality/context flag for the source image.
    developmental_stage_state:
        Developmental stage if known.
    orientation_context:
        Free-text orientation context from image metadata.
    """
    warnings: list[str] = []
    RC = ResupinationCharacters

    if image_quality in (ImageQualityState.CROPPED, ImageQualityState.DETACHED_SPECIMEN):
        warnings.append(
            f"IMAGE_QUALITY_INSUFFICIENT_FOR_ORIENTATION: image_quality='{image_quality}' — "
            "labellum position relative to floral axis cannot be reliably scored "
            "from a cropped or detached specimen."
        )
        return RC.STATE_RESUPINATION_CANNOT_DETERMINE, warnings

    if not orientation_context:
        warnings.append(
            "ORIENTATION_CONTEXT_MISSING: no orientation context metadata; "
            "resupination scoring may be unreliable."
        )

    if developmental_stage_state not in (
        None,
        RC.STATE_STAGE_ANTHESIS,
        RC.STATE_STAGE_UNKNOWN,
    ):
        warnings.append(
            f"NON_ANTHESIS_STAGE: developmental_stage='{developmental_stage_state}' — "
            "resupination state should ideally be scored at anthesis."
        )

    if labellum_position_state is None:
        warnings.append("LABELLUM_POSITION_NOT_OBSERVED")
        return RC.STATE_RESUPINATION_CANNOT_DETERMINE, warnings

    if labellum_position_state == RC.STATE_LABELLUM_CANNOT_DETERMINE:
        return RC.STATE_RESUPINATION_CANNOT_DETERMINE, warnings

    if labellum_position_state == RC.STATE_LABELLUM_LOWERMOST:
        return RC.STATE_RESUPINATE, warnings

    if labellum_position_state == RC.STATE_LABELLUM_UPPERMOST:
        return RC.STATE_NON_RESUPINATE, warnings

    # Lateral or other indeterminate
    warnings.append(
        f"LABELLUM_POSITION_AMBIGUOUS: position='{labellum_position_state}' — "
        "cannot determine resupination state from this observation."
    )
    return RC.STATE_RESUPINATION_CANNOT_DETERMINE, warnings


# ---------------------------------------------------------------------------
# Fixture: valid Resupination reference pipeline
# ---------------------------------------------------------------------------


def fixture_reference_image_set() -> ReferenceImageSet:
    """Fixture reference image set for Resupination testing."""
    item = ReferenceImageSetItem(
        reference_set_item_id=FIXTURE_ITEM_ID,
        reference_set_id=FIXTURE_REF_SET_ID,
        image_id="fixture-image-001",
        media_id=None,
        taxon_id="fixture-taxon-orchidaceae-sp",
        taxon_confidence=0.9,
        developmental_stage="ANTHESIS",
        orientation_context="lateral view, natural orientation on stem",
        calibration_status=CalibrationState.UNCALIBRATED,
        scale_information=None,
        image_quality_state=ImageQualityState.ACCEPTABLE,
        source="FIXTURE",
        license="CC-BY-4.0",
        provenance=_FIXTURE_PROVENANCE,
        inclusion_reason="Reference specimen showing resupinate flower at anthesis",
        review_state=VisionReviewState.MACHINE_GENERATED,
    )
    return ReferenceImageSet(
        reference_set_id=FIXTURE_REF_SET_ID,
        title="[FIXTURE] Resupination Reference Set",
        target_concept_id=RESUPINATION_CONCEPT_ID,
        taxon_scope="Orchidaceae",
        description="Fixture reference set for pipeline testing. Not real scientific data.",
        created_by="fixture",
        review_state=VisionReviewState.MACHINE_GENERATED,
        provenance=_FIXTURE_PROVENANCE,
        license_summary="Test fixture only",
        notes="FIXTURE DATA — do not publish",
        items=(item,),
    )


def fixture_vision_analysis() -> VisionAnalysisRecord:
    """Fixture VisionAnalysis record for Resupination pipeline testing."""
    return VisionAnalysisRecord(
        analysis_id=FIXTURE_ANALYSIS_ID,
        image_id="fixture-image-001",
        content_hash="a" * 64,
        reference_set_id=FIXTURE_REF_SET_ID,
        vision_model="fixture-model",
        vision_model_version="1.0.0",
        analysis_version=1,
        taxon_context="Orchidaceae",
        taxon_confidence=0.9,
        calibration_state=CalibrationState.UNCALIBRATED,
        image_quality=ImageQualityState.ACCEPTABLE,
        analysis_status=AnalysisStatus.COMPLETE,
        review_state=VisionReviewState.MACHINE_GENERATED,
        provenance=_FIXTURE_PROVENANCE,
        warnings=("FIXTURE: not a real Vision inference",),
        limitations=("Uncalibrated image — no absolute measurements",),
        request_hash="fixture-request-hash-001",
    )


def fixture_vision_regions() -> tuple[VisionRegion, ...]:
    """Fixture VisionRegion records for Resupination."""
    labellum = VisionRegion(
        region_id=FIXTURE_LABELLUM_REGION_ID,
        analysis_id=FIXTURE_ANALYSIS_ID,
        concept_id=LABELLUM_CONCEPT_ID,
        label="Labellum",
        bounding_box={"x": 120, "y": 200, "width": 80, "height": 60},
        segmentation_ref=None,
        landmarks=[
            {"name": "labellum_apex", "x": 160, "y": 260},
            {"name": "labellum_base", "x": 160, "y": 200},
        ],
        confidence=0.88,
        review_state=VisionReviewState.MACHINE_GENERATED,
        provenance=_FIXTURE_PROVENANCE,
    )
    column = VisionRegion(
        region_id=FIXTURE_COLUMN_REGION_ID,
        analysis_id=FIXTURE_ANALYSIS_ID,
        concept_id=COLUMN_CONCEPT_ID,
        label="Column / Gynostemium",
        bounding_box={"x": 140, "y": 140, "width": 40, "height": 50},
        segmentation_ref=None,
        landmarks=None,
        confidence=0.82,
        review_state=VisionReviewState.MACHINE_GENERATED,
        provenance=_FIXTURE_PROVENANCE,
    )
    return (labellum, column)


def fixture_character_observations() -> tuple[CharacterObservation, ...]:
    """Fixture CharacterObservation records with canonical IDs."""
    RC = ResupinationCharacters
    labellum_pos = CharacterObservation(
        observation_id=FIXTURE_OBS_ORIENTATION_ID,
        analysis_id=FIXTURE_ANALYSIS_ID,
        region_id=FIXTURE_LABELLUM_REGION_ID,
        concept_id=LABELLUM_CONCEPT_ID,
        character_id=RC.CHARACTER_LABELLUM_POSITION,
        character_state_id=RC.STATE_LABELLUM_LOWERMOST,
        numeric_value=None,
        unit=None,
        relative_value=None,
        measurement_basis=MeasurementBasis.IMAGE_DERIVED,
        confidence=0.87,
        method="landmark_relative_position",
        evidence_region=str(FIXTURE_LABELLUM_REGION_ID),
        review_state=VisionReviewState.MACHINE_GENERATED,
        provenance=_FIXTURE_PROVENANCE,
        limitations=("FIXTURE observation",),
    )
    resupination_state = CharacterObservation(
        observation_id=FIXTURE_OBS_RESUPINATION_STATE_ID,
        analysis_id=FIXTURE_ANALYSIS_ID,
        region_id=None,
        concept_id=RESUPINATION_CONCEPT_ID,
        character_id=RC.CHARACTER_RESUPINATION_STATE,
        character_state_id=RC.STATE_RESUPINATE,
        numeric_value=None,
        unit=None,
        relative_value=None,
        measurement_basis=MeasurementBasis.IMAGE_DERIVED,
        confidence=0.87,
        method="derived_from_labellum_position",
        evidence_region=str(FIXTURE_LABELLUM_REGION_ID),
        review_state=VisionReviewState.MACHINE_GENERATED,
        provenance=_FIXTURE_PROVENANCE,
        limitations=("FIXTURE observation",),
    )
    return (labellum_pos, resupination_state)


def fixture_morphometric_observations() -> tuple[MorphometricObservation, ...]:
    """Fixture morphometric observations — uncalibrated, so only ratios/angles."""
    ratio = MorphometricObservation(
        morphometric_id=FIXTURE_MORPHOMETRIC_ID,
        analysis_id=FIXTURE_ANALYSIS_ID,
        region_id=FIXTURE_LABELLUM_REGION_ID,
        metric_type=MetricType.RATIO,
        value=0.67,
        unit="ratio",
        calibration_state=CalibrationState.UNCALIBRATED,
        calibration_basis=None,
        calibration_uncertainty=None,
        confidence=0.80,
        landmarks_used=[
            {"name": "labellum_apex"},
            {"name": "labellum_base"},
        ],
        provenance=_FIXTURE_PROVENANCE,
    )
    return (ratio,)


def fixture_color_observation() -> ColorPhenotypeObservation:
    """Fixture color observation — IMAGE_DERIVED only."""
    return ColorPhenotypeObservation(
        color_obs_id=FIXTURE_COLOR_OBS_ID,
        analysis_id=FIXTURE_ANALYSIS_ID,
        region_id=FIXTURE_LABELLUM_REGION_ID,
        phenotype_class=ColorPhenotypeClass.IMAGE_DERIVED,
        rgb_hex="#CC88AA",
        hsv_hue=340.0,
        hsv_saturation=0.33,
        hsv_value=0.80,
        lab_l=65.0,
        lab_a=18.0,
        lab_b=-5.0,
        pattern_description="uniform pinkish-purple",
        pigment_class=None,
        pigment_evidence_source=None,
        provenance=_FIXTURE_PROVENANCE,
    )


def fixture_vision_assertion() -> VisionAssertion:
    """Fixture vision assertion (MACHINE_CANDIDATE, not published)."""
    return VisionAssertion(
        assertion_id=FIXTURE_ASSERTION_ID,
        analysis_id=FIXTURE_ANALYSIS_ID,
        subject=str(LABELLUM_CONCEPT_ID),
        predicate="POSITION_AT_ANTHESIS",
        object_or_value="LOWERMOST",
        evidence_id=str(FIXTURE_OBS_ORIENTATION_ID),
        confidence=0.87,
        assertion_state=AssertionState.MACHINE_CANDIDATE,
        review_state=VisionReviewState.MACHINE_GENERATED,
        provenance=_FIXTURE_PROVENANCE,
    )


def fixture_figure_specification() -> FigureSpecification:
    """Fixture FigureSpecification for the Resupination concept."""
    return FigureSpecification(
        figure_spec_id=FIXTURE_FIGURE_SPEC_ID,
        target_concept_id=RESUPINATION_CONCEPT_ID,
        purpose="Illustrate labellum lowermost position at anthesis in a resupinate orchid",
        scope="MORPHOLOGICAL_ILLUSTRATION",
        taxon_scope="Orchidaceae (representative resupinate genus)",
        reference_set_ids=(FIXTURE_REF_SET_ID,),
        required_structures=[
            {"concept_id": str(LABELLUM_CONCEPT_ID), "label": "Labellum", "position": "lowermost"},
            {"concept_id": str(COLUMN_CONCEPT_ID), "label": "Column / Gynostemium"},
            {"concept_id": str(OVARY_CONCEPT_ID), "label": "Ovary / Pedicel"},
        ],
        required_character_states=[
            {
                "character_id": ResupinationCharacters.CHARACTER_RESUPINATION_STATE,
                "state_id": ResupinationCharacters.STATE_RESUPINATE,
            },
            {
                "character_id": ResupinationCharacters.CHARACTER_LABELLUM_POSITION,
                "state_id": ResupinationCharacters.STATE_LABELLUM_LOWERMOST,
            },
            {
                "character_id": ResupinationCharacters.CHARACTER_DEVELOPMENTAL_STAGE,
                "state_id": ResupinationCharacters.STATE_STAGE_ANTHESIS,
            },
        ],
        required_relationships=[
            {
                "predicate": "ILLUSTRATES",
                "object_concept_id": str(RESUPINATION_CONCEPT_ID),
            }
        ],
        allowed_variation={"taxon_representative": "any resupinate Orchidaceae"},
        excluded_interpretations=[
            {"note": "Must NOT show non-resupinate labellum position"},
            {"note": "Must NOT infer chemical pigment identity from colour"},
        ],
        relative_geometry_constraints={
            "labellum_position": "lowermost relative to floral axis",
            "column_position": "uppermost",
        },
        color_constraints={
            "class": "IMAGE_DERIVED",
            "note": "Colour shown may differ across taxa; no single colour is required",
        },
        literature_constraints=[],
        label_requirements=[
            {"structure": "Labellum", "required": True},
            {"structure": "Column", "required": True},
        ],
        uncertainty_notes=(
            "Developmental mechanism of torsion varies across Orchidaceae; "
            "illustration should not imply a single universal mechanism."
        ),
        generation_notes="[FIXTURE] Not a real figure specification",
        media_type=MediaType.STATIC_ILLUSTRATION,
        temporal_sequence=None,
        required_stage_order=None,
        motion_constraints=None,
        duration_range=None,
        loop_behavior=None,
        scientific_state_transitions=None,
        reduced_motion_alternative=None,
        created_by="fixture",
        review_state=VisionReviewState.MACHINE_GENERATED,
        version=1,
        provenance=_FIXTURE_PROVENANCE,
    )


def fixture_validation_run() -> FigureValidationRun:
    """Fixture FigureValidationRun with character-level conformance checks."""
    RC = ResupinationCharacters
    checks = (
        CharacterConformanceCheck(
            check_id=FIXTURE_CONFORMANCE_LABELLUM_ID,
            validation_run_id=FIXTURE_VALIDATION_RUN_ID,
            character_id=RC.CHARACTER_LABELLUM_POSITION,
            expected_state_or_range=RC.STATE_LABELLUM_LOWERMOST,
            observed_state_or_value=RC.STATE_LABELLUM_LOWERMOST,
            result=CharacterConformanceResult.PASS,
            confidence=0.88,
            notes="Labellum confirmed lowermost",
            review_state=VisionReviewState.MACHINE_GENERATED,
        ),
        CharacterConformanceCheck(
            check_id=FIXTURE_CONFORMANCE_ORIENTATION_ID,
            validation_run_id=FIXTURE_VALIDATION_RUN_ID,
            character_id=RC.CHARACTER_RESUPINATION_STATE,
            expected_state_or_range=RC.STATE_RESUPINATE,
            observed_state_or_value=RC.STATE_RESUPINATE,
            result=CharacterConformanceResult.PASS,
            confidence=0.87,
            notes="Resupination state confirmed",
            review_state=VisionReviewState.MACHINE_GENERATED,
        ),
    )
    return FigureValidationRun(
        validation_run_id=FIXTURE_VALIDATION_RUN_ID,
        asset_id="fixture-asset-001",
        figure_spec_id=FIXTURE_FIGURE_SPEC_ID,
        vision_analysis_id=FIXTURE_ANALYSIS_ID,
        status=ValidationRunStatus.COMPLETE,
        overall_review_state=VisionReviewState.MACHINE_GENERATED,
        provenance=_FIXTURE_PROVENANCE,
        conformance_checks=checks,
    )


def fixture_aggregate_summary() -> ReferenceSetAggregateSummary:
    """Fixture aggregate summary for the Resupination reference set."""
    RC = ResupinationCharacters
    return ReferenceSetAggregateSummary(
        reference_set_id=FIXTURE_REF_SET_ID,
        analysis_count=1,
        character_summaries=(
            CharacterStateSummary(
                character_id=RC.CHARACTER_RESUPINATION_STATE,
                sample_size=1,
                state_frequencies={RC.STATE_RESUPINATE: 1},
                cannot_determine_count=0,
                notes="FIXTURE data",
            ),
            CharacterStateSummary(
                character_id=RC.CHARACTER_LABELLUM_POSITION,
                sample_size=1,
                state_frequencies={RC.STATE_LABELLUM_LOWERMOST: 1},
                cannot_determine_count=0,
                notes="FIXTURE data",
            ),
        ),
        numeric_summaries=(
            NumericObservationSummary(
                character_id=RC.CHARACTER_TORSION_ANGLE,
                metric_type="RATIO",
                sample_size=1,
                median=0.67,
                min_value=0.67,
                max_value=0.67,
                range_note="Single fixture specimen",
                cannot_determine_count=0,
                contributing_analysis_ids=(FIXTURE_ANALYSIS_ID,),
            ),
        ),
        unresolved_count=0,
        provenance=_FIXTURE_PROVENANCE,
    )
