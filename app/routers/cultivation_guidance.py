from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.cultivation_guidance import CultivationGuidanceService

router = APIRouter(
    prefix="/brain/mission-control/cultivation",
    tags=["mission-control-cultivation"],
)
Identity = Annotated[dict[str, object], Depends(verify_owner_or_api_key)]
_service_instance = CultivationGuidanceService()


def _service() -> CultivationGuidanceService:
    return _service_instance


def _owner(identity: dict[str, object]) -> str:
    actor = str(identity.get("actor") or identity.get("subject") or "").strip()
    if not actor:
        raise HTTPException(status_code=403, detail={"code": "CULTIVATION_OWNER_SCOPE_REQUIRED"})
    return actor


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, (FileNotFoundError, LookupError)):
        return HTTPException(status_code=404, detail={"code": str(exc) or "CULTIVATION_RECORD_NOT_FOUND"})
    return HTTPException(status_code=422, detail={"code": str(exc).split(":", 1)[0], "detail": str(exc)})


class GuidanceRequest(BaseModel):
    guidance_id: str
    version: int = Field(default=1, ge=1)
    identity: dict[str, Any]
    source_kind: str
    source: dict[str, Any] = Field(default_factory=dict)
    grower_observation: dict[str, Any] = Field(default_factory=dict)
    locality_context: dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    contradictions: list[str | dict[str, Any]] = Field(default_factory=list)
    review_state: str = "candidate"
    temperature: Any | None = None
    light: Any | None = None
    water: Any | None = None
    humidity: Any | None = None
    ventilation: Any | None = None
    rest: Any | None = None
    media: Any | None = None
    mounting: Any | None = None
    fertilization: Any | None = None
    repotting: Any | None = None


class ReviewRequest(BaseModel):
    state: str
    rationale: str = Field(min_length=1, max_length=4000)


@router.post("/guidance")
def register_guidance(request: GuidanceRequest, identity: Identity) -> dict[str, Any]:
    try:
        owner = _owner(identity)
        return _service().register_guidance(owner, request.model_dump(), actor=owner)
    except (FileNotFoundError, LookupError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/guidance/{guidance_id}/versions/{version}/review")
def review_guidance(guidance_id: str, version: int, request: ReviewRequest, identity: Identity) -> dict[str, Any]:
    try:
        owner = _owner(identity)
        return _service().review_guidance(owner, guidance_id, version, state=request.state, reviewer=owner, rationale=request.rationale)
    except (FileNotFoundError, LookupError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/profiles/{identity_key}")
def profile(identity_key: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().assemble_profile(_owner(identity), identity_key)
    except (FileNotFoundError, LookupError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/profiles/{identity_key}/handoff")
def handoff(identity_key: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().conservatory_oasis_handoff(_owner(identity), identity_key)
    except (FileNotFoundError, LookupError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/readiness")
def readiness(identity: Identity) -> dict[str, Any]:
    return _service().readiness(_owner(identity))
