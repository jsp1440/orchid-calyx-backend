"""FastAPI routes for the Vision-Lexicon bridge.

Security: all routes require owner session or API key via
verify_owner_or_api_key (consistent with existing conventions).

Public Lexicon APIs must only expose content approved for public publication;
this is enforced by the review_state filter on concept evidence summaries.
"""

from __future__ import annotations

import dataclasses
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.routers.health import add_mission_control_cors_headers
from app.security import verify_owner_or_api_key

from .models import (
    CalibrationState,
    ColorEvidenceClass,
    ConformanceResult,
    ImageQuality,
    MeasurementBasis,
    MediaType,
    ReviewState,
)
from .service import VisionLexiconError, VisionLexiconService

router = APIRouter(
    prefix="/api/vision-lexicon",
    tags=["vision-lexicon-bridge"],
    dependencies=[
        Depends(verify_owner_or_api_key),
        Depends(add_mission_control_cors_headers),
    ],
)

_service: VisionLexiconService | None = None


def _get_service() -> VisionLexiconService:
    global _service
    if _service is None:
        _service = VisionLexiconService()
    return _service


def _translate(exc: VisionLexiconError) -> HTTPException:
    status_map = {
        "REFERENCE_SET_NOT_FOUND": 404,
        "ANALYSIS_NOT_FOUND": 404,
        "FIGURE_SPEC_NOT_FOUND": 404,
        "VALIDATION_RUN_NOT_FOUND": 404,
    }
    return HTTPException(
        status_code=status_map.get(exc.code, 422),
        detail={"code": exc.code, "details": exc.details},
    )


def _dc_to_dict(obj: object) -> dict[str, Any]:
    """Convert a frozen dataclass to a JSON-serialisable dict."""
    return dataclasses.asdict(obj)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class CreateReferenceSetRequest(BaseModel):
    title: str
    target_concept_id: UUID
    created_by: str
    taxon_scope: str | None = None
    description: str | None = None
    license_summary: str | None = None
    notes: str | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class AddSetItemRequest(BaseModel):
    image_id: str
    calibration_status: CalibrationState = CalibrationState.UNCALIBRATED
    image_quality_state: ImageQuality = ImageQuality.CANNOT_DETERMINE
    taxon_id: str | None = None
    taxon_confidence: float | None = None
    developmental_stage: str | None = None
    orientation_context: str | None = None
    scale_information: dict[str, Any] | None = None
    source: str | None = None
    license: str | None = None
    inclusion_reason: str | None = None
    license_usages: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


class RequestAnalysisRequest(BaseModel):
    image_id: str
    reference_set_id: UUID | None = None
    taxon_context: str | None = None
    image_url: str | None = None


class RecordRegionRequest(BaseModel):
    analysis_id: UUID
    label: str
    concept_id: UUID | None = None
    confidence: float = 0.0
    bounding_box: dict[str, Any] | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class RecordObservationRequest(BaseModel):
    analysis_id: UUID
    region_id: UUID | None = None
    concept_id: UUID | None = None
    character_id: UUID | None = None
    character_state_id: UUID | None = None
    numeric_value: float | None = None
    unit: str | None = None
    relative_value: float | None = None
    measurement_basis: MeasurementBasis | None = None
    calibration_basis: str | None = None
    confidence: float = 0.0
    method: str = "VISION_ANALYSIS"
    colour_evidence_class: ColorEvidenceClass | None = None
    cannot_determine: bool = False
    limitations: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)


class RecordMorphometricRequest(BaseModel):
    analysis_id: UUID
    measurement_type: str
    measurement_basis: MeasurementBasis
    region_id: UUID | None = None
    concept_id: UUID | None = None
    value: float | None = None
    unit: str | None = None
    calibration_basis: str | None = None
    calibration_uncertainty: float | None = None
    confidence: float = 0.0
    cannot_determine: bool = False
    provenance: dict[str, Any] = Field(default_factory=dict)


class CreateFigureSpecRequest(BaseModel):
    target_concept_id: UUID
    purpose: str
    scope: str
    created_by: str
    taxon_scope: str | None = None
    reference_set_ids: list[UUID] = Field(default_factory=list)
    required_structures: list[dict[str, Any]] = Field(default_factory=list)
    required_character_states: list[dict[str, Any]] = Field(default_factory=list)
    required_relationships: list[dict[str, Any]] = Field(default_factory=list)
    allowed_variation: dict[str, Any] = Field(default_factory=dict)
    excluded_interpretations: list[str] = Field(default_factory=list)
    relative_geometry_constraints: dict[str, Any] = Field(default_factory=dict)
    colour_constraints: dict[str, Any] = Field(default_factory=dict)
    literature_constraints: list[dict[str, Any]] = Field(default_factory=list)
    label_requirements: list[str] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)
    generation_notes: str | None = None
    media_type: MediaType = MediaType.STATIC_ILLUSTRATION
    provenance: dict[str, Any] = Field(default_factory=dict)


class CreateValidationRunRequest(BaseModel):
    asset_id: str
    figure_spec_id: UUID
    vision_analysis_id: UUID | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class RecordConformanceCheckRequest(BaseModel):
    validation_run_id: UUID
    character_id: UUID | None = None
    expected_state_or_range: dict[str, Any]
    observed_state_or_value: dict[str, Any] | None = None
    result: ConformanceResult
    confidence: float = 0.0
    notes: str | None = None


# ---------------------------------------------------------------------------
# Reference Sets
# ---------------------------------------------------------------------------


@router.post("/reference-sets", status_code=201)
def create_reference_set(
    body: CreateReferenceSetRequest,
    svc: VisionLexiconService = Depends(_get_service),
) -> dict[str, Any]:
    try:
        result = svc.create_reference_set(
            title=body.title,
            target_concept_id=body.target_concept_id,
            created_by=body.created_by,
            taxon_scope=body.taxon_scope,
            description=body.description,
            license_summary=body.license_summary,
            notes=body.notes,
            provenance=body.provenance,
        )
    except VisionLexiconError as exc:
        raise _translate(exc)
    return _dc_to_dict(result)


@router.get("/reference-sets/{reference_set_id}")
def get_reference_set(
    reference_set_id: UUID,
    svc: VisionLexiconService = Depends(_get_service),
) -> dict[str, Any]:
    try:
        return _dc_to_dict(svc.get_reference_set(reference_set_id))
    except VisionLexiconError as exc:
        raise _translate(exc)


@router.post("/reference-sets/{reference_set_id}/items", status_code=201)
def add_set_item(
    reference_set_id: UUID,
    body: AddSetItemRequest,
    svc: VisionLexiconService = Depends(_get_service),
) -> dict[str, Any]:
    try:
        result = svc.add_set_item(
            reference_set_id,
            image_id=body.image_id,
            calibration_status=body.calibration_status,
            image_quality_state=body.image_quality_state,
            taxon_id=body.taxon_id,
            taxon_confidence=body.taxon_confidence,
            developmental_stage=body.developmental_stage,
            orientation_context=body.orientation_context,
            scale_information=body.scale_information,
            source=body.source,
            license=body.license,
            inclusion_reason=body.inclusion_reason,
            license_usages=tuple(body.license_usages),
            provenance=body.provenance,
        )
    except VisionLexiconError as exc:
        raise _translate(exc)
    return _dc_to_dict(result)


@router.get("/lexicon/concepts/{concept_id}/reference-sets")
def list_reference_sets_for_concept(
    concept_id: UUID,
    svc: VisionLexiconService = Depends(_get_service),
) -> list[dict[str, Any]]:
    return [_dc_to_dict(r) for r in svc.list_reference_sets_for_concept(concept_id)]


# ---------------------------------------------------------------------------
# Vision Analyses
# ---------------------------------------------------------------------------


@router.post("/analyses", status_code=201)
def request_analysis(
    body: RequestAnalysisRequest,
    svc: VisionLexiconService = Depends(_get_service),
) -> dict[str, Any]:
    try:
        result = svc.request_analysis(
            image_id=body.image_id,
            reference_set_id=body.reference_set_id,
            taxon_context=body.taxon_context,
            image_url=body.image_url,
        )
    except VisionLexiconError as exc:
        raise _translate(exc)
    return _dc_to_dict(result)


@router.get("/analyses/{analysis_id}")
def get_analysis(
    analysis_id: UUID,
    svc: VisionLexiconService = Depends(_get_service),
) -> dict[str, Any]:
    try:
        return _dc_to_dict(svc.get_analysis(analysis_id))
    except VisionLexiconError as exc:
        raise _translate(exc)


@router.get("/analyses/{analysis_id}/observations")
def list_observations(
    analysis_id: UUID,
    svc: VisionLexiconService = Depends(_get_service),
) -> list[dict[str, Any]]:
    try:
        svc.get_analysis(analysis_id)  # 404 guard
    except VisionLexiconError as exc:
        raise _translate(exc)
    return [_dc_to_dict(o) for o in svc.list_observations(analysis_id)]


@router.get("/analyses/{analysis_id}/morphometrics")
def list_morphometrics(
    analysis_id: UUID,
    svc: VisionLexiconService = Depends(_get_service),
) -> list[dict[str, Any]]:
    try:
        svc.get_analysis(analysis_id)
    except VisionLexiconError as exc:
        raise _translate(exc)
    return [_dc_to_dict(m) for m in svc.list_morphometrics(analysis_id)]


@router.get("/analyses/{analysis_id}/regions")
def list_regions(
    analysis_id: UUID,
    svc: VisionLexiconService = Depends(_get_service),
) -> list[dict[str, Any]]:
    try:
        svc.get_analysis(analysis_id)
    except VisionLexiconError as exc:
        raise _translate(exc)
    return [_dc_to_dict(r) for r in svc.list_regions(analysis_id)]


# ---------------------------------------------------------------------------
# Record observations (internal / governed)
# ---------------------------------------------------------------------------


@router.post("/observations", status_code=201)
def record_observation(
    body: RecordObservationRequest,
    svc: VisionLexiconService = Depends(_get_service),
) -> dict[str, Any]:
    try:
        result = svc.record_character_observation(
            analysis_id=body.analysis_id,
            region_id=body.region_id,
            concept_id=body.concept_id,
            character_id=body.character_id,
            character_state_id=body.character_state_id,
            numeric_value=body.numeric_value,
            unit=body.unit,
            relative_value=body.relative_value,
            measurement_basis=body.measurement_basis,
            calibration_basis=body.calibration_basis,
            confidence=body.confidence,
            method=body.method,
            colour_evidence_class=body.colour_evidence_class,
            cannot_determine=body.cannot_determine,
            limitations=tuple(body.limitations),
            provenance=body.provenance,
        )
    except (VisionLexiconError, ValueError) as exc:
        if isinstance(exc, VisionLexiconError):
            raise _translate(exc)
        raise HTTPException(422, detail={"code": str(exc)})
    return _dc_to_dict(result)


@router.post("/morphometrics", status_code=201)
def record_morphometric(
    body: RecordMorphometricRequest,
    svc: VisionLexiconService = Depends(_get_service),
) -> dict[str, Any]:
    try:
        result = svc.record_morphometric(
            analysis_id=body.analysis_id,
            measurement_type=body.measurement_type,
            measurement_basis=body.measurement_basis,
            region_id=body.region_id,
            concept_id=body.concept_id,
            value=body.value,
            unit=body.unit,
            calibration_basis=body.calibration_basis,
            calibration_uncertainty=body.calibration_uncertainty,
            confidence=body.confidence,
            cannot_determine=body.cannot_determine,
            provenance=body.provenance,
        )
    except (VisionLexiconError, ValueError) as exc:
        if isinstance(exc, VisionLexiconError):
            raise _translate(exc)
        raise HTTPException(422, detail={"code": str(exc)})
    return _dc_to_dict(result)


@router.post("/regions", status_code=201)
def record_region(
    body: RecordRegionRequest,
    svc: VisionLexiconService = Depends(_get_service),
) -> dict[str, Any]:
    try:
        result = svc.record_region(
            analysis_id=body.analysis_id,
            label=body.label,
            concept_id=body.concept_id,
            confidence=body.confidence,
            bounding_box=body.bounding_box,
            provenance=body.provenance,
        )
    except VisionLexiconError as exc:
        raise _translate(exc)
    return _dc_to_dict(result)


# ---------------------------------------------------------------------------
# Figure Specifications
# ---------------------------------------------------------------------------


@router.post("/figure-specifications", status_code=201)
def create_figure_specification(
    body: CreateFigureSpecRequest,
    svc: VisionLexiconService = Depends(_get_service),
) -> dict[str, Any]:
    try:
        result = svc.create_figure_specification(
            target_concept_id=body.target_concept_id,
            purpose=body.purpose,
            scope=body.scope,
            created_by=body.created_by,
            taxon_scope=body.taxon_scope,
            reference_set_ids=tuple(body.reference_set_ids),
            required_structures=tuple(body.required_structures),
            required_character_states=tuple(body.required_character_states),
            required_relationships=tuple(body.required_relationships),
            allowed_variation=body.allowed_variation,
            excluded_interpretations=tuple(body.excluded_interpretations),
            relative_geometry_constraints=body.relative_geometry_constraints,
            colour_constraints=body.colour_constraints,
            literature_constraints=tuple(body.literature_constraints),
            label_requirements=tuple(body.label_requirements),
            uncertainty_notes=tuple(body.uncertainty_notes),
            generation_notes=body.generation_notes,
            media_type=body.media_type,
            provenance=body.provenance,
        )
    except VisionLexiconError as exc:
        raise _translate(exc)
    return _dc_to_dict(result)


@router.get("/figure-specifications/{figure_spec_id}")
def get_figure_specification(
    figure_spec_id: UUID,
    svc: VisionLexiconService = Depends(_get_service),
) -> dict[str, Any]:
    try:
        return _dc_to_dict(svc.get_figure_specification(figure_spec_id))
    except VisionLexiconError as exc:
        raise _translate(exc)


@router.get("/lexicon/concepts/{concept_id}/figure-specifications")
def list_figure_specs_for_concept(
    concept_id: UUID,
    svc: VisionLexiconService = Depends(_get_service),
) -> list[dict[str, Any]]:
    return [_dc_to_dict(s) for s in svc._repo.list_figure_specs_for_concept(concept_id)]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@router.post("/validation-runs", status_code=201)
def create_validation_run(
    body: CreateValidationRunRequest,
    svc: VisionLexiconService = Depends(_get_service),
) -> dict[str, Any]:
    try:
        result = svc.create_validation_run(
            asset_id=body.asset_id,
            figure_spec_id=body.figure_spec_id,
            vision_analysis_id=body.vision_analysis_id,
            provenance=body.provenance,
        )
    except VisionLexiconError as exc:
        raise _translate(exc)
    return _dc_to_dict(result)


@router.post("/conformance-checks", status_code=201)
def record_conformance_check(
    body: RecordConformanceCheckRequest,
    svc: VisionLexiconService = Depends(_get_service),
) -> dict[str, Any]:
    try:
        result = svc.record_conformance_check(
            validation_run_id=body.validation_run_id,
            character_id=body.character_id,
            expected_state_or_range=body.expected_state_or_range,
            observed_state_or_value=body.observed_state_or_value,
            result=body.result,
            confidence=body.confidence,
            notes=body.notes,
        )
    except VisionLexiconError as exc:
        raise _translate(exc)
    return _dc_to_dict(result)


@router.get("/validation-runs/{run_id}/conformance-checks")
def list_conformance_checks(
    run_id: UUID,
    svc: VisionLexiconService = Depends(_get_service),
) -> list[dict[str, Any]]:
    try:
        run = svc._repo.get_validation_run(run_id)
        if run is None:
            raise VisionLexiconError("VALIDATION_RUN_NOT_FOUND")
    except VisionLexiconError as exc:
        raise _translate(exc)
    return [_dc_to_dict(c) for c in svc.list_conformance_checks(run_id)]


# ---------------------------------------------------------------------------
# Aggregate summaries
# ---------------------------------------------------------------------------


@router.get("/reference-sets/{reference_set_id}/aggregate-summary")
def aggregate_reference_set_summary(
    reference_set_id: UUID,
    svc: VisionLexiconService = Depends(_get_service),
) -> dict[str, Any]:
    try:
        return svc.aggregate_reference_set_summary(reference_set_id)
    except VisionLexiconError as exc:
        raise _translate(exc)


# ---------------------------------------------------------------------------
# Frontend evidence summary
# ---------------------------------------------------------------------------


@router.get("/lexicon/concepts/{concept_id}/vision-evidence")
def concept_vision_evidence(
    concept_id: UUID,
    svc: VisionLexiconService = Depends(_get_service),
) -> dict[str, Any]:
    """Frontend-facing concept evidence summary.

    Returns all vision evidence consolidated so the Famous Lexicon frontend
    does not need to reconstruct scientific assertions from raw database tables.
    """
    return _dc_to_dict(svc.get_concept_evidence_summary(concept_id))
