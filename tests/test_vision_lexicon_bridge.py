"""CALYX-VISION-LEXICON-BRIDGE-001 — Comprehensive test suite.

Tests cover the scientific safeguards and end-to-end Resupination pipeline.

Scientific safeguards tested:
- Uncalibrated images cannot emit absolute physical measurements.
- Calibrated images may emit absolute measurements when scale exists.
- Color phenotype does not become chemical pigment identity.
- Cannot-determine states are preserved.
- Duplicate analysis requests are handled safely (idempotency).
- Versioned re-analysis preserves prior records.
- Provenance is retained.
- Community review cannot auto-promote scientific truth.
- Resupination insufficient-orientation case returns CANNOT_DETERMINE.
- Resupination valid-orientation case returns RESUPINATE.
- Frontend evidence-summary contract is correct.
- Canonical concept linking is present on observations.
- Figure Specification creation works under governance.
- Character-level post-generation validation is inspectable.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.vision_lexicon.contracts import (
    AnalysisStatus,
    AssertionState,
    CalibrationState,
    CharacterConformanceResult,
    CharacterObservation,
    ColorPhenotypeClass,
    ColorPhenotypeObservation,
    ImageQualityState,
    MeasurementBasis,
    MediaType,
    MetricType,
    MorphometricObservation,
    ReviewDecision,
    ReviewerTier,
    ValidationRunStatus,
    VisionReviewRecord,
    VisionReviewState,
)
from app.vision_lexicon.persistence import MemoryVisionLexiconRepository
from app.vision_lexicon.resupination import (
    LABELLUM_CONCEPT_ID,
    RESUPINATION_CONCEPT_ID,
    ResupinationCharacters,
    fixture_aggregate_summary,
    fixture_character_observations,
    fixture_color_observation,
    fixture_figure_specification,
    fixture_morphometric_observations,
    fixture_reference_image_set,
    fixture_validation_run,
    fixture_vision_analysis,
    fixture_vision_regions,
    score_resupination_from_observation,
)
from app.vision_lexicon.service import VisionLexiconService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def repo():
    return MemoryVisionLexiconRepository()


@pytest.fixture()
def service(repo):
    return VisionLexiconService(repo)


# ---------------------------------------------------------------------------
# 1. Canonical concept linking
# ---------------------------------------------------------------------------


def test_character_observation_has_canonical_concept_id():
    obs_tuple = fixture_character_observations()
    assert len(obs_tuple) == 2
    labellum_obs = obs_tuple[0]
    assert labellum_obs.concept_id == LABELLUM_CONCEPT_ID
    assert labellum_obs.character_id == ResupinationCharacters.CHARACTER_LABELLUM_POSITION
    assert labellum_obs.character_state_id == ResupinationCharacters.STATE_LABELLUM_LOWERMOST


def test_resupination_state_observation_links_to_concept_id():
    obs_tuple = fixture_character_observations()
    resup_obs = obs_tuple[1]
    assert resup_obs.concept_id == RESUPINATION_CONCEPT_ID
    assert resup_obs.character_id == ResupinationCharacters.CHARACTER_RESUPINATION_STATE
    assert resup_obs.character_state_id == ResupinationCharacters.STATE_RESUPINATE


# ---------------------------------------------------------------------------
# 2. Uncalibrated images cannot emit absolute physical measurements
# ---------------------------------------------------------------------------


def test_absolute_length_blocked_on_uncalibrated_image():
    obs = MorphometricObservation(
        morphometric_id=uuid4(),
        analysis_id=uuid4(),
        region_id=None,
        metric_type=MetricType.ABSOLUTE_LENGTH,
        value=12.5,
        unit="mm",
        calibration_state=CalibrationState.UNCALIBRATED,
        calibration_basis=None,
        calibration_uncertainty=None,
        confidence=0.9,
        landmarks_used=None,
        provenance={},
    )
    with pytest.raises(ValueError, match="ABSOLUTE_DIMENSION_REQUIRES_CALIBRATION"):
        obs.validate()


def test_absolute_area_blocked_on_uncalibrated_image():
    obs = MorphometricObservation(
        morphometric_id=uuid4(),
        analysis_id=uuid4(),
        region_id=None,
        metric_type=MetricType.ABSOLUTE_AREA,
        value=3.14,
        unit="mm2",
        calibration_state=CalibrationState.UNCALIBRATED,
        calibration_basis=None,
        calibration_uncertainty=None,
        confidence=0.8,
        landmarks_used=None,
        provenance={},
    )
    with pytest.raises(ValueError, match="ABSOLUTE_DIMENSION_REQUIRES_CALIBRATION"):
        obs.validate()


def test_ratio_allowed_on_uncalibrated_image():
    obs = MorphometricObservation(
        morphometric_id=uuid4(),
        analysis_id=uuid4(),
        region_id=None,
        metric_type=MetricType.RATIO,
        value=0.67,
        unit="ratio",
        calibration_state=CalibrationState.UNCALIBRATED,
        calibration_basis=None,
        calibration_uncertainty=None,
        confidence=0.8,
        landmarks_used=None,
        provenance={},
    )
    obs.validate()  # must not raise


def test_angle_allowed_on_uncalibrated_image():
    obs = MorphometricObservation(
        morphometric_id=uuid4(),
        analysis_id=uuid4(),
        region_id=None,
        metric_type=MetricType.ANGLE,
        value=35.0,
        unit="angle_deg",
        calibration_state=CalibrationState.UNCALIBRATED,
        calibration_basis=None,
        calibration_uncertainty=None,
        confidence=0.85,
        landmarks_used=None,
        provenance={},
    )
    obs.validate()  # must not raise


# ---------------------------------------------------------------------------
# 3. Calibrated images may emit absolute measurements when scale exists
# ---------------------------------------------------------------------------


def test_absolute_length_allowed_on_calibrated_image():
    obs = MorphometricObservation(
        morphometric_id=uuid4(),
        analysis_id=uuid4(),
        region_id=None,
        metric_type=MetricType.ABSOLUTE_LENGTH,
        value=8.3,
        unit="mm",
        calibration_state=CalibrationState.SCALE_BAR_PRESENT,
        calibration_basis="1mm scale bar in image lower-right",
        calibration_uncertainty="±0.1mm",
        confidence=0.92,
        landmarks_used=None,
        provenance={},
    )
    obs.validate()  # must not raise


# ---------------------------------------------------------------------------
# 4. Character observation absolute unit blocked without calibration
# ---------------------------------------------------------------------------


def test_character_obs_absolute_unit_blocked_without_calibration():
    obs = CharacterObservation(
        observation_id=uuid4(),
        analysis_id=uuid4(),
        region_id=None,
        concept_id=None,
        character_id="labellum_length",
        character_state_id=None,
        numeric_value=5.0,
        unit="mm",
        relative_value=None,
        measurement_basis=MeasurementBasis.IMAGE_DERIVED,
        confidence=0.85,
        method=None,
        evidence_region=None,
        review_state=VisionReviewState.MACHINE_GENERATED,
        provenance={},
        limitations=(),
    )
    with pytest.raises(ValueError, match="ABSOLUTE_UNIT_REQUIRES_CALIBRATION"):
        obs.validate()


def test_character_obs_relative_unit_allowed_without_calibration():
    obs = CharacterObservation(
        observation_id=uuid4(),
        analysis_id=uuid4(),
        region_id=None,
        concept_id=None,
        character_id="labellum_length",
        character_state_id=None,
        numeric_value=0.67,
        unit="ratio",
        relative_value=None,
        measurement_basis=MeasurementBasis.IMAGE_DERIVED,
        confidence=0.85,
        method=None,
        evidence_region=None,
        review_state=VisionReviewState.MACHINE_GENERATED,
        provenance={},
        limitations=(),
    )
    obs.validate()  # must not raise


# ---------------------------------------------------------------------------
# 5. Color phenotype does not become chemical pigment identity
# ---------------------------------------------------------------------------


def test_color_observation_image_derived_requires_no_evidence_source():
    obs = ColorPhenotypeObservation(
        color_obs_id=uuid4(),
        analysis_id=uuid4(),
        region_id=None,
        phenotype_class=ColorPhenotypeClass.IMAGE_DERIVED,
        rgb_hex="#FF88AA",
        hsv_hue=350.0,
        hsv_saturation=0.46,
        hsv_value=1.0,
        lab_l=72.0,
        lab_a=25.0,
        lab_b=-2.0,
        pattern_description="pink",
        pigment_class=None,
        pigment_evidence_source=None,
        provenance={},
    )
    obs.validate()  # must not raise


def test_inferred_pigment_requires_evidence_source():
    obs = ColorPhenotypeObservation(
        color_obs_id=uuid4(),
        analysis_id=uuid4(),
        region_id=None,
        phenotype_class=ColorPhenotypeClass.INFERRED_PIGMENT_CLASS,
        rgb_hex=None,
        hsv_hue=None,
        hsv_saturation=None,
        hsv_value=None,
        lab_l=None,
        lab_a=None,
        lab_b=None,
        pattern_description=None,
        pigment_class="anthocyanin",
        pigment_evidence_source=None,  # missing!
        provenance={},
    )
    with pytest.raises(ValueError, match="PIGMENT_EVIDENCE_SOURCE_REQUIRED"):
        obs.validate()


def test_chemically_verified_requires_evidence_source():
    obs = ColorPhenotypeObservation(
        color_obs_id=uuid4(),
        analysis_id=uuid4(),
        region_id=None,
        phenotype_class=ColorPhenotypeClass.CHEMICALLY_VERIFIED,
        rgb_hex=None,
        hsv_hue=None,
        hsv_saturation=None,
        hsv_value=None,
        lab_l=None,
        lab_a=None,
        lab_b=None,
        pattern_description=None,
        pigment_class="cyanidin-3-glucoside",
        pigment_evidence_source=None,  # missing!
        provenance={},
    )
    with pytest.raises(ValueError, match="PIGMENT_EVIDENCE_SOURCE_REQUIRED"):
        obs.validate()


def test_chemically_verified_with_evidence_source_is_valid():
    obs = ColorPhenotypeObservation(
        color_obs_id=uuid4(),
        analysis_id=uuid4(),
        region_id=None,
        phenotype_class=ColorPhenotypeClass.CHEMICALLY_VERIFIED,
        rgb_hex=None,
        hsv_hue=None,
        hsv_saturation=None,
        hsv_value=None,
        lab_l=None,
        lab_a=None,
        lab_b=None,
        pattern_description=None,
        pigment_class="cyanidin-3-glucoside",
        pigment_evidence_source="HPLC analysis, Smith et al. 2023",
        provenance={},
    )
    obs.validate()  # must not raise


# ---------------------------------------------------------------------------
# 6. Cannot-determine states are preserved
# ---------------------------------------------------------------------------


def test_fixture_analysis_has_cannot_determine_status_accessible():
    fixture_vision_analysis()
    # Status can be CANNOT_DETERMINE — verify this is a valid value
    assert AnalysisStatus.CANNOT_DETERMINE == "CANNOT_DETERMINE"


def test_resupination_cropped_image_returns_cannot_determine():
    state, warnings = score_resupination_from_observation(
        labellum_position_state=ResupinationCharacters.STATE_LABELLUM_LOWERMOST,
        image_quality=ImageQualityState.CROPPED,
        developmental_stage_state=ResupinationCharacters.STATE_STAGE_ANTHESIS,
        orientation_context="lateral view",
    )
    assert state == ResupinationCharacters.STATE_RESUPINATION_CANNOT_DETERMINE
    assert any("CROPPED" in w or "INSUFFICIENT" in w for w in warnings)


def test_resupination_detached_specimen_returns_cannot_determine():
    state, _warnings = score_resupination_from_observation(
        labellum_position_state=None,
        image_quality=ImageQualityState.DETACHED_SPECIMEN,
        developmental_stage_state=None,
        orientation_context=None,
    )
    assert state == ResupinationCharacters.STATE_RESUPINATION_CANNOT_DETERMINE


def test_resupination_no_labellum_observation_returns_cannot_determine():
    state, warnings = score_resupination_from_observation(
        labellum_position_state=None,
        image_quality=ImageQualityState.ACCEPTABLE,
        developmental_stage_state=ResupinationCharacters.STATE_STAGE_ANTHESIS,
        orientation_context="lateral view",
    )
    assert state == ResupinationCharacters.STATE_RESUPINATION_CANNOT_DETERMINE
    assert any("LABELLUM" in w for w in warnings)


# ---------------------------------------------------------------------------
# 7. Duplicate analysis requests are handled safely (idempotency)
# ---------------------------------------------------------------------------


def test_duplicate_analysis_request_returns_same_record(service):
    kwargs = {
        "image_id": "image-001",
        "content_hash": "a" * 64,
        "reference_set_id": None,
        "vision_model": "fixture-model",
        "vision_model_version": "1.0",
        "taxon_context": None,
        "taxon_confidence": None,
        "calibration_state": CalibrationState.UNCALIBRATED,
        "image_quality": ImageQualityState.ACCEPTABLE,
        "warnings": [],
        "limitations": [],
    }
    first = service.request_analysis(**kwargs)
    second = service.request_analysis(**kwargs)
    assert first.analysis_id == second.analysis_id


# ---------------------------------------------------------------------------
# 8. Versioned re-analysis preserves prior records
# ---------------------------------------------------------------------------


def test_different_model_version_creates_new_record(service):
    base = {
        "image_id": "image-002",
        "content_hash": "b" * 64,
        "reference_set_id": None,
        "taxon_context": None,
        "taxon_confidence": None,
        "calibration_state": CalibrationState.UNCALIBRATED,
        "image_quality": ImageQualityState.ACCEPTABLE,
        "warnings": [],
        "limitations": [],
    }
    v1 = service.request_analysis(vision_model="m", vision_model_version="1.0", **base)
    v2 = service.request_analysis(vision_model="m", vision_model_version="2.0", **base)
    assert v1.analysis_id != v2.analysis_id
    # Both are retrievable
    assert service.get_analysis(v1.analysis_id) is not None
    assert service.get_analysis(v2.analysis_id) is not None


# ---------------------------------------------------------------------------
# 9. Provenance is retained
# ---------------------------------------------------------------------------


def test_reference_set_provenance_retained(service):
    rs = service.create_reference_set(
        title="Test Set",
        target_concept_id=RESUPINATION_CONCEPT_ID,
        taxon_scope=None,
        description=None,
        license_summary=None,
        notes=None,
        created_by="tester",
        items=[],
    )
    retrieved = service.get_reference_set(rs.reference_set_id)
    assert retrieved is not None
    assert "created_by" in retrieved.provenance
    assert retrieved.provenance["created_by"] == "tester"


def test_fixture_analysis_has_provenance():
    analysis = fixture_vision_analysis()
    assert analysis.provenance is not None


# ---------------------------------------------------------------------------
# 10. Community review cannot auto-promote scientific truth
# ---------------------------------------------------------------------------


def test_community_review_auto_promotion_blocked(service, repo):
    # Save a reference set so we have a valid subject
    rs = service.create_reference_set(
        title="Review Test",
        target_concept_id=None,
        taxon_scope=None,
        description=None,
        license_summary=None,
        notes=None,
        created_by="system",
        items=[],
    )
    review = service.record_review(
        subject_type="REFERENCE_SET",
        subject_id=rs.reference_set_id,
        reviewer_id="community-user-1",
        reviewer_tier=ReviewerTier.COMMUNITY,
        decision=ReviewDecision.APPROVE,
        scope_of_expertise=None,
        version_reviewed=None,
        questions_answered=[],
        comments="looks good",
        provenance={},
    )
    assert review.auto_promotion_blocked is True


def test_community_review_cannot_set_auto_promotion_false():
    with pytest.raises(ValueError, match="COMMUNITY_AUTO_PROMOTION_BLOCKED"):
        VisionReviewRecord(
            review_id=uuid4(),
            subject_type="ANALYSIS",
            subject_id=uuid4(),
            reviewer_id="user-1",
            reviewer_tier=ReviewerTier.COMMUNITY,
            decision=ReviewDecision.APPROVE,
            scope_of_expertise=None,
            version_reviewed=None,
            questions_answered=[],
            comments=None,
            auto_promotion_blocked=False,  # VIOLATION
            provenance={},
        ).validate()


def test_expert_review_allows_auto_promotion_false():
    """Expert reviews are not blocked from auto_promotion_blocked=False
    (governance is handled at the publication layer, not here)."""
    review = VisionReviewRecord(
        review_id=uuid4(),
        subject_type="ANALYSIS",
        subject_id=uuid4(),
        reviewer_id="dr-smith",
        reviewer_tier=ReviewerTier.EXPERT,
        decision=ReviewDecision.APPROVE,
        scope_of_expertise="Orchid morphology",
        version_reviewed=1,
        questions_answered=[],
        comments=None,
        auto_promotion_blocked=False,
        provenance={},
    )
    review.validate()  # must not raise


# ---------------------------------------------------------------------------
# 11. Resupination reference implementation — full pipeline
# ---------------------------------------------------------------------------


def test_fixture_reference_pipeline_valid():
    """Exercise the complete Resupination fixture pipeline end-to-end."""
    ref_set = fixture_reference_image_set()
    ref_set.validate()
    assert ref_set.target_concept_id == RESUPINATION_CONCEPT_ID
    assert len(ref_set.items) == 1

    analysis = fixture_vision_analysis()
    analysis.validate()
    assert analysis.calibration_state == CalibrationState.UNCALIBRATED
    assert analysis.review_state == VisionReviewState.MACHINE_GENERATED

    regions = fixture_vision_regions()
    for region in regions:
        region.validate()
    assert any(r.concept_id == LABELLUM_CONCEPT_ID for r in regions)

    observations = fixture_character_observations()
    for obs in observations:
        obs.validate()

    morphometrics = fixture_morphometric_observations()
    for m in morphometrics:
        m.validate()
        # Uncalibrated fixture must NOT use absolute dimensions
        assert not m.metric_type.requires_calibration()

    color_obs = fixture_color_observation()
    color_obs.validate()
    assert color_obs.phenotype_class == ColorPhenotypeClass.IMAGE_DERIVED

    assertion = fixture_validation_run()
    assertion.validate()
    assert assertion.status == ValidationRunStatus.COMPLETE
    checks = assertion.conformance_checks
    assert len(checks) >= 2
    for check in checks:
        check.validate()
        assert check.result in (
            CharacterConformanceResult.PASS,
            CharacterConformanceResult.PARTIAL,
            CharacterConformanceResult.FAIL,
            CharacterConformanceResult.CANNOT_DETERMINE,
        )

    figure_spec = fixture_figure_specification()
    figure_spec.validate()
    assert figure_spec.target_concept_id == RESUPINATION_CONCEPT_ID
    assert len(figure_spec.required_structures) >= 2

    aggregate = fixture_aggregate_summary()
    assert aggregate.analysis_count == 1
    assert len(aggregate.character_summaries) >= 1


def test_fixture_analysis_review_state_is_machine_generated():
    analysis = fixture_vision_analysis()
    assert analysis.review_state == VisionReviewState.MACHINE_GENERATED
    assert analysis.review_state.is_machine_only()


def test_fixture_assertion_is_machine_candidate():
    from app.vision_lexicon.resupination import fixture_vision_assertion

    assertion = fixture_vision_assertion()
    assertion.validate()
    assert assertion.assertion_state == AssertionState.MACHINE_CANDIDATE


# ---------------------------------------------------------------------------
# 12. Resupination scoring — valid orientation → RESUPINATE
# ---------------------------------------------------------------------------


def test_resupination_valid_labellum_lowermost():
    RC = ResupinationCharacters
    state, warnings = score_resupination_from_observation(
        labellum_position_state=RC.STATE_LABELLUM_LOWERMOST,
        image_quality=ImageQualityState.ACCEPTABLE,
        developmental_stage_state=RC.STATE_STAGE_ANTHESIS,
        orientation_context="lateral view, stem intact",
    )
    assert state == RC.STATE_RESUPINATE
    assert not warnings  # no warnings for clean case


def test_resupination_valid_labellum_uppermost_nonresupinate():
    RC = ResupinationCharacters
    state, _warnings = score_resupination_from_observation(
        labellum_position_state=RC.STATE_LABELLUM_UPPERMOST,
        image_quality=ImageQualityState.ACCEPTABLE,
        developmental_stage_state=RC.STATE_STAGE_ANTHESIS,
        orientation_context="front view, natural orientation",
    )
    assert state == RC.STATE_NON_RESUPINATE


def test_resupination_missing_orientation_context_adds_warning():
    RC = ResupinationCharacters
    state, warnings = score_resupination_from_observation(
        labellum_position_state=RC.STATE_LABELLUM_LOWERMOST,
        image_quality=ImageQualityState.ACCEPTABLE,
        developmental_stage_state=None,
        orientation_context=None,
    )
    assert state == RC.STATE_RESUPINATE
    assert any("ORIENTATION_CONTEXT_MISSING" in w for w in warnings)


def test_resupination_pre_anthesis_adds_warning():
    RC = ResupinationCharacters
    _state, warnings = score_resupination_from_observation(
        labellum_position_state=RC.STATE_LABELLUM_LOWERMOST,
        image_quality=ImageQualityState.ACCEPTABLE,
        developmental_stage_state=RC.STATE_STAGE_PRE_ANTHESIS,
        orientation_context="lateral view",
    )
    # Scoring still succeeds but warns about developmental stage
    assert any("NON_ANTHESIS_STAGE" in w for w in warnings)


def test_resupination_lateral_ambiguous_returns_cannot_determine():
    RC = ResupinationCharacters
    state, warnings = score_resupination_from_observation(
        labellum_position_state=RC.STATE_LABELLUM_LATERAL,
        image_quality=ImageQualityState.ACCEPTABLE,
        developmental_stage_state=RC.STATE_STAGE_ANTHESIS,
        orientation_context="lateral view",
    )
    assert state == RC.STATE_RESUPINATION_CANNOT_DETERMINE
    assert any("AMBIGUOUS" in w or "LABELLUM" in w for w in warnings)


# ---------------------------------------------------------------------------
# 13. Figure Specification creation
# ---------------------------------------------------------------------------


def test_figure_spec_creation_via_service(service):
    spec = service.create_figure_spec(
        target_concept_id=RESUPINATION_CONCEPT_ID,
        purpose="Illustrate resupination in representative Orchidaceae",
        scope="MORPHOLOGICAL_ILLUSTRATION",
        taxon_scope="Orchidaceae",
        reference_set_ids=[],
        required_structures=[{"label": "Labellum"}],
        required_character_states=[],
        required_relationships=[],
        allowed_variation={},
        excluded_interpretations=[],
        relative_geometry_constraints={},
        color_constraints={},
        literature_constraints=[],
        label_requirements=[],
        uncertainty_notes=None,
        generation_notes=None,
        media_type=MediaType.STATIC_ILLUSTRATION,
        created_by="test-user",
        provenance={"test": True},
    )
    assert spec.figure_spec_id is not None
    assert spec.review_state == VisionReviewState.MACHINE_GENERATED
    assert spec.version == 1
    assert spec.target_concept_id == RESUPINATION_CONCEPT_ID


def test_figure_spec_purpose_required(service):
    with pytest.raises(ValueError, match="purpose"):
        service.create_figure_spec(
            target_concept_id=None,
            purpose="",  # invalid
            scope="MORPHOLOGICAL_ILLUSTRATION",
            taxon_scope=None,
            reference_set_ids=[],
            required_structures=[],
            required_character_states=[],
            required_relationships=[],
            allowed_variation={},
            excluded_interpretations=[],
            relative_geometry_constraints={},
            color_constraints={},
            literature_constraints=[],
            label_requirements=[],
            uncertainty_notes=None,
            generation_notes=None,
            media_type=MediaType.STATIC_ILLUSTRATION,
            created_by="test",
            provenance={},
        )


# ---------------------------------------------------------------------------
# 14. Character-level post-generation validation
# ---------------------------------------------------------------------------


def test_validation_run_has_character_level_checks():
    run = fixture_validation_run()
    assert run.conformance_checks
    character_ids = {c.character_id for c in run.conformance_checks}
    assert ResupinationCharacters.CHARACTER_LABELLUM_POSITION in character_ids
    assert ResupinationCharacters.CHARACTER_RESUPINATION_STATE in character_ids


def test_character_conformance_cannot_determine_is_preserved():
    """CANNOT_DETERMINE must remain a first-class result."""
    check_value = CharacterConformanceResult("CANNOT_DETERMINE")
    assert check_value == CharacterConformanceResult.CANNOT_DETERMINE


def test_validation_run_creation_via_service(service):
    run = service.create_validation_run(
        asset_id="test-asset-1",
        figure_spec_id=None,
        vision_analysis_id=None,
        provenance={"test": True},
    )
    assert run.validation_run_id is not None
    assert run.status == ValidationRunStatus.PENDING
    assert run.overall_review_state == VisionReviewState.MACHINE_GENERATED


# ---------------------------------------------------------------------------
# 15. Frontend evidence-summary contract
# ---------------------------------------------------------------------------


def test_evidence_summary_contract(service):
    # Seed a reference set and analysis
    rs = service.create_reference_set(
        title="Evidence Test Set",
        target_concept_id=RESUPINATION_CONCEPT_ID,
        taxon_scope="Orchidaceae",
        description=None,
        license_summary=None,
        notes=None,
        created_by="test",
        items=[
            {
                "image_id": "img-contract-001",
                "calibration_status": "UNCALIBRATED",
                "image_quality_state": "ACCEPTABLE",
            }
        ],
    )
    analysis = service.request_analysis(
        image_id="img-contract-001",
        content_hash="c" * 64,
        reference_set_id=rs.reference_set_id,
        vision_model="fixture",
        vision_model_version="1.0",
        taxon_context=None,
        taxon_confidence=None,
        calibration_state=CalibrationState.UNCALIBRATED,
        image_quality=ImageQualityState.ACCEPTABLE,
        warnings=[],
        limitations=["Uncalibrated image"],
    )
    service.record_character_observation(
        analysis_id=analysis.analysis_id,
        region_id=None,
        concept_id=RESUPINATION_CONCEPT_ID,
        character_id=ResupinationCharacters.CHARACTER_RESUPINATION_STATE,
        character_state_id=ResupinationCharacters.STATE_RESUPINATE,
        numeric_value=None,
        unit=None,
        relative_value=None,
        measurement_basis=MeasurementBasis.IMAGE_DERIVED,
        confidence=0.88,
        method=None,
        evidence_region=None,
        provenance={},
        limitations=[],
    )

    summary = service.get_evidence_summary(RESUPINATION_CONCEPT_ID)

    assert "concept_id" in summary
    assert "reference_sets" in summary
    assert "reference_images" in summary
    assert "vision_observations" in summary
    assert "morphometrics" in summary
    assert "aggregate_summary" in summary
    assert "figure_specifications" in summary
    assert "visual_assets" in summary
    assert "validation_runs" in summary
    assert "review_state" in summary
    assert "provenance" in summary
    assert "limitations" in summary

    assert len(summary["reference_sets"]) == 1
    assert len(summary["vision_observations"]) == 1
    obs = summary["vision_observations"][0]
    assert obs["character_id"] == ResupinationCharacters.CHARACTER_RESUPINATION_STATE
    assert obs["character_state_id"] == ResupinationCharacters.STATE_RESUPINATE


# ---------------------------------------------------------------------------
# 16. Reference set aggregation
# ---------------------------------------------------------------------------


def test_aggregate_summary_preserves_cannot_determine_count(service):
    rs = service.create_reference_set(
        title="Agg Test",
        target_concept_id=RESUPINATION_CONCEPT_ID,
        taxon_scope=None,
        description=None,
        license_summary=None,
        notes=None,
        created_by="test",
        items=[{"image_id": "agg-img-001"}],
    )
    analysis = service.request_analysis(
        image_id="agg-img-001",
        content_hash="d" * 64,
        reference_set_id=rs.reference_set_id,
        vision_model="m",
        vision_model_version="1.0",
        taxon_context=None,
        taxon_confidence=None,
        calibration_state=CalibrationState.UNCALIBRATED,
        image_quality=ImageQualityState.CROPPED,
        warnings=[],
        limitations=[],
    )
    # Record a CANNOT_DETERMINE observation
    service.record_character_observation(
        analysis_id=analysis.analysis_id,
        region_id=None,
        concept_id=None,
        character_id=ResupinationCharacters.CHARACTER_RESUPINATION_STATE,
        character_state_id="CANNOT_DETERMINE",
        numeric_value=None,
        unit=None,
        relative_value=None,
        measurement_basis=MeasurementBasis.CANNOT_DETERMINE,
        confidence=0.0,
        method=None,
        evidence_region=None,
        provenance={},
        limitations=["Image cropped — orientation not determinable"],
    )

    summary = service.aggregate_reference_set(rs.reference_set_id)
    assert summary["unresolved_count"] >= 1
    char_summary = next(
        (c for c in summary["character_summaries"]
         if c["character_id"] == ResupinationCharacters.CHARACTER_RESUPINATION_STATE),
        None,
    )
    assert char_summary is not None
    assert char_summary["cannot_determine_count"] >= 1


# ---------------------------------------------------------------------------
# 17. Capability status
# ---------------------------------------------------------------------------


def test_capability_status_truthful():
    from app.vision_lexicon.service import vision_lexicon_capability_status
    status = vision_lexicon_capability_status()
    assert status["live_inference_enabled"] is False
    assert status["safeguards"]["uncalibrated_absolute_dimensions_blocked"] is True
    assert status["safeguards"]["community_review_auto_promotion_blocked"] is True
    assert status["safeguards"]["automatic_publication"] is False
    assert len(status["remaining_external_dependencies"]) >= 1
