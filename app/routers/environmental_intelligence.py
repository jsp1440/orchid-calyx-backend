from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.environmental_intelligence import EnvironmentalIntelligenceService

router = APIRouter(
    prefix="/brain/mission-control/environment",
    tags=["mission-control-environment"],
)
Identity = Annotated[dict[str, object], Depends(verify_owner_or_api_key)]
_service_instance = EnvironmentalIntelligenceService()


def _service() -> EnvironmentalIntelligenceService:
    return _service_instance


def _owner(identity: dict[str, object]) -> str:
    actor = str(identity.get("actor") or identity.get("subject") or "").strip()
    if not actor:
        raise HTTPException(status_code=403, detail={"code": "ENV_OWNER_SCOPE_REQUIRED"})
    return actor


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, (FileNotFoundError, LookupError)):
        return HTTPException(status_code=404, detail={"code": str(exc) or "ENV_RECORD_NOT_FOUND"})
    return HTTPException(status_code=422, detail={"code": str(exc).split(":", 1)[0], "detail": str(exc)})


class EnvironmentalRecordRequest(BaseModel):
    record_id: str
    canonical_taxon_id: str
    accepted_name: str
    occurrence_id: str | None = None
    climate_variables: dict[str, Any] = Field(default_factory=dict)
    elevation: dict[str, Any] = Field(default_factory=dict)
    substrate: list[str] = Field(default_factory=list)
    habitat: list[str] = Field(default_factory=list)
    temporal_coverage: dict[str, Any] = Field(default_factory=dict)
    spatial_resolution: dict[str, Any]
    source: dict[str, Any]
    observation_state: str
    uncertainty: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any]
    review_state: str = "candidate"


class ReviewRequest(BaseModel):
    state: str
    rationale: str = Field(min_length=1, max_length=4000)


@router.post("/records")
def register_record(request: EnvironmentalRecordRequest, identity: Identity) -> dict[str, Any]:
    try:
        owner = _owner(identity)
        return _service().register_record(owner, request.model_dump(), actor=owner)
    except (FileNotFoundError, LookupError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/records/{record_id}/review")
def review_record(record_id: str, request: ReviewRequest, identity: Identity) -> dict[str, Any]:
    try:
        owner = _owner(identity)
        return _service().review_record(owner, record_id, state=request.state, reviewer=owner, rationale=request.rationale)
    except (FileNotFoundError, LookupError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/taxa/{canonical_taxon_id}/envelope")
def assemble_envelope(canonical_taxon_id: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().assemble_envelope(_owner(identity), canonical_taxon_id)
    except (FileNotFoundError, LookupError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/taxa/{canonical_taxon_id}/atlas-handoff")
def atlas_handoff(canonical_taxon_id: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().atlas_handoff(_owner(identity), canonical_taxon_id)
    except (FileNotFoundError, LookupError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/readiness")
def readiness(identity: Identity) -> dict[str, Any]:
    return _service().readiness(_owner(identity))
