"""VisionLexiconService: orchestrates the end-to-end pipeline.

Scientific rules enforced:
1. Uncalibrated analyses CANNOT emit absolute measurements.
2. Image colour CANNOT be elevated to chemical pigment without independent evidence.
3. Machine observations remain PENDING_REVIEW; publication requires governance.
4. Cannot-determine observations are stored, never silently dropped.
5. Re-analysis with a newer model version creates a new record; prior evidence
   is preserved.
6. Duplicate analysis requests for the same image+version are safe (idempotent).
7. Community review cannot auto-promote to scientific truth.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from .models import (
    AnalysisStatus,
    CalibrationState,
    CharacterConformanceCheck,
    CharacterObservation,
    ColorEvidenceClass,
    ConformanceResult,
    FigureSpecification,
    FigureValidationRun,
    ImageQuality,
    MeasurementBasis,
    MediaType,
    MorphometricObservation,
    ReferenceImageSet,
    ReferenceImageSetItem,
    ReviewState,
    VisionAnalysis,
    VisionAssertion,
    VisionRegion,
    ConceptEvidenceSummary,
    enforce_calibration_constraint,
    enforce_colour_ceiling,
)
from .provider import VisionProvider, get_configured_provider
from .repository import MemoryVisionLexiconRepository


class VisionLexiconError(Exception):
    def __init__(self, code: str, details: str = "") -> None:
        super().__init__(details or code)
        self.code = code
        self.details = details


class VisionLexiconService:
    def __init__(
        self,
        repository: MemoryVisionLexiconRepository | None = None,
        provider: VisionProvider | None = None,
    ) -> None:
        self._repo = repository or MemoryVisionLexiconRepository()
        self._provider = provider or get_configured_provider()

    # ------------------------------------------------------------------
    # Reference Image Sets
    # ------------------------------------------------------------------

    def create_reference_set(
        self,
        *,
        title: str,
        target_concept_id: UUID,
        created_by: str,
        taxon_scope: str | None = None,
        description: str | None = None,
        license_summary: str | None = None,
        notes: str | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> ReferenceImageSet:
        ref_set = ReferenceImageSet(
            reference_set_id=uuid4(),
            title=title,
            target_concept_id=target_concept_id,
            taxon_scope=taxon_scope,
            description=description,
            created_at=datetime.now(tz=timezone.utc),
            created_by=created_by,
            review_state=ReviewState.PENDING_REVIEW,
            provenance=provenance or {},
            license_summary=license_summary,
            notes=notes,
        )
        self._repo.save_reference_set(ref_set)
        return ref_set

    def add_set_item(
        self,
        reference_set_id: UUID,
        *,
        image_id: str,
        calibration_status: CalibrationState = CalibrationState.UNCALIBRATED,
        image_quality_state: ImageQuality = ImageQuality.CANNOT_DETERMINE,
        license_usages: tuple = (),
        provenance: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> ReferenceImageSetItem:
        if self._repo.get_reference_set(reference_set_id) is None:
            raise VisionLexiconError("REFERENCE_SET_NOT_FOUND")
        item = ReferenceImageSetItem(
            reference_set_item_id=uuid4(),
            reference_set_id=reference_set_id,
            image_id=image_id,
            calibration_status=calibration_status,
            image_quality_state=image_quality_state,
            license_usages=tuple(license_usages),
            provenance=provenance or {},
            review_state=ReviewState.PENDING_REVIEW,
            **{k: kwargs.get(k) for k in (
                "taxon_id", "taxon_confidence", "developmental_stage",
                "orientation_context", "scale_information", "source",
                "license", "inclusion_reason",
            )},
        )
        self._repo.save_set_item(item)
        return item

    def get_reference_set(self, reference_set_id: UUID) -> ReferenceImageSet:
        result = self._repo.get_reference_set(reference_set_id)
        if result is None:
            raise VisionLexiconError("REFERENCE_SET_NOT_FOUND")
        return result

    def list_reference_sets_for_concept(self, concept_id: UUID) -> list[ReferenceImageSet]:
        return self._repo.list_reference_sets_for_concept(concept_id)

    # ------------------------------------------------------------------
    # Vision Analysis
    # ------------------------------------------------------------------

    def request_analysis(
        self,
        *,
        image_id: str,
        reference_set_id: UUID | None = None,
        taxon_context: str | None = None,
        image_bytes: bytes | None = None,
        image_url: str | None = None,
    ) -> VisionAnalysis:
        """Request a new analysis.  Idempotency: always increments version."""
        next_version = self._repo.latest_analysis_version_for_image(image_id) + 1

        raw = self._provider.analyse_image(
            image_id=image_id,
            image_bytes=image_bytes,
            image_url=image_url,
            taxon_context=taxon_context,
            reference_set_id=reference_set_id,
            analysis_version=next_version,
        )

        status = raw.get("status", AnalysisStatus.PROVIDER_UNAVAILABLE)
        limitations = tuple(raw.get("limitations", []))
        warnings = tuple(raw.get("warnings", []))

        analysis = VisionAnalysis(
            analysis_id=uuid4(),
            image_id=image_id,
            reference_set_id=reference_set_id,
            vision_model=raw.get("provider", self._provider.provider_name),
            vision_model_version=raw.get("provider_version", self._provider.provider_version),
            analysis_version=next_version,
            created_at=datetime.now(tz=timezone.utc),
            taxon_context=taxon_context,
            taxon_confidence=raw.get("taxon_confidence"),
            calibration_state=CalibrationState(
                raw.get("calibration_state", CalibrationState.UNCALIBRATED)
            ),
            image_quality=ImageQuality(
                raw.get("image_quality", ImageQuality.CANNOT_DETERMINE)
            ),
            analysis_status=AnalysisStatus(status),
            review_state=ReviewState.PENDING_REVIEW,
            provenance=raw.get("provenance", {}),
            warnings=warnings,
            limitations=limitations,
        )
        self._repo.save_analysis(analysis)
        return analysis

    def get_analysis(self, analysis_id: UUID) -> VisionAnalysis:
        result = self._repo.get_analysis(analysis_id)
        if result is None:
            raise VisionLexiconError("ANALYSIS_NOT_FOUND")
        return result

    # ------------------------------------------------------------------
    # Structured observations (regions, characters, morphometrics)
    # ------------------------------------------------------------------

    def record_region(
        self,
        *,
        analysis_id: UUID,
        label: str,
        concept_id: UUID | None = None,
        confidence: float = 0.0,
        bounding_box: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> VisionRegion:
        self._assert_analysis_exists(analysis_id)
        region = VisionRegion(
            region_id=uuid4(),
            analysis_id=analysis_id,
            concept_id=concept_id,
            label=label,
            bounding_box=bounding_box,
            segmentation_reference=kwargs.get("segmentation_reference"),
            landmarks=kwargs.get("landmarks"),
            confidence=confidence,
            review_state=ReviewState.PENDING_REVIEW,
            provenance=provenance or {},
        )
        self._repo.save_region(region)
        return region

    def record_character_observation(
        self,
        *,
        analysis_id: UUID,
        concept_id: UUID | None = None,
        character_id: UUID | None = None,
        character_state_id: UUID | None = None,
        numeric_value: float | None = None,
        unit: str | None = None,
        relative_value: float | None = None,
        measurement_basis: MeasurementBasis | None = None,
        calibration_basis: str | None = None,
        confidence: float = 0.0,
        method: str = "VISION_ANALYSIS",
        colour_evidence_class: ColorEvidenceClass | None = None,
        cannot_determine: bool = False,
        limitations: tuple[str, ...] = (),
        provenance: dict[str, Any] | None = None,
        region_id: UUID | None = None,
        evidence_region: dict[str, Any] | None = None,
    ) -> CharacterObservation:
        self._assert_analysis_exists(analysis_id)
        analysis = self._repo.get_analysis(analysis_id)
        assert analysis is not None

        # Enforce calibration constraint
        if measurement_basis is not None:
            enforce_calibration_constraint(
                calibration_state=analysis.calibration_state,
                measurement_basis=measurement_basis,
            )

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
            calibration_basis=calibration_basis,
            confidence=confidence,
            method=method,
            evidence_region=evidence_region,
            colour_evidence_class=colour_evidence_class,
            review_state=ReviewState.PENDING_REVIEW,
            provenance=provenance or {},
            limitations=limitations,
            cannot_determine=cannot_determine,
        )
        self._repo.save_observation(obs)
        return obs

    def record_morphometric(
        self,
        *,
        analysis_id: UUID,
        measurement_type: str,
        measurement_basis: MeasurementBasis,
        value: float | None = None,
        unit: str | None = None,
        calibration_basis: str | None = None,
        calibration_uncertainty: float | None = None,
        confidence: float = 0.0,
        cannot_determine: bool = False,
        concept_id: UUID | None = None,
        region_id: UUID | None = None,
        landmarks: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> MorphometricObservation:
        self._assert_analysis_exists(analysis_id)
        analysis = self._repo.get_analysis(analysis_id)
        assert analysis is not None

        # Calibration constraint enforced in MorphometricObservation.__post_init__
        m = MorphometricObservation(
            morphometric_id=uuid4(),
            analysis_id=analysis_id,
            region_id=region_id,
            concept_id=concept_id,
            measurement_type=measurement_type,
            value=value,
            unit=unit,
            measurement_basis=measurement_basis,
            calibration_state=analysis.calibration_state,
            calibration_basis=calibration_basis,
            calibration_uncertainty=calibration_uncertainty,
            landmarks=landmarks,
            confidence=confidence,
            review_state=ReviewState.PENDING_REVIEW,
            provenance=provenance or {},
            cannot_determine=cannot_determine,
        )
        self._repo.save_morphometric(m)
        return m

    def list_observations(self, analysis_id: UUID) -> list[CharacterObservation]:
        return self._repo.list_observations(analysis_id)

    def list_morphometrics(self, analysis_id: UUID) -> list[MorphometricObservation]:
        return self._repo.list_morphometrics(analysis_id)

    def list_regions(self, analysis_id: UUID) -> list[VisionRegion]:
        return self._repo.list_regions(analysis_id)

    # ------------------------------------------------------------------
    # Vision Assertions (KG-style)
    # ------------------------------------------------------------------

    def record_assertion(
        self,
        *,
        analysis_id: UUID,
        subject: str,
        predicate: str,
        object_or_value: str | None = None,
        evidence_region_id: UUID | None = None,
        confidence: float = 0.0,
        provenance: dict[str, Any] | None = None,
    ) -> VisionAssertion:
        self._assert_analysis_exists(analysis_id)
        assertion = VisionAssertion(
            assertion_id=uuid4(),
            analysis_id=analysis_id,
            subject=subject,
            predicate=predicate,
            object_or_value=object_or_value,
            evidence_region_id=evidence_region_id,
            confidence=confidence,
            assertion_state="MACHINE_GENERATED",
            review_state=ReviewState.PENDING_REVIEW,
            created_at=datetime.now(tz=timezone.utc),
            provenance=provenance or {},
        )
        self._repo.save_assertion(assertion)
        return assertion

    # ------------------------------------------------------------------
    # Figure Specifications
    # ------------------------------------------------------------------

    def create_figure_specification(
        self,
        *,
        target_concept_id: UUID,
        purpose: str,
        scope: str,
        created_by: str,
        taxon_scope: str | None = None,
        reference_set_ids: tuple[UUID, ...] = (),
        required_structures: tuple[dict[str, Any], ...] = (),
        required_character_states: tuple[dict[str, Any], ...] = (),
        required_relationships: tuple[dict[str, Any], ...] = (),
        allowed_variation: dict[str, Any] | None = None,
        excluded_interpretations: tuple[str, ...] = (),
        relative_geometry_constraints: dict[str, Any] | None = None,
        colour_constraints: dict[str, Any] | None = None,
        literature_constraints: tuple[dict[str, Any], ...] = (),
        label_requirements: tuple[str, ...] = (),
        uncertainty_notes: tuple[str, ...] = (),
        generation_notes: str | None = None,
        media_type: MediaType = MediaType.STATIC_ILLUSTRATION,
        provenance: dict[str, Any] | None = None,
        # Moving media fields
        temporal_sequence: tuple[dict[str, Any], ...] | None = None,
        required_stage_order: tuple[str, ...] | None = None,
        motion_constraints: dict[str, Any] | None = None,
        duration_range_seconds: tuple[float, float] | None = None,
        loop_behavior: str | None = None,
        scientific_state_transitions: tuple[dict[str, Any], ...] | None = None,
        reduced_motion_alternative: str | None = None,
    ) -> FigureSpecification:
        spec = FigureSpecification(
            figure_spec_id=uuid4(),
            target_concept_id=target_concept_id,
            purpose=purpose,
            scope=scope,
            taxon_scope=taxon_scope,
            reference_set_ids=reference_set_ids,
            required_structures=required_structures,
            required_character_states=required_character_states,
            required_relationships=required_relationships,
            allowed_variation=allowed_variation or {},
            excluded_interpretations=excluded_interpretations,
            relative_geometry_constraints=relative_geometry_constraints or {},
            colour_constraints=colour_constraints or {},
            literature_constraints=literature_constraints,
            label_requirements=label_requirements,
            uncertainty_notes=uncertainty_notes,
            generation_notes=generation_notes,
            media_type=media_type,
            temporal_sequence=temporal_sequence,
            required_stage_order=required_stage_order,
            motion_constraints=motion_constraints,
            duration_range_seconds=duration_range_seconds,
            loop_behavior=loop_behavior,
            scientific_state_transitions=scientific_state_transitions,
            reduced_motion_alternative=reduced_motion_alternative,
            created_at=datetime.now(tz=timezone.utc),
            created_by=created_by,
            review_state=ReviewState.PENDING_REVIEW,
            version=1,
            provenance=provenance or {},
        )
        self._repo.save_figure_spec(spec)
        return spec

    def get_figure_specification(self, figure_spec_id: UUID) -> FigureSpecification:
        result = self._repo.get_figure_spec(figure_spec_id)
        if result is None:
            raise VisionLexiconError("FIGURE_SPEC_NOT_FOUND")
        return result

    # ------------------------------------------------------------------
    # Validation Runs
    # ------------------------------------------------------------------

    def create_validation_run(
        self,
        *,
        asset_id: str,
        figure_spec_id: UUID,
        vision_analysis_id: UUID | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> FigureValidationRun:
        if self._repo.get_figure_spec(figure_spec_id) is None:
            raise VisionLexiconError("FIGURE_SPEC_NOT_FOUND")

        run = FigureValidationRun(
            validation_run_id=uuid4(),
            asset_id=asset_id,
            figure_spec_id=figure_spec_id,
            vision_analysis_id=vision_analysis_id,
            created_at=datetime.now(tz=timezone.utc),
            status="PENDING",
            overall_review_state=ReviewState.PENDING_REVIEW,
            provenance=provenance or {},
        )
        self._repo.save_validation_run(run)
        return run

    def record_conformance_check(
        self,
        *,
        validation_run_id: UUID,
        character_id: UUID | None = None,
        expected_state_or_range: dict[str, Any],
        observed_state_or_value: dict[str, Any] | None = None,
        result: ConformanceResult,
        confidence: float = 0.0,
        notes: str | None = None,
    ) -> CharacterConformanceCheck:
        if self._repo.get_validation_run(validation_run_id) is None:
            raise VisionLexiconError("VALIDATION_RUN_NOT_FOUND")
        check = CharacterConformanceCheck(
            check_id=uuid4(),
            validation_run_id=validation_run_id,
            character_id=character_id,
            expected_state_or_range=expected_state_or_range,
            observed_state_or_value=observed_state_or_value,
            result=result,
            confidence=confidence,
            notes=notes,
            review_state=ReviewState.PENDING_REVIEW,
        )
        self._repo.save_conformance_check(check)
        return check

    def list_conformance_checks(self, validation_run_id: UUID) -> list[CharacterConformanceCheck]:
        return self._repo.list_conformance_checks(validation_run_id)

    # ------------------------------------------------------------------
    # Reference-set aggregation
    # ------------------------------------------------------------------

    def aggregate_reference_set_summary(
        self, reference_set_id: UUID
    ) -> dict[str, Any]:
        """Summarise observations across all images in a reference set.

        Rules:
        - Sample size and cannot-determine counts are always included.
        - Unresolved observations are never hidden.
        - Aggregate records retain links to contributing analyses.
        """
        ref_set = self._repo.get_reference_set(reference_set_id)
        if ref_set is None:
            raise VisionLexiconError("REFERENCE_SET_NOT_FOUND")

        items = self._repo.list_set_items(reference_set_id)
        contributing_analysis_ids: list[UUID] = []
        character_states: dict[str, list[str]] = {}
        cannot_determine_count = 0
        total_observations = 0

        for item in items:
            for analysis in self._repo.list_analyses_for_image(item.image_id):
                contributing_analysis_ids.append(analysis.analysis_id)
                for obs in self._repo.list_observations(analysis.analysis_id):
                    total_observations += 1
                    if obs.cannot_determine:
                        cannot_determine_count += 1
                        continue
                    if obs.character_id is not None and obs.character_state_id is not None:
                        key = str(obs.character_id)
                        character_states.setdefault(key, []).append(str(obs.character_state_id))

        # Frequency tables per character
        frequency: dict[str, dict[str, int]] = {}
        for char_id, states in character_states.items():
            freq: dict[str, int] = {}
            for s in states:
                freq[s] = freq.get(s, 0) + 1
            frequency[char_id] = freq

        return {
            "reference_set_id": str(reference_set_id),
            "sample_size": len(items),
            "contributing_analysis_ids": [str(a) for a in contributing_analysis_ids],
            "total_observations": total_observations,
            "cannot_determine_count": cannot_determine_count,
            "character_state_frequencies": frequency,
            "limitations": [
                "Aggregate is computed from pending-review machine observations only.",
                "Cannot-determine observations are preserved in the count above.",
                "No statistical inference has been performed.",
            ],
        }

    # ------------------------------------------------------------------
    # Frontend evidence summary
    # ------------------------------------------------------------------

    def get_concept_evidence_summary(self, concept_id: UUID) -> ConceptEvidenceSummary:
        """Return all vision evidence for a concept in frontend-consumable form."""
        ref_sets = self._repo.list_reference_sets_for_concept(concept_id)
        all_images: list[dict[str, Any]] = []
        all_observations: list[dict[str, Any]] = []
        all_morphometrics: list[dict[str, Any]] = []
        for ref_set in ref_sets:
            for item in self._repo.list_set_items(ref_set.reference_set_id):
                all_images.append(
                    {"image_id": item.image_id, "reference_set_id": str(ref_set.reference_set_id)}
                )
                for analysis in self._repo.list_analyses_for_image(item.image_id):
                    for obs in self._repo.list_observations(analysis.analysis_id):
                        all_observations.append(
                            {
                                "observation_id": str(obs.observation_id),
                                "analysis_id": str(obs.analysis_id),
                                "concept_id": str(obs.concept_id) if obs.concept_id else None,
                                "character_id": str(obs.character_id) if obs.character_id else None,
                                "character_state_id": str(obs.character_state_id) if obs.character_state_id else None,
                                "cannot_determine": obs.cannot_determine,
                                "confidence": obs.confidence,
                                "review_state": obs.review_state,
                                "limitations": list(obs.limitations),
                            }
                        )
                    for m in self._repo.list_morphometrics(analysis.analysis_id):
                        all_morphometrics.append(
                            {
                                "morphometric_id": str(m.morphometric_id),
                                "measurement_type": m.measurement_type,
                                "measurement_basis": m.measurement_basis,
                                "value": m.value,
                                "unit": m.unit,
                                "cannot_determine": m.cannot_determine,
                                "confidence": m.confidence,
                            }
                        )

        figure_specs = self._repo.list_figure_specs_for_concept(concept_id)
        limitations: list[str] = [
            "All observations are machine-generated and pending human review.",
            "Cannot-determine states are included in the totals above.",
        ]

        return ConceptEvidenceSummary(
            concept_id=concept_id,
            concept_label=str(concept_id),
            reference_sets=tuple(
                {"reference_set_id": str(r.reference_set_id), "title": r.title, "review_state": r.review_state}
                for r in ref_sets
            ),
            reference_images=tuple(all_images),
            vision_observations=tuple(all_observations),
            morphometrics=tuple(all_morphometrics),
            aggregate_summary={},
            figure_specifications=tuple(
                {"figure_spec_id": str(s.figure_spec_id), "purpose": s.purpose, "version": s.version}
                for s in figure_specs
            ),
            visual_assets=(),
            validation_runs=(),
            review_state=ReviewState.PENDING_REVIEW,
            provenance={"source": "VisionLexiconService"},
            limitations=tuple(limitations),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _assert_analysis_exists(self, analysis_id: UUID) -> None:
        if self._repo.get_analysis(analysis_id) is None:
            raise VisionLexiconError("ANALYSIS_NOT_FOUND")
