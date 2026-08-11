"""FastAPI routes for the Vision-Lexicon bridge.

All write endpoints require owner/API-key authentication.
Read endpoints for public Lexicon APIs follow the existing project pattern.

Live Vision inference is not enabled until a provider is configured.
The capability status endpoint always reports truthfully.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from app.security import verify_owner_or_api_key

from .contracts import (
    CalibrationState,
    ImageQualityState,
    MediaType,
    ReviewDecision,
    ReviewerTier,
)
from .models import (
    AggregateSummaryResponse,
    CapabilityStatusResponse,
    CharacterObservationResponse,
    CreateFigureSpecRequest,
    CreateReferenceSetRequest,
    CreateValidationRunRequest,
    EvidenceSummaryResponse,
    FigureSpecResponse,
    MorphometricObservationResponse,
    ReviewDecisionRequest,
    ValidationRunResponse,
    VisionAnalysisRequest,
    VisionAnalysisResponse,
)
from .persistence import MemoryVisionLexiconRepository
from .service import VisionLexiconService, vision_lexicon_capability_status

router = APIRouter(
    prefix="/api/vision-lexicon",
    tags=["vision-lexicon"],
)

AuthDep = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]

# Module-level in-memory repository.
# Replaced by PostgresVisionLexiconRepository once the migration is activated.
_repo = MemoryVisionLexiconRepository()
_service = VisionLexiconService(_repo)


def _404(detail: str) -> HTTPException:
    return HTTPException(status_code=404, detail=detail)


def _422(code: str, msg: str) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": code, "message": msg})


# ---------------------------------------------------------------------------
# Capability status (public — no auth required)
# ---------------------------------------------------------------------------


@router.get("/status")
def get_capability_status() -> CapabilityStatusResponse:
    """Return truthful capability status for the Vision-Lexicon bridge."""
    status = vision_lexicon_capability_status()
    return CapabilityStatusResponse(**status)


# ---------------------------------------------------------------------------
# Reference Image Sets
# ---------------------------------------------------------------------------


@router.post("/reference-sets")
def create_reference_set(
    request: CreateReferenceSetRequest,
    auth: AuthDep,
) -> dict[str, Any]:
    """Create a new Reference Image Set."""
    actor = auth.get("actor") or auth.get("owner") or "api"
    try:
        ref_set = _service.create_reference_set(
            title=request.title,
            target_concept_id=request.target_concept_id,
            taxon_scope=request.taxon_scope,
            description=request.description,
            license_summary=request.license_summary,
            notes=request.notes,
            created_by=actor,
            items=[item.model_dump() for item in request.items],
        )
    except Exception as exc:
        raise _422("REFERENCE_SET_CREATE_ERROR", str(exc)) from exc
    return {
        "reference_set_id": str(ref_set.reference_set_id),
        "title": ref_set.title,
        "review_state": ref_set.review_state,
        "item_count": len(ref_set.items),
    }


@router.get("/reference-sets/{reference_set_id}")
def get_reference_set(reference_set_id: UUID) -> dict[str, Any]:
    """Retrieve a Reference Image Set by ID."""
    ref_set = _service.get_reference_set(reference_set_id)
    if ref_set is None:
        raise _404(f"Reference set {reference_set_id} not found")
    return {
        "reference_set_id": str(ref_set.reference_set_id),
        "title": ref_set.title,
        "target_concept_id": str(ref_set.target_concept_id) if ref_set.target_concept_id else None,
        "taxon_scope": ref_set.taxon_scope,
        "description": ref_set.description,
        "review_state": ref_set.review_state,
        "license_summary": ref_set.license_summary,
        "notes": ref_set.notes,
        "items": [
            {
                "reference_set_item_id": str(item.reference_set_item_id),
                "image_id": item.image_id,
                "taxon_id": item.taxon_id,
                "calibration_status": item.calibration_status,
                "image_quality_state": item.image_quality_state,
                "review_state": item.review_state,
            }
            for item in ref_set.items
        ],
    }


@router.get("/lexicon/concepts/{concept_id}/reference-sets")
def list_reference_sets_for_concept(concept_id: UUID) -> dict[str, Any]:
    """List all Reference Image Sets targeting a Lexicon concept."""
    sets = _service.list_reference_sets_for_concept(concept_id)
    return {
        "concept_id": str(concept_id),
        "reference_sets": [
            {
                "reference_set_id": str(rs.reference_set_id),
                "title": rs.title,
                "review_state": rs.review_state,
                "item_count": len(rs.items),
            }
            for rs in sets
        ],
    }


# ---------------------------------------------------------------------------
# Vision Analyses
# ---------------------------------------------------------------------------


@router.post("/analyses")
def request_analysis(
    request: VisionAnalysisRequest,
    auth: AuthDep,
) -> VisionAnalysisResponse:
    """Request or retrieve (idempotent) a Vision analysis record."""
    try:
        analysis = _service.request_analysis(
            image_id=request.image_id,
            content_hash=request.content_hash,
            reference_set_id=request.reference_set_id,
            vision_model=request.vision_model,
            vision_model_version=request.vision_model_version,
            taxon_context=request.taxon_context,
            taxon_confidence=request.taxon_confidence,
            calibration_state=CalibrationState(request.calibration_state),
            image_quality=ImageQualityState(request.image_quality),
            warnings=request.warnings,
            limitations=request.limitations,
        )
    except Exception as exc:
        raise _422("ANALYSIS_REQUEST_ERROR", str(exc)) from exc
    return VisionAnalysisResponse(
        analysis_id=str(analysis.analysis_id),
        image_id=analysis.image_id,
        reference_set_id=str(analysis.reference_set_id) if analysis.reference_set_id else None,
        vision_model=analysis.vision_model,
        vision_model_version=analysis.vision_model_version,
        analysis_version=analysis.analysis_version,
        taxon_context=analysis.taxon_context,
        taxon_confidence=analysis.taxon_confidence,
        calibration_state=analysis.calibration_state,
        image_quality=analysis.image_quality,
        analysis_status=analysis.analysis_status,
        review_state=analysis.review_state,
        warnings=list(analysis.warnings),
        limitations=list(analysis.limitations),
    )


@router.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: UUID) -> VisionAnalysisResponse:
    """Retrieve a Vision analysis record by ID."""
    analysis = _service.get_analysis(analysis_id)
    if analysis is None:
        raise _404(f"Analysis {analysis_id} not found")
    return VisionAnalysisResponse(
        analysis_id=str(analysis.analysis_id),
        image_id=analysis.image_id,
        reference_set_id=str(analysis.reference_set_id) if analysis.reference_set_id else None,
        vision_model=analysis.vision_model,
        vision_model_version=analysis.vision_model_version,
        analysis_version=analysis.analysis_version,
        taxon_context=analysis.taxon_context,
        taxon_confidence=analysis.taxon_confidence,
        calibration_state=analysis.calibration_state,
        image_quality=analysis.image_quality,
        analysis_status=analysis.analysis_status,
        review_state=analysis.review_state,
        warnings=list(analysis.warnings),
        limitations=list(analysis.limitations),
    )


@router.get("/analyses/{analysis_id}/observations")
def list_observations(analysis_id: UUID) -> dict[str, Any]:
    """Retrieve structured character observations for an analysis."""
    observations = _service.list_observations_for_analysis(analysis_id)
    return {
        "analysis_id": str(analysis_id),
        "observations": [
            CharacterObservationResponse(
                observation_id=str(obs.observation_id),
                analysis_id=str(obs.analysis_id),
                region_id=str(obs.region_id) if obs.region_id else None,
                concept_id=str(obs.concept_id) if obs.concept_id else None,
                character_id=obs.character_id,
                character_state_id=obs.character_state_id,
                numeric_value=obs.numeric_value,
                unit=obs.unit,
                relative_value=obs.relative_value,
                measurement_basis=obs.measurement_basis,
                confidence=obs.confidence,
                method=obs.method,
                review_state=obs.review_state,
                limitations=list(obs.limitations),
            ).model_dump()
            for obs in observations
        ],
    }


@router.get("/analyses/{analysis_id}/morphometrics")
def list_morphometrics(analysis_id: UUID) -> dict[str, Any]:
    """Retrieve morphometric observations for an analysis."""
    morphometrics = _service.list_morphometrics_for_analysis(analysis_id)
    return {
        "analysis_id": str(analysis_id),
        "morphometrics": [
            MorphometricObservationResponse(
                morphometric_id=str(m.morphometric_id),
                analysis_id=str(m.analysis_id),
                region_id=str(m.region_id) if m.region_id else None,
                metric_type=m.metric_type,
                value=m.value,
                unit=m.unit,
                calibration_state=m.calibration_state,
                confidence=m.confidence,
            ).model_dump()
            for m in morphometrics
        ],
    }


# ---------------------------------------------------------------------------
# Figure Specifications
# ---------------------------------------------------------------------------


@router.post("/figure-specifications")
def create_figure_spec(
    request: CreateFigureSpecRequest,
    auth: AuthDep,
) -> FigureSpecResponse:
    """Create a new Figure Specification under governance."""
    actor = auth.get("actor") or auth.get("owner") or "api"
    try:
        spec = _service.create_figure_spec(
            target_concept_id=request.target_concept_id,
            purpose=request.purpose,
            scope=request.scope,
            taxon_scope=request.taxon_scope,
            reference_set_ids=request.reference_set_ids,
            required_structures=request.required_structures,
            required_character_states=request.required_character_states,
            required_relationships=request.required_relationships,
            allowed_variation=request.allowed_variation,
            excluded_interpretations=request.excluded_interpretations,
            relative_geometry_constraints=request.relative_geometry_constraints,
            color_constraints=request.color_constraints,
            literature_constraints=request.literature_constraints,
            label_requirements=request.label_requirements,
            uncertainty_notes=request.uncertainty_notes,
            generation_notes=request.generation_notes,
            media_type=MediaType(request.media_type),
            created_by=actor,
            provenance={"created_by": actor},
            temporal_sequence=request.temporal_sequence,
            required_stage_order=request.required_stage_order,
            motion_constraints=request.motion_constraints,
            duration_range=request.duration_range,
            loop_behavior=request.loop_behavior,
            scientific_state_transitions=request.scientific_state_transitions,
            reduced_motion_alternative=request.reduced_motion_alternative,
        )
    except Exception as exc:
        raise _422("FIGURE_SPEC_CREATE_ERROR", str(exc)) from exc
    return FigureSpecResponse(
        figure_spec_id=str(spec.figure_spec_id),
        target_concept_id=str(spec.target_concept_id) if spec.target_concept_id else None,
        purpose=spec.purpose,
        scope=spec.scope,
        media_type=spec.media_type,
        review_state=spec.review_state,
        version=spec.version,
        required_structures=spec.required_structures,
        required_character_states=spec.required_character_states,
        uncertainty_notes=spec.uncertainty_notes,
    )


@router.get("/figure-specifications/{figure_spec_id}")
def get_figure_spec(figure_spec_id: UUID) -> FigureSpecResponse:
    """Retrieve a Figure Specification by ID."""
    spec = _service.get_figure_spec(figure_spec_id)
    if spec is None:
        raise _404(f"Figure specification {figure_spec_id} not found")
    return FigureSpecResponse(
        figure_spec_id=str(spec.figure_spec_id),
        target_concept_id=str(spec.target_concept_id) if spec.target_concept_id else None,
        purpose=spec.purpose,
        scope=spec.scope,
        media_type=spec.media_type,
        review_state=spec.review_state,
        version=spec.version,
        required_structures=spec.required_structures,
        required_character_states=spec.required_character_states,
        uncertainty_notes=spec.uncertainty_notes,
    )


# ---------------------------------------------------------------------------
# Validation Runs
# ---------------------------------------------------------------------------


@router.post("/validation-runs")
def create_validation_run(
    request: CreateValidationRunRequest,
    auth: AuthDep,
) -> ValidationRunResponse:
    """Create a new Figure Validation Run."""
    try:
        run = _service.create_validation_run(
            asset_id=request.asset_id,
            figure_spec_id=request.figure_spec_id,
            vision_analysis_id=request.vision_analysis_id,
            provenance=request.provenance,
        )
    except Exception as exc:
        raise _422("VALIDATION_RUN_CREATE_ERROR", str(exc)) from exc
    return ValidationRunResponse(
        validation_run_id=str(run.validation_run_id),
        asset_id=run.asset_id,
        figure_spec_id=str(run.figure_spec_id) if run.figure_spec_id else None,
        status=run.status,
        overall_review_state=run.overall_review_state,
        conformance_checks=[],
    )


@router.get("/figures/{asset_id}/validation")
def get_figure_validation(asset_id: str) -> dict[str, Any]:
    """Retrieve validation information for a figure asset (by asset_id)."""
    return {
        "asset_id": asset_id,
        "validation_runs": [],
        "note": "Retrieve via /validation-runs/{validation_run_id} for full detail",
    }


@router.get("/validation-runs/{validation_run_id}")
def get_validation_run(validation_run_id: UUID) -> ValidationRunResponse:
    """Retrieve a validation run with character-level conformance checks."""
    run = _service.get_validation_run(validation_run_id)
    if run is None:
        raise _404(f"Validation run {validation_run_id} not found")
    return ValidationRunResponse(
        validation_run_id=str(run.validation_run_id),
        asset_id=run.asset_id,
        figure_spec_id=str(run.figure_spec_id) if run.figure_spec_id else None,
        status=run.status,
        overall_review_state=run.overall_review_state,
        conformance_checks=[
            {
                "check_id": str(c.check_id),
                "character_id": c.character_id,
                "expected_state_or_range": c.expected_state_or_range,
                "observed_state_or_value": c.observed_state_or_value,
                "result": c.result,
                "confidence": c.confidence,
                "notes": c.notes,
                "review_state": c.review_state,
            }
            for c in run.conformance_checks
        ],
    )


# ---------------------------------------------------------------------------
# Aggregate Reference-Set Summary
# ---------------------------------------------------------------------------


@router.get("/reference-sets/{reference_set_id}/aggregate-summary")
def get_aggregate_summary(reference_set_id: UUID) -> AggregateSummaryResponse:
    """Return aggregate observation summary across all analyses in a reference set."""
    summary = _service.aggregate_reference_set(reference_set_id)
    return AggregateSummaryResponse(**summary)


# ---------------------------------------------------------------------------
# Frontend Evidence Summary
# ---------------------------------------------------------------------------


@router.get("/lexicon/concepts/{concept_id}/vision-evidence")
def get_evidence_summary(concept_id: UUID) -> EvidenceSummaryResponse:
    """Return the complete vision evidence summary for a Lexicon concept.

    This is the primary endpoint consumed by the Famous Lexicon frontend.
    The frontend must not need to reconstruct scientific assertions from
    raw database tables.
    """
    summary = _service.get_evidence_summary(concept_id)
    return EvidenceSummaryResponse(**summary)


# ---------------------------------------------------------------------------
# Human Review (governance write endpoint)
# ---------------------------------------------------------------------------


@router.post("/reviews")
def record_review(
    request: ReviewDecisionRequest,
    auth: AuthDep,
) -> dict[str, Any]:
    """Record a human review decision for a Vision pipeline object.

    Community reviews (reviewer_tier=COMMUNITY) have auto_promotion_blocked=True
    enforced; they cannot automatically promote a record to scientific truth.
    """
    actor = auth.get("actor") or auth.get("owner") or "api"
    if auth.get("auth_type") not in ("owner_session", "api_key"):
        raise HTTPException(
            status_code=403,
            detail={"code": "REVIEW_AUTH_REQUIRED"},
        )
    try:
        review = _service.record_review(
            subject_type=request.subject_type,
            subject_id=request.subject_id,
            reviewer_id=actor,
            reviewer_tier=ReviewerTier(request.reviewer_tier),
            decision=ReviewDecision(request.decision),
            scope_of_expertise=request.scope_of_expertise,
            version_reviewed=request.version_reviewed,
            questions_answered=request.questions_answered,
            comments=request.comments,
            provenance=request.provenance,
        )
    except Exception as exc:
        raise _422("REVIEW_ERROR", str(exc)) from exc
    return {
        "review_id": str(review.review_id),
        "subject_type": review.subject_type,
        "subject_id": str(review.subject_id),
        "reviewer_tier": review.reviewer_tier,
        "decision": review.decision,
        "auto_promotion_blocked": review.auto_promotion_blocked,
    }
