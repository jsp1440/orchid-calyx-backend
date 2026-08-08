"""Protected Mission Control routes for governed AI.Vision review workflows."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.ai_vision_governed import GovernedVisionService

router = APIRouter(
    prefix="/brain/mission-control/vision",
    tags=["mission-control-vision"],
    dependencies=[Depends(verify_owner_or_api_key)],
)

_service_instance = GovernedVisionService()


def _service() -> GovernedVisionService:
    return _service_instance


class AnalysisRequest(BaseModel):
    image: dict[str, Any]
    model: dict[str, Any]
    prompt: dict[str, Any]
    taxon_resolution: dict[str, Any] = Field(default_factory=dict)
    detected_parts: list[dict[str, Any]] = Field(min_length=1, max_length=100)
    character_observations: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    warnings: list[str] = Field(default_factory=list, max_length=100)


class CorrectionRequest(BaseModel):
    character_id: str
    corrected_state: str | None = None
    reviewer: str
    rationale: str
    reviewed_at: str


class MatrixHandoffRequest(BaseModel):
    registry_id: str
    version: str


@router.post("/analyses")
def submit_analysis(request: AnalysisRequest) -> dict:
    try:
        return _service().submit_analysis(request.model_dump())
    except (ValueError, PermissionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/analyses/{analysis_id}")
def get_analysis(analysis_id: str) -> dict:
    try:
        return _service().get_analysis(analysis_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/analyses/{analysis_id}/corrections")
def correct_analysis(analysis_id: str, request: CorrectionRequest) -> dict:
    try:
        return _service().correct_observation(analysis_id, **request.model_dump())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/analyses/{analysis_id}/matrix-handoff")
def handoff_matrix(analysis_id: str, request: MatrixHandoffRequest) -> dict:
    try:
        return _service().matrix_handoff(
            analysis_id,
            registry_id=request.registry_id,
            version=request.version,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
