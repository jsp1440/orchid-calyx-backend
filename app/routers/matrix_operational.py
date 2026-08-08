"""Protected Mission Control API for deterministic Matrix identification sessions."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.matrix_identification_registry import (
    candidates_from_registry,
    get_registry_version,
)
from runtime.matrix_operational import (
    create_identification_session,
    get_candidate_explanation,
    get_identification_session,
    resolve_candidate_name,
)

router = APIRouter(
    prefix="/brain/mission-control/matrix",
    tags=["mission-control-matrix"],
    dependencies=[Depends(verify_owner_or_api_key)],
)


class SessionRequest(BaseModel):
    registry_id: str = Field(min_length=1, max_length=120)
    version: str = Field(min_length=1, max_length=120)
    observations: list[dict[str, Any]] = Field(min_length=1, max_length=500)
    limit: int = Field(default=20, ge=1, le=200)


@router.post("/sessions")
def create_session(request: SessionRequest) -> dict:
    try:
        return create_identification_session(
            registry_id=request.registry_id,
            version=request.version,
            observations=request.observations,
            limit=request.limit,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/sessions/{session_id}")
def read_session(session_id: str) -> dict:
    try:
        return get_identification_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/sessions/{session_id}/candidates/{canonical_taxon_id}")
def candidate_explanation(session_id: str, canonical_taxon_id: str) -> dict:
    try:
        return get_candidate_explanation(session_id, canonical_taxon_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/registries/{registry_id}/{version}/resolve/{label}")
def resolve_taxon(registry_id: str, version: str, label: str) -> dict:
    try:
        registry = get_registry_version(registry_id, version)
        return resolve_candidate_name(candidates_from_registry(registry), label)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
