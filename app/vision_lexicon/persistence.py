"""Postgres repository for the Vision-Lexicon bridge.

Construction is inert — no connection is opened at import time.
Callers must explicitly supply a connection factory.
This module never reads credentials or applies migrations automatically.

The in-memory implementation (MemoryVisionLexiconRepository) is used for
tests and for status endpoints when the schema is not yet activated.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from .contracts import (
    AnalysisStatus,
    CalibrationState,
    CharacterConformanceCheck,
    CharacterConformanceResult,
    CharacterObservation,
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
    ValidationRunStatus,
    VisionAnalysisRecord,
    VisionAssertion,
    VisionRegion,
    VisionReviewRecord,
    VisionReviewState,
)

# ---------------------------------------------------------------------------
# In-memory repository (used for tests and fixture pipelines)
# ---------------------------------------------------------------------------


class MemoryVisionLexiconRepository:
    """Thread-unsafe in-memory repository for unit tests."""

    def __init__(self) -> None:
        self._reference_sets: dict[UUID, ReferenceImageSet] = {}
        self._analyses: dict[UUID, VisionAnalysisRecord] = {}
        self._analyses_by_hash: dict[str, VisionAnalysisRecord] = {}
        self._regions: dict[UUID, VisionRegion] = {}
        self._char_obs: dict[UUID, CharacterObservation] = {}
        self._morphometrics: dict[UUID, MorphometricObservation] = {}
        self._color_obs: dict[UUID, ColorPhenotypeObservation] = {}
        self._assertions: dict[UUID, VisionAssertion] = {}
        self._figure_specs: dict[UUID, FigureSpecification] = {}
        self._validation_runs: dict[UUID, FigureValidationRun] = {}
        self._conformance_checks: dict[UUID, CharacterConformanceCheck] = {}
        self._reviews: dict[UUID, VisionReviewRecord] = {}

    # Reference sets

    def save_reference_set(self, ref_set: ReferenceImageSet) -> ReferenceImageSet:
        self._reference_sets[ref_set.reference_set_id] = ref_set
        return ref_set

    def get_reference_set(self, reference_set_id: UUID) -> ReferenceImageSet | None:
        return self._reference_sets.get(reference_set_id)

    def list_reference_sets_for_concept(self, concept_id: UUID) -> list[ReferenceImageSet]:
        return [
            rs for rs in self._reference_sets.values()
            if rs.target_concept_id == concept_id
        ]

    # Analyses

    def save_analysis(self, analysis: VisionAnalysisRecord) -> VisionAnalysisRecord:
        self._analyses[analysis.analysis_id] = analysis
        if analysis.request_hash:
            self._analyses_by_hash[analysis.request_hash] = analysis
        return analysis

    def get_analysis(self, analysis_id: UUID) -> VisionAnalysisRecord | None:
        return self._analyses.get(analysis_id)

    def get_analysis_by_request_hash(self, request_hash: str) -> VisionAnalysisRecord | None:
        return self._analyses_by_hash.get(request_hash)

    def list_analyses_for_image(self, image_id: str) -> list[VisionAnalysisRecord]:
        return [a for a in self._analyses.values() if a.image_id == image_id]

    def list_analyses_for_reference_set(
        self, reference_set_id: UUID
    ) -> list[VisionAnalysisRecord]:
        return [
            a for a in self._analyses.values()
            if a.reference_set_id == reference_set_id
        ]

    # Regions

    def save_region(self, region: VisionRegion) -> VisionRegion:
        self._regions[region.region_id] = region
        return region

    def get_region(self, region_id: UUID) -> VisionRegion | None:
        return self._regions.get(region_id)

    def list_regions_for_analysis(self, analysis_id: UUID) -> list[VisionRegion]:
        return [r for r in self._regions.values() if r.analysis_id == analysis_id]

    # Character observations

    def save_character_observation(self, obs: CharacterObservation) -> CharacterObservation:
        self._char_obs[obs.observation_id] = obs
        return obs

    def list_observations_for_analysis(
        self, analysis_id: UUID
    ) -> list[CharacterObservation]:
        return [o for o in self._char_obs.values() if o.analysis_id == analysis_id]

    # Morphometrics

    def save_morphometric(self, obs: MorphometricObservation) -> MorphometricObservation:
        self._morphometrics[obs.morphometric_id] = obs
        return obs

    def list_morphometrics_for_analysis(
        self, analysis_id: UUID
    ) -> list[MorphometricObservation]:
        return [m for m in self._morphometrics.values() if m.analysis_id == analysis_id]

    # Color observations

    def save_color_observation(
        self, obs: ColorPhenotypeObservation
    ) -> ColorPhenotypeObservation:
        self._color_obs[obs.color_obs_id] = obs
        return obs

    # Assertions

    def save_assertion(self, assertion: VisionAssertion) -> VisionAssertion:
        self._assertions[assertion.assertion_id] = assertion
        return assertion

    # Figure specs

    def save_figure_spec(self, spec: FigureSpecification) -> FigureSpecification:
        self._figure_specs[spec.figure_spec_id] = spec
        return spec

    def get_figure_spec(self, figure_spec_id: UUID) -> FigureSpecification | None:
        return self._figure_specs.get(figure_spec_id)

    def list_figure_specs_for_concept(self, concept_id: UUID) -> list[FigureSpecification]:
        return [
            s for s in self._figure_specs.values()
            if s.target_concept_id == concept_id
        ]

    # Validation runs

    def save_validation_run(self, run: FigureValidationRun) -> FigureValidationRun:
        self._validation_runs[run.validation_run_id] = run
        return run

    def get_validation_run(self, validation_run_id: UUID) -> FigureValidationRun | None:
        return self._validation_runs.get(validation_run_id)

    # Conformance checks

    def save_conformance_checks(
        self, checks: list[CharacterConformanceCheck]
    ) -> list[CharacterConformanceCheck]:
        for check in checks:
            self._conformance_checks[check.check_id] = check
        return checks

    def list_conformance_checks_for_run(
        self, validation_run_id: UUID
    ) -> list[CharacterConformanceCheck]:
        return [
            c for c in self._conformance_checks.values()
            if c.validation_run_id == validation_run_id
        ]

    # Reviews

    def save_review(self, review: VisionReviewRecord) -> VisionReviewRecord:
        self._reviews[review.review_id] = review
        return review


# ---------------------------------------------------------------------------
# Postgres repository
# ---------------------------------------------------------------------------


class PostgresVisionLexiconRepository:
    """Postgres implementation.

    Construction is inert; callers must provide a connection factory.
    The schema must be activated via the governed migration before use.
    """

    def __init__(self, connection_factory: Callable[[], Any]) -> None:
        self._cf = connection_factory

    # ------------------------------------------------------------------
    # Reference sets
    # ------------------------------------------------------------------

    def save_reference_set(self, ref_set: ReferenceImageSet) -> ReferenceImageSet:
        from psycopg.types.json import Jsonb

        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_vision.reference_image_sets (
                    reference_set_id, title, target_concept_id, taxon_scope,
                    description, created_by, review_state, provenance,
                    license_summary, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (reference_set_id) DO NOTHING
                """,
                (
                    ref_set.reference_set_id,
                    ref_set.title,
                    ref_set.target_concept_id,
                    ref_set.taxon_scope,
                    ref_set.description,
                    ref_set.created_by,
                    ref_set.review_state,
                    Jsonb(ref_set.provenance),
                    ref_set.license_summary,
                    ref_set.notes,
                ),
            )
            for item in ref_set.items:
                cur.execute(
                    """
                    INSERT INTO oc_vision.reference_image_set_items (
                        reference_set_item_id, reference_set_id, image_id,
                        media_id, taxon_id, taxon_confidence,
                        developmental_stage, orientation_context,
                        calibration_status, scale_information,
                        image_quality_state, source, license, provenance,
                        inclusion_reason, review_state
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (reference_set_item_id) DO NOTHING
                    """,
                    (
                        item.reference_set_item_id,
                        item.reference_set_id,
                        item.image_id,
                        item.media_id,
                        item.taxon_id,
                        item.taxon_confidence,
                        item.developmental_stage,
                        item.orientation_context,
                        item.calibration_status,
                        Jsonb(item.scale_information) if item.scale_information else None,
                        item.image_quality_state,
                        item.source,
                        item.license,
                        Jsonb(item.provenance),
                        item.inclusion_reason,
                        item.review_state,
                    ),
                )
        return ref_set

    def get_reference_set(self, reference_set_id: UUID) -> ReferenceImageSet | None:
        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM oc_vision.reference_image_sets WHERE reference_set_id=%s",
                (reference_set_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cur.execute(
                "SELECT * FROM oc_vision.reference_image_set_items WHERE reference_set_id=%s",
                (reference_set_id,),
            )
            item_rows = cur.fetchall()
        return self._build_reference_set(row, item_rows)

    def list_reference_sets_for_concept(self, concept_id: UUID) -> list[ReferenceImageSet]:
        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM oc_vision.reference_image_sets WHERE target_concept_id=%s",
                (concept_id,),
            )
            rows = cur.fetchall()
            result = []
            for row in rows:
                cur.execute(
                    "SELECT * FROM oc_vision.reference_image_set_items WHERE reference_set_id=%s",
                    (row[0],),
                )
                result.append(self._build_reference_set(row, cur.fetchall()))
        return result

    @staticmethod
    def _build_reference_set(row: Any, item_rows: Any) -> ReferenceImageSet:
        items = tuple(
            ReferenceImageSetItem(
                reference_set_item_id=r[0],
                reference_set_id=r[1],
                image_id=r[2],
                media_id=r[3],
                taxon_id=r[4],
                taxon_confidence=float(r[5]) if r[5] is not None else None,
                developmental_stage=r[6],
                orientation_context=r[7],
                calibration_status=CalibrationState(r[8]),
                scale_information=r[9],
                image_quality_state=ImageQualityState(r[10]),
                source=r[11],
                license=r[12],
                provenance=r[13] or {},
                inclusion_reason=r[14],
                review_state=VisionReviewState(r[15]),
            )
            for r in item_rows
        )
        return ReferenceImageSet(
            reference_set_id=row[0],
            title=row[1],
            target_concept_id=row[2],
            taxon_scope=row[3],
            description=row[4],
            created_by=row[6],
            review_state=VisionReviewState(row[7]),
            provenance=row[8] or {},
            license_summary=row[9],
            notes=row[10],
            items=items,
        )

    # ------------------------------------------------------------------
    # Analyses
    # ------------------------------------------------------------------

    def save_analysis(self, analysis: VisionAnalysisRecord) -> VisionAnalysisRecord:
        from psycopg.types.json import Jsonb

        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_vision.vision_analyses (
                    analysis_id, image_id, content_hash, reference_set_id,
                    vision_model, vision_model_version, analysis_version,
                    taxon_context, taxon_confidence, calibration_state,
                    image_quality, analysis_status, review_state,
                    provenance, warnings, limitations, request_hash
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (request_hash) DO NOTHING
                """,
                (
                    analysis.analysis_id,
                    analysis.image_id,
                    analysis.content_hash,
                    analysis.reference_set_id,
                    analysis.vision_model,
                    analysis.vision_model_version,
                    analysis.analysis_version,
                    analysis.taxon_context,
                    analysis.taxon_confidence,
                    analysis.calibration_state,
                    analysis.image_quality,
                    analysis.analysis_status,
                    analysis.review_state,
                    Jsonb(analysis.provenance),
                    list(analysis.warnings),
                    list(analysis.limitations),
                    analysis.request_hash,
                ),
            )
        return analysis

    def get_analysis(self, analysis_id: UUID) -> VisionAnalysisRecord | None:
        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM oc_vision.vision_analyses WHERE analysis_id=%s",
                (analysis_id,),
            )
            row = cur.fetchone()
        return self._build_analysis(row) if row else None

    def get_analysis_by_request_hash(self, request_hash: str) -> VisionAnalysisRecord | None:
        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM oc_vision.vision_analyses WHERE request_hash=%s",
                (request_hash,),
            )
            row = cur.fetchone()
        return self._build_analysis(row) if row else None

    def list_analyses_for_image(self, image_id: str) -> list[VisionAnalysisRecord]:
        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM oc_vision.vision_analyses WHERE image_id=%s",
                (image_id,),
            )
            return [self._build_analysis(r) for r in cur.fetchall()]

    def list_analyses_for_reference_set(
        self, reference_set_id: UUID
    ) -> list[VisionAnalysisRecord]:
        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM oc_vision.vision_analyses WHERE reference_set_id=%s",
                (reference_set_id,),
            )
            return [self._build_analysis(r) for r in cur.fetchall()]

    @staticmethod
    def _build_analysis(row: Any) -> VisionAnalysisRecord:
        return VisionAnalysisRecord(
            analysis_id=row[0],
            image_id=row[1],
            content_hash=row[2],
            reference_set_id=row[3],
            vision_model=row[4],
            vision_model_version=row[5],
            analysis_version=row[6],
            taxon_context=row[8],
            taxon_confidence=float(row[9]) if row[9] is not None else None,
            calibration_state=CalibrationState(row[10]),
            image_quality=ImageQualityState(row[11]),
            analysis_status=AnalysisStatus(row[12]),
            review_state=VisionReviewState(row[13]),
            provenance=row[14] or {},
            warnings=tuple(row[15] or []),
            limitations=tuple(row[16] or []),
            request_hash=row[17] if len(row) > 17 else None,
        )

    # ------------------------------------------------------------------
    # Regions
    # ------------------------------------------------------------------

    def save_region(self, region: VisionRegion) -> VisionRegion:
        from psycopg.types.json import Jsonb

        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_vision.vision_regions (
                    region_id, analysis_id, concept_id, label, bounding_box,
                    segmentation_ref, landmarks, confidence, review_state, provenance
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (region_id) DO NOTHING
                """,
                (
                    region.region_id, region.analysis_id, region.concept_id,
                    region.label,
                    Jsonb(region.bounding_box) if region.bounding_box is not None else None,
                    region.segmentation_ref,
                    Jsonb(region.landmarks) if region.landmarks is not None else None,
                    region.confidence, region.review_state, Jsonb(region.provenance),
                ),
            )
        return region

    def get_region(self, region_id: UUID) -> VisionRegion | None:
        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM oc_vision.vision_regions WHERE region_id=%s",
                (region_id,),
            )
            row = cur.fetchone()
            return self._build_region(row) if row is not None else None

    def list_regions_for_analysis(self, analysis_id: UUID) -> list[VisionRegion]:
        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM oc_vision.vision_regions WHERE analysis_id=%s",
                (analysis_id,),
            )
            return [self._build_region(r) for r in cur.fetchall()]

    @staticmethod
    def _build_region(row: Any) -> VisionRegion:
        return VisionRegion(
            region_id=row[0],
            analysis_id=row[1],
            concept_id=row[2],
            label=row[3],
            bounding_box=row[4],
            segmentation_ref=row[5],
            landmarks=row[6],
            confidence=float(row[7]) if row[7] is not None else None,
            review_state=VisionReviewState(row[8]),
            provenance=row[9] or {},
        )

    # ------------------------------------------------------------------
    # Character observations (pass-through stubs — extend as needed)
    # ------------------------------------------------------------------

    def save_character_observation(self, obs: CharacterObservation) -> CharacterObservation:
        from psycopg.types.json import Jsonb

        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_vision.character_observations (
                    observation_id, analysis_id, region_id, concept_id,
                    character_id, character_state_id, numeric_value, unit,
                    relative_value, measurement_basis, confidence, method,
                    evidence_region, review_state, provenance, limitations
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (observation_id) DO NOTHING
                """,
                (
                    obs.observation_id, obs.analysis_id, obs.region_id,
                    obs.concept_id, obs.character_id, obs.character_state_id,
                    obs.numeric_value, obs.unit, obs.relative_value,
                    obs.measurement_basis, obs.confidence, obs.method,
                    obs.evidence_region, obs.review_state,
                    Jsonb(obs.provenance), list(obs.limitations),
                ),
            )
        return obs

    def list_observations_for_analysis(
        self, analysis_id: UUID
    ) -> list[CharacterObservation]:
        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM oc_vision.character_observations WHERE analysis_id=%s",
                (analysis_id,),
            )
            return [self._build_char_obs(r) for r in cur.fetchall()]

    @staticmethod
    def _build_char_obs(row: Any) -> CharacterObservation:
        return CharacterObservation(
            observation_id=row[0],
            analysis_id=row[1],
            region_id=row[2],
            concept_id=row[3],
            character_id=row[4],
            character_state_id=row[5],
            numeric_value=float(row[6]) if row[6] is not None else None,
            unit=row[7],
            relative_value=float(row[8]) if row[8] is not None else None,
            measurement_basis=MeasurementBasis(row[9]),
            confidence=float(row[10]),
            method=row[11],
            evidence_region=row[12],
            review_state=VisionReviewState(row[13]),
            provenance=row[14] or {},
            limitations=tuple(row[15] or []),
        )

    def save_morphometric(self, obs: MorphometricObservation) -> MorphometricObservation:
        from psycopg.types.json import Jsonb

        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_vision.morphometric_observations (
                    morphometric_id, analysis_id, region_id, metric_type,
                    value, unit, calibration_state, calibration_basis,
                    calibration_uncertainty, confidence, landmarks_used, provenance
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (morphometric_id) DO NOTHING
                """,
                (
                    obs.morphometric_id, obs.analysis_id, obs.region_id,
                    obs.metric_type, obs.value, obs.unit, obs.calibration_state,
                    obs.calibration_basis, obs.calibration_uncertainty,
                    obs.confidence,
                    Jsonb(obs.landmarks_used) if obs.landmarks_used else None,
                    Jsonb(obs.provenance),
                ),
            )
        return obs

    def list_morphometrics_for_analysis(
        self, analysis_id: UUID
    ) -> list[MorphometricObservation]:
        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM oc_vision.morphometric_observations WHERE analysis_id=%s",
                (analysis_id,),
            )
            return [self._build_morphometric(r) for r in cur.fetchall()]

    @staticmethod
    def _build_morphometric(row: Any) -> MorphometricObservation:
        return MorphometricObservation(
            morphometric_id=row[0],
            analysis_id=row[1],
            region_id=row[2],
            metric_type=MetricType(row[3]),
            value=float(row[4]),
            unit=row[5],
            calibration_state=CalibrationState(row[6]),
            calibration_basis=row[7],
            calibration_uncertainty=row[8],
            confidence=float(row[9]) if row[9] is not None else None,
            landmarks_used=row[10],
            provenance=row[11] or {},
        )

    def save_color_observation(
        self, obs: ColorPhenotypeObservation
    ) -> ColorPhenotypeObservation:
        from psycopg.types.json import Jsonb

        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_vision.color_phenotype_observations (
                    color_obs_id, analysis_id, region_id, phenotype_class,
                    rgb_hex, hsv_hue, hsv_saturation, hsv_value,
                    lab_l, lab_a, lab_b, pattern_description,
                    pigment_class, pigment_evidence_source, provenance
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (color_obs_id) DO NOTHING
                """,
                (
                    obs.color_obs_id, obs.analysis_id, obs.region_id,
                    obs.phenotype_class, obs.rgb_hex,
                    obs.hsv_hue, obs.hsv_saturation, obs.hsv_value,
                    obs.lab_l, obs.lab_a, obs.lab_b,
                    obs.pattern_description,
                    obs.pigment_class, obs.pigment_evidence_source,
                    Jsonb(obs.provenance),
                ),
            )
        return obs

    def save_figure_spec(self, spec: FigureSpecification) -> FigureSpecification:
        from psycopg.types.json import Jsonb

        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_vision.figure_specifications (
                    figure_spec_id, target_concept_id, purpose, scope,
                    taxon_scope, reference_set_ids, required_structures,
                    required_character_states, required_relationships,
                    allowed_variation, excluded_interpretations,
                    relative_geometry_constraints, color_constraints,
                    literature_constraints, label_requirements,
                    uncertainty_notes, generation_notes, media_type,
                    created_by, review_state, version, provenance
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (figure_spec_id) DO NOTHING
                """,
                (
                    spec.figure_spec_id, spec.target_concept_id, spec.purpose,
                    spec.scope, spec.taxon_scope,
                    [str(sid) for sid in spec.reference_set_ids],
                    Jsonb(spec.required_structures),
                    Jsonb(spec.required_character_states),
                    Jsonb(spec.required_relationships),
                    Jsonb(spec.allowed_variation),
                    Jsonb(spec.excluded_interpretations),
                    Jsonb(spec.relative_geometry_constraints),
                    Jsonb(spec.color_constraints),
                    Jsonb(spec.literature_constraints),
                    Jsonb(spec.label_requirements),
                    spec.uncertainty_notes, spec.generation_notes,
                    spec.media_type, spec.created_by, spec.review_state,
                    spec.version, Jsonb(spec.provenance),
                ),
            )
        return spec

    def get_figure_spec(self, figure_spec_id: UUID) -> FigureSpecification | None:
        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM oc_vision.figure_specifications WHERE figure_spec_id=%s",
                (figure_spec_id,),
            )
            row = cur.fetchone()
        return self._build_figure_spec(row) if row else None

    def list_figure_specs_for_concept(self, concept_id: UUID) -> list[FigureSpecification]:
        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM oc_vision.figure_specifications WHERE target_concept_id=%s",
                (concept_id,),
            )
            return [self._build_figure_spec(r) for r in cur.fetchall()]

    @staticmethod
    def _build_figure_spec(row: Any) -> FigureSpecification:
        import uuid as _uuid
        return FigureSpecification(
            figure_spec_id=row[0],
            target_concept_id=row[1],
            purpose=row[2],
            scope=row[3],
            taxon_scope=row[4],
            reference_set_ids=tuple(
                _uuid.UUID(sid) for sid in (row[5] or [])
            ),
            required_structures=row[6] or [],
            required_character_states=row[7] or [],
            required_relationships=row[8] or [],
            allowed_variation=row[9] or {},
            excluded_interpretations=row[10] or [],
            relative_geometry_constraints=row[11] or {},
            color_constraints=row[12] or {},
            literature_constraints=row[13] or [],
            label_requirements=row[14] or [],
            uncertainty_notes=row[15],
            generation_notes=row[16],
            media_type=MediaType(row[17]),
            temporal_sequence=None,
            required_stage_order=None,
            motion_constraints=None,
            duration_range=None,
            loop_behavior=None,
            scientific_state_transitions=None,
            reduced_motion_alternative=None,
            created_by=row[18],
            review_state=VisionReviewState(row[19]),
            version=row[20],
            provenance=row[21] or {},
        )

    def save_validation_run(self, run: FigureValidationRun) -> FigureValidationRun:
        from psycopg.types.json import Jsonb

        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_vision.figure_validation_runs (
                    validation_run_id, asset_id, figure_spec_id,
                    vision_analysis_id, status, overall_review_state, provenance
                ) VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (validation_run_id) DO NOTHING
                """,
                (
                    run.validation_run_id, run.asset_id,
                    run.figure_spec_id, run.vision_analysis_id,
                    run.status, run.overall_review_state,
                    Jsonb(run.provenance),
                ),
            )
        return run

    def get_validation_run(self, validation_run_id: UUID) -> FigureValidationRun | None:
        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM oc_vision.figure_validation_runs WHERE validation_run_id=%s",
                (validation_run_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cur.execute(
                "SELECT * FROM oc_vision.character_conformance_checks WHERE validation_run_id=%s",
                (validation_run_id,),
            )
            check_rows = cur.fetchall()
        return self._build_validation_run(row, check_rows)

    @staticmethod
    def _build_validation_run(
        row: Any, check_rows: Any
    ) -> FigureValidationRun:
        checks = tuple(
            CharacterConformanceCheck(
                check_id=c[0],
                validation_run_id=c[1],
                character_id=c[2],
                expected_state_or_range=c[3],
                observed_state_or_value=c[4],
                result=CharacterConformanceResult(c[5]),
                confidence=float(c[6]) if c[6] is not None else None,
                notes=c[7],
                review_state=VisionReviewState(c[8]),
            )
            for c in check_rows
        )
        return FigureValidationRun(
            validation_run_id=row[0],
            asset_id=row[1],
            figure_spec_id=row[2],
            vision_analysis_id=row[3],
            status=ValidationRunStatus(row[4]),
            overall_review_state=VisionReviewState(row[5]),
            provenance=row[6] or {},
            conformance_checks=checks,
        )

    def save_conformance_checks(
        self, checks: list[CharacterConformanceCheck]
    ) -> list[CharacterConformanceCheck]:

        if not checks:
            return []
        with self._cf() as conn, conn.cursor() as cur:
            for check in checks:
                cur.execute(
                    """
                    INSERT INTO oc_vision.character_conformance_checks (
                        check_id, validation_run_id, character_id,
                        expected_state_or_range, observed_state_or_value,
                        result, confidence, notes, review_state
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (check_id) DO NOTHING
                    """,
                    (
                        check.check_id, check.validation_run_id, check.character_id,
                        check.expected_state_or_range, check.observed_state_or_value,
                        check.result, check.confidence, check.notes, check.review_state,
                    ),
                )
        return checks

    def list_conformance_checks_for_run(
        self, validation_run_id: UUID
    ) -> list[CharacterConformanceCheck]:
        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM oc_vision.character_conformance_checks WHERE validation_run_id=%s",
                (validation_run_id,),
            )
            return [
                CharacterConformanceCheck(
                    check_id=r[0], validation_run_id=r[1], character_id=r[2],
                    expected_state_or_range=r[3], observed_state_or_value=r[4],
                    result=CharacterConformanceResult(r[5]),
                    confidence=float(r[6]) if r[6] is not None else None,
                    notes=r[7],
                    review_state=VisionReviewState(r[8]),
                )
                for r in cur.fetchall()
            ]

    def save_review(self, review: VisionReviewRecord) -> VisionReviewRecord:
        from psycopg.types.json import Jsonb

        with self._cf() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO oc_vision.vision_review_records (
                    review_id, subject_type, subject_id, reviewer_id,
                    reviewer_tier, decision, scope_of_expertise,
                    version_reviewed, questions_answered, comments,
                    auto_promotion_blocked, provenance
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (review_id) DO NOTHING
                """,
                (
                    review.review_id, review.subject_type, review.subject_id,
                    review.reviewer_id, review.reviewer_tier, review.decision,
                    review.scope_of_expertise, review.version_reviewed,
                    Jsonb(review.questions_answered), review.comments,
                    review.auto_promotion_blocked, Jsonb(review.provenance),
                ),
            )
        return review
