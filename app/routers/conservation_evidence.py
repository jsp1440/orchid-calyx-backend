"""Protected Mission Control routes for conservation evidence."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.conservation_evidence import ConservationEvidenceService

router = APIRouter(prefix="/brain/mission-control/conservation", tags=["mission-control-conservation"])
_service_instance = ConservationEvidenceService()
Identity = Annotated[dict[str, object], Depends(verify_owner_or_api_key)]


def _service() -> ConservationEvidenceService:
    return _service_instance


def _owner(identity: dict[str, object]) -> str:
    actor = str(identity.get("actor") or "").strip()
    if not actor:
        raise HTTPException(status_code=403, detail={"code": "CONSERVATION_OWNER_SCOPE_REQUIRED"})
    return actor


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail={"code": "CONSERVATION_RECORD_NOT_FOUND", "detail": str(exc)})
    return HTTPException(status_code=422, detail={"code": str(exc).split(":", 1)[0], "detail": str(exc)})


class EvidenceReference(BaseModel):
    literature_run_id: str
    span_id: int = Field(ge=1)


class AssessmentRequest(BaseModel):
    assessment_id: str
    taxon: dict[str, str]
    source_authority: str
    assessment_version: str
    assessment_date: str
    category_system: str
    category: str
    population: dict[str, Any] = Field(default_factory=dict)
    trend: str = ""
    threats: list[dict[str, Any] | str] = Field(default_factory=list, max_length=500)
    protected_areas: list[dict[str, Any] | str] = Field(default_factory=list, max_length=500)
    actions: list[dict[str, Any] | str] = Field(default_factory=list, max_length=500)
    evidence: EvidenceReference
    confidence: float = Field(ge=0, le=1)
    conflicts: list[dict[str, Any] | str] = Field(default_factory=list, max_length=500)
    occurrence_evidence_ids: list[str] = Field(default_factory=list, max_length=500)
    atlas_feature_ids: list[str] = Field(default_factory=list, max_length=500)


@router.put("/{assessment_id}")
def record_assessment(assessment_id: str, request: AssessmentRequest, identity: Identity) -> dict[str, Any]:
    try:
        payload = request.model_dump()
        payload["assessment_id"] = assessment_id
        return _service().record(_owner(identity), payload)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/{assessment_id}")
def get_assessment(assessment_id: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().get(_owner(identity), assessment_id)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("")
def review_queue(identity: Identity) -> dict[str, Any]:
    return _service().review_queue(_owner(identity))


@router.post("/stage")
def stage(identity: Identity, limit: int = Query(default=100, ge=1, le=5000)) -> dict[str, Any]:
    try:
        return _service().stage(_owner(identity), limit=limit)
    except (TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/status/readiness")
def readiness(identity: Identity) -> dict[str, Any]:
    return _service().readiness(_owner(identity))
