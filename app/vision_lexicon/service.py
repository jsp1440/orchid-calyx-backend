"""Vision-Lexicon bridge service layer.

Enforces scientific safeguards:
- Idempotency: duplicate analysis requests return the existing record.
- Calibration: absolute morphometric units require calibrated images.
- Color / pigment separation: Vision-only observations are always IMAGE_DERIVED.
- Cannot-determine states are preserved, never silently upgraded.
- Machine outputs remain MACHINE_GENERATED until a human review record exists.
- Community review cannot automatically promote to scientific truth.

Database persistence is delegated to the repository.  This service is
usable independently of a live Vision provider.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from .contracts import (
    AnalysisStatus,
    CalibrationState,
    CharacterConformanceCheck,
    CharacterConformanceResult,
    CharacterObservation,
    ColorPhenotypeClass,
    ColorPhenotypeObservation,
    FigureSpecification,
    FigureValidationRun,
    ImageQualityState,
    MeasurementBasis,
    MediaType,
    MetricType,
    MorphometricObservation,
    ReferenceImageSet,
    ReferenceImageSetItem,
    ReviewDecision,
    ReviewerTier,
    ValidationRunStatus,
    VisionAnalysisRecord,
    VisionRegion,
    VisionReviewRecord,
    VisionReviewState,
)


class VisionLexiconError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _stable_request_hash(image_id: str, content_hash: str, model: str, version: str) -> str:
    """Stable, idempotent hash for a Vision analysis request."""
    payload = json.dumps(
        {"image_id": image_id, "content_hash": content_hash, "model": model, "version": version},
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


class VisionLexiconService:
    """Orchestrates the Vision-Lexicon pipeline operations.

    Constructor is inert; no connection is opened at import time.
    """

    def __init__(self, repository: Any) -> None:
        self._repo = repository

    # ------------------------------------------------------------------
    # Reference Image Sets
    # ------------------------------------------------------------------

    def create_reference_set(
        self,
        *,
        title: str,
        target_concept_id: UUID | None,
        taxon_scope: str | None,
        description: str | None,
        license_summary: str | None,
        notes: str | None,
        created_by: str,
        items: list[dict[str, Any]],
    ) -> ReferenceImageSet:
        if not title.strip():
            raise VisionLexiconError("TITLE_REQUIRED", "Reference set title is required.")
        if not created_by.strip():
            raise VisionLexiconError("CREATOR_REQUIRED", "Creator identity is required.")

        set_id = uuid4()
        built_items: list[ReferenceImageSetItem] = []
        for item_data in items:
            item = ReferenceImageSetItem(
                reference_set_item_id=uuid4(),
                reference_set_id=set_id,
                image_id=item_data["image_id"],
                media_id=item_data.get("media_id"),
                taxon_id=item_data.get("taxon_id"),
                taxon_confidence=item_data.get("taxon_confidence"),
                developmental_stage=item_data.get("developmental_stage"),
                orientation_context=item_data.get("orientation_context"),
                calibration_status=CalibrationState(
                    item_data.get("calibration_status", CalibrationState.UNCALIBRATED)
                ),
                scale_information=item_data.get("scale_information"),
                image_quality_state=ImageQualityState(
                    item_data.get("image_quality_state", ImageQualityState.UNKNOWN)
                ),
                source=item_data.get("source"),
                license=item_data.get("license"),
                provenance=item_data.get("provenance", {}),
                inclusion_reason=item_data.get("inclusion_reason"),
                review_state=VisionReviewState.MACHINE_GENERATED,
            )
            item.validate()
            built_items.append(item)

        ref_set = ReferenceImageSet(
            reference_set_id=set_id,
            title=title.strip(),
            target_concept_id=target_concept_id,
            taxon_scope=taxon_scope,
            description=description,
            created_by=created_by,
            review_state=VisionReviewState.MACHINE_GENERATED,
            provenance={
                "created_at": datetime.now(UTC).isoformat(),
                "created_by": created_by,
            },
            license_summary=license_summary,
            notes=notes,
            items=tuple(built_items),
        )
        ref_set.validate()
        return self._repo.save_reference_set(ref_set)

    def get_reference_set(self, reference_set_id: UUID) -> ReferenceImageSet | None:
        return self._repo.get_reference_set(reference_set_id)

    def list_reference_sets_for_concept(
        self, concept_id: UUID
    ) -> list[ReferenceImageSet]:
        return self._repo.list_reference_sets_for_concept(concept_id)

    # ------------------------------------------------------------------
    # Vision Analyses
    # ------------------------------------------------------------------

    def request_analysis(
        self,
        *,
        image_id: str,
        content_hash: str,
        reference_set_id: UUID | None,
        vision_model: str,
        vision_model_version: str,
        taxon_context: str | None,
        taxon_confidence: float | None,
        calibration_state: CalibrationState,
        image_quality: ImageQualityState,
        warnings: list[str],
        limitations: list[str],
    ) -> VisionAnalysisRecord:
        """Idempotent: returns existing record if an identical request was
        previously submitted, rather than creating a duplicate."""
        request_hash = _stable_request_hash(
            image_id, content_hash, vision_model, vision_model_version
        )

        existing = self._repo.get_analysis_by_request_hash(request_hash)
        if existing is not None:
            return existing

        analysis = VisionAnalysisRecord(
            analysis_id=uuid4(),
            image_id=image_id,
            content_hash=content_hash,
            reference_set_id=reference_set_id,
            vision_model=vision_model,
            vision_model_version=vision_model_version,
            analysis_version=1,
            taxon_context=taxon_context,
            taxon_confidence=taxon_confidence,
            calibration_state=calibration_state,
            image_quality=image_quality,
            analysis_status=AnalysisStatus.PENDING,
            review_state=VisionReviewState.MACHINE_GENERATED,
            provenance={"created_at": datetime.now(UTC).isoformat()},
            warnings=tuple(warnings),
            limitations=tuple(limitations),
            request_hash=request_hash,
        )
        analysis.validate()
        return self._repo.save_analysis(analysis)

    def get_analysis(self, analysis_id: UUID) -> VisionAnalysisRecord | None:
        return self._repo.get_analysis(analysis_id)

    def list_analyses_for_image(self, image_id: str) -> list[VisionAnalysisRecord]:
        return self._repo.list_analyses_for_image(image_id)

    # ------------------------------------------------------------------
    # Regions
    # ------------------------------------------------------------------

    def record_region(
        self,
        *,
        analysis_id: UUID,
        concept_id: UUID | None,
        label: str,
        bounding_box: dict[str, Any] | None,
        segmentation_ref: str | None,
        landmarks: list[dict[str, Any]] | None,
        confidence: float | None,
        provenance: dict[str, Any],
    ) -> VisionRegion:
        region = VisionRegion(
            region_id=uuid4(),
            analysis_id=analysis_id,
            concept_id=concept_id,
            label=label,
            bounding_box=bounding_box,
            segmentation_ref=segmentation_ref,
            landmarks=landmarks,
            confidence=confidence,
            review_state=VisionReviewState.MACHINE_GENERATED,
            provenance=provenance,
        )
        region.validate()
        return self._repo.save_region(region)

    def get_region(self, region_id: UUID) -> VisionRegion | None:
        return self._repo.get_region(region_id)

    def list_regions_for_analysis(self, analysis_id: UUID) -> list[VisionRegion]:
        return self._repo.list_regions_for_analysis(analysis_id)

    # ------------------------------------------------------------------
    # Character Observations
    # ------------------------------------------------------------------

    def record_character_observation(
        self,
        *,
        analysis_id: UUID,
        region_id: UUID | None,
        concept_id: UUID | None,
        character_id: str,
        character_state_id: str | None,
        numeric_value: float | None,
        unit: str | None,
        relative_value: float | None,
        measurement_basis: MeasurementBasis,
        confidence: float,
        method: str | None,
        evidence_region: str | None,
        provenance: dict[str, Any],
        limitations: list[str],
    ) -> CharacterObservation:
        obs = CharacterObservation(
            observation_id=uuid4(),
            analysis_id=analysis_id,
            region_id=region_id,
            concept_id=concept_id,
            character_id=character_id,
            character_state_id=character_state_id,
            numeric_value=numeric_value,
            unit=unit,
            relative_value=relative_value,
            measurement_basis=measurement_basis,
            confidence=confidence,
            method=method,
            evidence_region=evidence_region,
            review_state=VisionReviewState.MACHINE_GENERATED,
            provenance=provenance,
            limitations=tuple(limitations),
        )
        obs.validate()
        return self._repo.save_character_observation(obs)

    def list_observations_for_analysis(
        self, analysis_id: UUID
    ) -> list[CharacterObservation]:
        return self._repo.list_observations_for_analysis(analysis_id)

    # ------------------------------------------------------------------
    # Morphometric Observations
    # ------------------------------------------------------------------

    def record_morphometric(
        self,
        *,
        analysis_id: UUID,
        region_id: UUID | None,
        metric_type: MetricType,
        value: float,
        unit: str | None,
        calibration_state: CalibrationState,
        calibration_basis: str | None,
        calibration_uncertainty: str | None,
        confidence: float | None,
        landmarks_used: list[dict[str, Any]] | None,
        provenance: dict[str, Any],
    ) -> MorphometricObservation:
        obs = MorphometricObservation(
            morphometric_id=uuid4(),
            analysis_id=analysis_id,
            region_id=region_id,
            metric_type=metric_type,
            value=value,
            unit=unit,
            calibration_state=calibration_state,
            calibration_basis=calibration_basis,
            calibration_uncertainty=calibration_uncertainty,
            confidence=confidence,
            landmarks_used=landmarks_used,
            provenance=provenance,
        )
        obs.validate()
        return self._repo.save_morphometric(obs)

    def list_morphometrics_for_analysis(
        self, analysis_id: UUID
    ) -> list[MorphometricObservation]:
        return self._repo.list_morphometrics_for_analysis(analysis_id)

    # ------------------------------------------------------------------
    # Color Phenotype Observations
    # ------------------------------------------------------------------

    def record_color_phenotype(
        self,
        *,
        analysis_id: UUID,
        region_id: UUID | None,
        phenotype_class: ColorPhenotypeClass,
        rgb_hex: str | None,
        hsv_hue: float | None,
        hsv_saturation: float | None,
        hsv_value: float | None,
        lab_l: float | None,
        lab_a: float | None,
        lab_b: float | None,
        pattern_description: str | None,
        pigment_class: str | None,
        pigment_evidence_source: str | None,
        provenance: dict[str, Any],
    ) -> ColorPhenotypeObservation:
        obs = ColorPhenotypeObservation(
            color_obs_id=uuid4(),
            analysis_id=analysis_id,
            region_id=region_id,
            phenotype_class=phenotype_class,
            rgb_hex=rgb_hex,
            hsv_hue=hsv_hue,
            hsv_saturation=hsv_saturation,
            hsv_value=hsv_value,
            lab_l=lab_l,
            lab_a=lab_a,
            lab_b=lab_b,
            pattern_description=pattern_description,
            pigment_class=pigment_class,
            pigment_evidence_source=pigment_evidence_source,
            provenance=provenance,
        )
        obs.validate()
        return self._repo.save_color_observation(obs)

    # ------------------------------------------------------------------
    # Figure Specifications
    # ------------------------------------------------------------------

    def create_figure_spec(
        self,
        *,
        target_concept_id: UUID | None,
        purpose: str,
        scope: str,
        taxon_scope: str | None,
        reference_set_ids: list[UUID],
        required_structures: list[dict[str, Any]],
        required_character_states: list[dict[str, Any]],
        required_relationships: list[dict[str, Any]],
        allowed_variation: dict[str, Any],
        excluded_interpretations: list[dict[str, Any]],
        relative_geometry_constraints: dict[str, Any],
        color_constraints: dict[str, Any],
        literature_constraints: list[dict[str, Any]],
        label_requirements: list[dict[str, Any]],
        uncertainty_notes: str | None,
        generation_notes: str | None,
        media_type: MediaType,
        created_by: str,
        provenance: dict[str, Any],
        temporal_sequence: list[dict[str, Any]] | None = None,
        required_stage_order: list[str] | None = None,
        motion_constraints: dict[str, Any] | None = None,
        duration_range: dict[str, Any] | None = None,
        loop_behavior: str | None = None,
        scientific_state_transitions: list[dict[str, Any]] | None = None,
        reduced_motion_alternative: str | None = None,
    ) -> FigureSpecification:
        spec = FigureSpecification(
            figure_spec_id=uuid4(),
            target_concept_id=target_concept_id,
            purpose=purpose,
            scope=scope,
            taxon_scope=taxon_scope,
            reference_set_ids=tuple(reference_set_ids),
            required_structures=required_structures,
            required_character_states=required_character_states,
            required_relationships=required_relationships,
            allowed_variation=allowed_variation,
            excluded_interpretations=excluded_interpretations,
            relative_geometry_constraints=relative_geometry_constraints,
            color_constraints=color_constraints,
            literature_constraints=literature_constraints,
            label_requirements=label_requirements,
            uncertainty_notes=uncertainty_notes,
            generation_notes=generation_notes,
            media_type=media_type,
            temporal_sequence=temporal_sequence,
            required_stage_order=required_stage_order,
            motion_constraints=motion_constraints,
            duration_range=duration_range,
            loop_behavior=loop_behavior,
            scientific_state_transitions=scientific_state_transitions,
            reduced_motion_alternative=reduced_motion_alternative,
            created_by=created_by,
            review_state=VisionReviewState.MACHINE_GENERATED,
            version=1,
            provenance=provenance,
        )
        spec.validate()
        return self._repo.save_figure_spec(spec)

    def get_figure_spec(self, figure_spec_id: UUID) -> FigureSpecification | None:
        return self._repo.get_figure_spec(figure_spec_id)

    # ------------------------------------------------------------------
    # Validation Runs
    # ------------------------------------------------------------------

    def create_validation_run(
        self,
        *,
        asset_id: str,
        figure_spec_id: UUID | None,
        vision_analysis_id: UUID | None,
        provenance: dict[str, Any],
    ) -> FigureValidationRun:
        run = FigureValidationRun(
            validation_run_id=uuid4(),
            asset_id=asset_id,
            figure_spec_id=figure_spec_id,
            vision_analysis_id=vision_analysis_id,
            status=ValidationRunStatus.PENDING,
            overall_review_state=VisionReviewState.MACHINE_GENERATED,
            provenance=provenance,
            conformance_checks=(),
        )
        run.validate()
        return self._repo.save_validation_run(run)

    def record_conformance_checks(
        self,
        *,
        validation_run_id: UUID,
        checks: list[dict[str, Any]],
    ) -> list[CharacterConformanceCheck]:
        built: list[CharacterConformanceCheck] = []
        for check_data in checks:
            check = CharacterConformanceCheck(
                check_id=uuid4(),
                validation_run_id=validation_run_id,
                character_id=check_data["character_id"],
                expected_state_or_range=check_data.get("expected_state_or_range"),
                observed_state_or_value=check_data.get("observed_state_or_value"),
                result=CharacterConformanceResult(check_data["result"]),
                confidence=check_data.get("confidence"),
                notes=check_data.get("notes"),
                review_state=VisionReviewState.MACHINE_GENERATED,
            )
            check.validate()
            built.append(check)
        return self._repo.save_conformance_checks(built)

    def get_validation_run(
        self, validation_run_id: UUID
    ) -> FigureValidationRun | None:
        return self._repo.get_validation_run(validation_run_id)

    # ------------------------------------------------------------------
    # Human Review
    # ------------------------------------------------------------------

    def record_review(
        self,
        *,
        subject_type: str,
        subject_id: UUID,
        reviewer_id: str,
        reviewer_tier: ReviewerTier,
        decision: ReviewDecision,
        scope_of_expertise: str | None,
        version_reviewed: int | None,
        questions_answered: list[dict[str, Any]],
        comments: str | None,
        provenance: dict[str, Any],
    ) -> VisionReviewRecord:
        auto_blocked = reviewer_tier == ReviewerTier.COMMUNITY
        review = VisionReviewRecord(
            review_id=uuid4(),
            subject_type=subject_type,
            subject_id=subject_id,
            reviewer_id=reviewer_id,
            reviewer_tier=reviewer_tier,
            decision=decision,
            scope_of_expertise=scope_of_expertise,
            version_reviewed=version_reviewed,
            questions_answered=questions_answered,
            comments=comments,
            auto_promotion_blocked=auto_blocked,
            provenance=provenance,
        )
        review.validate()
        return self._repo.save_review(review)

    # ------------------------------------------------------------------
    # Aggregate Summary
    # ------------------------------------------------------------------

    def aggregate_reference_set(self, reference_set_id: UUID) -> dict[str, Any]:
        """Return a summary of observations across all analyses in a reference set.

        Cannot-determine observations are counted and surfaced, never hidden.
        """
        analyses = self._repo.list_analyses_for_reference_set(reference_set_id)
        if not analyses:
            return {
                "reference_set_id": str(reference_set_id),
                "analysis_count": 0,
                "character_summaries": [],
                "numeric_summaries": [],
                "unresolved_count": 0,
            }

        all_obs: list[CharacterObservation] = []
        for analysis in analyses:
            all_obs.extend(
                self._repo.list_observations_for_analysis(analysis.analysis_id)
            )

        from collections import defaultdict

        char_states: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        cannot_det: dict[str, int] = defaultdict(int)

        for obs in all_obs:
            if obs.character_state_id == "CANNOT_DETERMINE":
                cannot_det[obs.character_id] += 1
            elif obs.character_state_id is not None:
                char_states[obs.character_id][obs.character_state_id] += 1
            else:
                cannot_det[obs.character_id] += 1

        character_summaries = []
        for char_id, state_freqs in char_states.items():
            character_summaries.append({
                "character_id": char_id,
                "sample_size": sum(state_freqs.values()) + cannot_det.get(char_id, 0),
                "state_frequencies": dict(state_freqs),
                "cannot_determine_count": cannot_det.get(char_id, 0),
            })
        for char_id, cd_count in cannot_det.items():
            if char_id not in char_states:
                character_summaries.append({
                    "character_id": char_id,
                    "sample_size": cd_count,
                    "state_frequencies": {},
                    "cannot_determine_count": cd_count,
                })

        return {
            "reference_set_id": str(reference_set_id),
            "analysis_count": len(analyses),
            "character_summaries": character_summaries,
            "numeric_summaries": [],
            "unresolved_count": sum(cannot_det.values()),
        }

    # ------------------------------------------------------------------
    # Frontend Evidence Summary
    # ------------------------------------------------------------------

    def get_evidence_summary(self, concept_id: UUID) -> dict[str, Any]:
        """Build the frontend-readable evidence summary for a concept."""
        reference_sets = self.list_reference_sets_for_concept(concept_id)
        analyses: list[VisionAnalysisRecord] = []
        all_observations: list[dict[str, Any]] = []
        all_morphometrics: list[dict[str, Any]] = []

        for ref_set in reference_sets:
            for item in ref_set.items:
                for analysis in self.list_analyses_for_image(item.image_id):
                    analyses.append(analysis)
                    for obs in self.list_observations_for_analysis(analysis.analysis_id):
                        all_observations.append({
                            "observation_id": str(obs.observation_id),
                            "character_id": obs.character_id,
                            "character_state_id": obs.character_state_id,
                            "concept_id": str(obs.concept_id) if obs.concept_id else None,
                            "confidence": obs.confidence,
                            "review_state": obs.review_state,
                            "limitations": list(obs.limitations),
                        })
                    for m in self.list_morphometrics_for_analysis(analysis.analysis_id):
                        all_morphometrics.append({
                            "morphometric_id": str(m.morphometric_id),
                            "metric_type": m.metric_type,
                            "value": m.value,
                            "unit": m.unit,
                            "calibration_state": m.calibration_state,
                        })

        aggregate = (
            self.aggregate_reference_set(reference_sets[0].reference_set_id)
            if reference_sets
            else None
        )

        review_states = {a.review_state for a in analyses}
        summary_review_state = (
            VisionReviewState.APPROVED
            if review_states == {VisionReviewState.APPROVED}
            else VisionReviewState.MACHINE_GENERATED
        )

        limitations: list[str] = []
        for analysis in analyses:
            limitations.extend(analysis.limitations)
        limitations = list(dict.fromkeys(limitations))

        return {
            "concept_id": str(concept_id),
            "concept_label": None,
            "reference_sets": [
                {"reference_set_id": str(rs.reference_set_id), "title": rs.title}
                for rs in reference_sets
            ],
            "reference_images": [
                {
                    "image_id": item.image_id,
                    "calibration_status": item.calibration_status,
                    "image_quality_state": item.image_quality_state,
                    "review_state": item.review_state,
                }
                for rs in reference_sets
                for item in rs.items
            ],
            "vision_observations": all_observations,
            "morphometrics": all_morphometrics,
            "aggregate_summary": aggregate,
            "figure_specifications": [],
            "visual_assets": [],
            "validation_runs": [],
            "review_state": summary_review_state,
            "provenance": {"concept_id": str(concept_id)},
            "limitations": limitations,
        }


# ---------------------------------------------------------------------------
# Capability status (truthful provider reporting)
# ---------------------------------------------------------------------------


def vision_lexicon_capability_status() -> dict[str, Any]:
    """Return truthful capability status for the Vision-Lexicon bridge."""
    return {
        "capability": "vision_lexicon_bridge",
        "live_inference_enabled": False,
        "provider_status": "PROVIDER_NOT_CONFIGURED",
        "migration_activated": False,
        "safeguards": {
            "uncalibrated_absolute_dimensions_blocked": True,
            "color_phenotype_class_enforced": True,
            "cannot_determine_preserved": True,
            "machine_output_distinct_from_reviewed_knowledge": True,
            "community_review_auto_promotion_blocked": True,
            "idempotent_analysis_requests": True,
            "versioned_reanalysis_preserves_prior_records": True,
            "automatic_candidate_promotion": False,
            "automatic_publication": False,
        },
        "remaining_external_dependencies": [
            (
                "Live Vision inference provider credentials "
                "(e.g. ANTHROPIC_API_KEY configured for image analysis, or equivalent)"
            ),
            "Governed migration activation of oc_vision schema",
            "Owner-approved candidate knowledge promotion execution",
        ],
    }
