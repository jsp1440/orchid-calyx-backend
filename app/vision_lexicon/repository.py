"""In-memory repository for VisionLexicon entities.

Used in tests and when DATABASE_URL is absent.
Postgres repository extension can be added later without changing the service.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from .models import (
    CharacterConformanceCheck,
    CharacterObservation,
    FigureSpecification,
    FigureValidationRun,
    MorphometricObservation,
    ReferenceImageSet,
    ReferenceImageSetItem,
    ReviewState,
    VisionAnalysis,
    VisionAssertion,
    VisionRegion,
)


def _stable_hash(data: dict[str, Any]) -> str:
    payload = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


class MemoryVisionLexiconRepository:
    """Thread-unsafe in-memory store for unit / integration testing."""

    def __init__(self) -> None:
        self._reference_sets: dict[UUID, ReferenceImageSet] = {}
        self._set_items: dict[UUID, list[ReferenceImageSetItem]] = {}
        self._analyses: dict[UUID, VisionAnalysis] = {}
        self._regions: dict[UUID, list[VisionRegion]] = {}
        self._observations: dict[UUID, list[CharacterObservation]] = {}
        self._morphometrics: dict[UUID, list[MorphometricObservation]] = {}
        self._assertions: dict[UUID, list[VisionAssertion]] = {}
        self._figure_specs: dict[UUID, FigureSpecification] = {}
        self._validation_runs: dict[UUID, FigureValidationRun] = {}
        self._conformance_checks: dict[UUID, list[CharacterConformanceCheck]] = {}

    # -- Reference Sets ------------------------------------------------------

    def save_reference_set(self, ref_set: ReferenceImageSet) -> None:
        self._reference_sets[ref_set.reference_set_id] = ref_set
        if ref_set.reference_set_id not in self._set_items:
            self._set_items[ref_set.reference_set_id] = []

    def get_reference_set(self, reference_set_id: UUID) -> ReferenceImageSet | None:
        return self._reference_sets.get(reference_set_id)

    def list_reference_sets_for_concept(self, concept_id: UUID) -> list[ReferenceImageSet]:
        return [s for s in self._reference_sets.values() if s.target_concept_id == concept_id]

    def save_set_item(self, item: ReferenceImageSetItem) -> None:
        self._set_items.setdefault(item.reference_set_id, []).append(item)

    def list_set_items(self, reference_set_id: UUID) -> list[ReferenceImageSetItem]:
        return list(self._set_items.get(reference_set_id, []))

    # -- Vision Analyses -----------------------------------------------------

    def save_analysis(self, analysis: VisionAnalysis) -> None:
        self._analyses[analysis.analysis_id] = analysis
        self._regions.setdefault(analysis.analysis_id, [])
        self._observations.setdefault(analysis.analysis_id, [])
        self._morphometrics.setdefault(analysis.analysis_id, [])
        self._assertions.setdefault(analysis.analysis_id, [])

    def get_analysis(self, analysis_id: UUID) -> VisionAnalysis | None:
        return self._analyses.get(analysis_id)

    def list_analyses_for_image(self, image_id: str) -> list[VisionAnalysis]:
        return [a for a in self._analyses.values() if a.image_id == image_id]

    def latest_analysis_version_for_image(self, image_id: str) -> int:
        versions = [a.analysis_version for a in self.list_analyses_for_image(image_id)]
        return max(versions, default=0)

    # -- Regions -------------------------------------------------------------

    def save_region(self, region: VisionRegion) -> None:
        self._regions.setdefault(region.analysis_id, []).append(region)

    def list_regions(self, analysis_id: UUID) -> list[VisionRegion]:
        return list(self._regions.get(analysis_id, []))

    # -- Character Observations ----------------------------------------------

    def save_observation(self, obs: CharacterObservation) -> None:
        self._observations.setdefault(obs.analysis_id, []).append(obs)

    def list_observations(self, analysis_id: UUID) -> list[CharacterObservation]:
        return list(self._observations.get(analysis_id, []))

    # -- Morphometrics -------------------------------------------------------

    def save_morphometric(self, m: MorphometricObservation) -> None:
        self._morphometrics.setdefault(m.analysis_id, []).append(m)

    def list_morphometrics(self, analysis_id: UUID) -> list[MorphometricObservation]:
        return list(self._morphometrics.get(analysis_id, []))

    # -- Vision Assertions ---------------------------------------------------

    def save_assertion(self, a: VisionAssertion) -> None:
        self._assertions.setdefault(a.analysis_id, []).append(a)

    def list_assertions(self, analysis_id: UUID) -> list[VisionAssertion]:
        return list(self._assertions.get(analysis_id, []))

    # -- Figure Specifications -----------------------------------------------

    def save_figure_spec(self, spec: FigureSpecification) -> None:
        self._figure_specs[spec.figure_spec_id] = spec

    def get_figure_spec(self, figure_spec_id: UUID) -> FigureSpecification | None:
        return self._figure_specs.get(figure_spec_id)

    def list_figure_specs_for_concept(self, concept_id: UUID) -> list[FigureSpecification]:
        return [s for s in self._figure_specs.values() if s.target_concept_id == concept_id]

    # -- Validation Runs -----------------------------------------------------

    def save_validation_run(self, run: FigureValidationRun) -> None:
        self._validation_runs[run.validation_run_id] = run
        self._conformance_checks.setdefault(run.validation_run_id, [])

    def get_validation_run(self, run_id: UUID) -> FigureValidationRun | None:
        return self._validation_runs.get(run_id)

    def save_conformance_check(self, check: CharacterConformanceCheck) -> None:
        self._conformance_checks.setdefault(check.validation_run_id, []).append(check)

    def list_conformance_checks(self, run_id: UUID) -> list[CharacterConformanceCheck]:
        return list(self._conformance_checks.get(run_id, []))
