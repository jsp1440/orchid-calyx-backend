"""Protected Mission Control routes for CALYX grant and funding intelligence."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.grant_funding import GrantFundingService

router = APIRouter(prefix="/brain/mission-control/funding", tags=["mission-control-funding"])
_service_instance = GrantFundingService()
Identity = Annotated[dict[str, object], Depends(verify_owner_or_api_key)]


def _service() -> GrantFundingService:
    return _service_instance


def _owner(identity: dict[str, object]) -> str:
    actor = str(identity.get("actor") or "").strip()
    if not actor:
        raise HTTPException(status_code=403, detail={"code": "FUNDING_OWNER_SCOPE_REQUIRED"})
    return actor


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail={"code": "FUNDING_RECORD_NOT_FOUND", "detail": str(exc)})
    return HTTPException(status_code=422, detail={"code": str(exc).split(":", 1)[0], "detail": str(exc)})


class ProfileRequest(BaseModel):
    profile_id: str
    organization: str
    organization_type: str = ""
    jurisdiction: str = ""
    mission: str = ""
    project_name: str
    project_summary: str = ""
    focus_areas: list[str] = Field(default_factory=list, max_length=100)
    geographies: list[str] = Field(default_factory=list, max_length=100)
    eligible_entity_types: list[str] = Field(default_factory=list, max_length=100)
    requested_currency: str = "USD"
    requested_amount: float | None = Field(default=None, ge=0)


class OpportunityRequest(BaseModel):
    opportunity_id: str
    funder: str
    title: str
    description: str = ""
    source_url: str
    retrieved_at: str
    jurisdiction: str = ""
    currency: str = "USD"
    amount_min: float | None = Field(default=None, ge=0)
    amount_max: float | None = Field(default=None, ge=0)
    deadline: str | None = None
    deadline_confidence: float | None = Field(default=None, ge=0, le=1)
    eligibility: dict[str, Any] = Field(default_factory=dict)
    requirements: list[dict[str, Any] | str] = Field(default_factory=list, max_length=500)
    focus_areas: list[str] = Field(default_factory=list, max_length=100)
    geographies: list[str] = Field(default_factory=list, max_length=100)
    contact: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any] = Field(default_factory=dict)


@router.put("/profiles/{profile_id}")
def save_profile(profile_id: str, request: ProfileRequest, identity: Identity) -> dict[str, Any]:
    try:
        payload = request.model_dump()
        payload["profile_id"] = profile_id
        return _service().save_profile(_owner(identity), payload)
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/profiles/{profile_id}")
def get_profile(profile_id: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().get_profile(_owner(identity), profile_id)
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc


@router.put("/opportunities/{opportunity_id}")
def record_opportunity(opportunity_id: str, request: OpportunityRequest, identity: Identity) -> dict[str, Any]:
    try:
        payload = request.model_dump()
        payload["opportunity_id"] = opportunity_id
        return _service().record_opportunity(_owner(identity), payload)
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/opportunities/{opportunity_id}")
def get_opportunity(opportunity_id: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().get_opportunity(_owner(identity), opportunity_id)
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/profiles/{profile_id}/opportunities/{opportunity_id}/assess")
def assess(profile_id: str, opportunity_id: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().assess_fit(_owner(identity), profile_id, opportunity_id)
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/profiles/{profile_id}/opportunities/{opportunity_id}/draft")
def create_draft(profile_id: str, opportunity_id: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().create_draft(_owner(identity), profile_id, opportunity_id)
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/profiles/{profile_id}/opportunities/{opportunity_id}/readiness")
def readiness(profile_id: str, opportunity_id: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().readiness(_owner(identity), profile_id, opportunity_id)
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc
