"""Protected Mission Control routes for governed post-publication monitoring."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.post_publication_monitoring import PostPublicationMonitoringService

router = APIRouter(prefix="/brain/mission-control/publication-monitoring", tags=["mission-control-publication-monitoring"])
_service_instance = PostPublicationMonitoringService()
Identity = Annotated[dict[str, object], Depends(verify_owner_or_api_key)]


def _service() -> PostPublicationMonitoringService:
    return _service_instance


def _owner(identity: dict[str, object]) -> str:
    actor = str(identity.get("actor") or "").strip()
    if not actor:
        raise HTTPException(status_code=403, detail={"code": "MONITOR_OWNER_SCOPE_REQUIRED"})
    return actor


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail={"code": "MONITOR_PUBLICATION_NOT_FOUND", "detail": str(exc)})
    if isinstance(exc, RuntimeError):
        return HTTPException(status_code=409, detail={"code": str(exc).split(":", 1)[0], "detail": str(exc)})
    return HTTPException(status_code=422, detail={"code": str(exc).split(":", 1)[0], "detail": str(exc)})


class PublicationRegistrationRequest(BaseModel):
    publication_id: str
    assertion_id: str
    ledger_id: str
    ledger_revision_id: str
    ledger_hash: str
    published_at: str
    approved_at: str
    approval_ttl_days: int = Field(default=365, ge=1, le=3650)
    confidence: float = Field(ge=0, le=1)
    evidence: list[dict[str, Any]] = Field(min_length=1, max_length=5000)
    provenance: list[dict[str, Any] | str] = Field(default_factory=list, max_length=5000)


class MonitoringObservationRequest(BaseModel):
    observed_at: str
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=5000)


@router.put("/publications/{publication_id}")
def register_publication(publication_id: str, request: PublicationRegistrationRequest, identity: Identity) -> dict[str, Any]:
    try:
        payload = request.model_dump()
        payload["publication_id"] = publication_id
        return _service().register_publication(_owner(identity), payload)
    except (FileNotFoundError, RuntimeError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/publications/{publication_id}")
def get_publication(publication_id: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().get_publication(_owner(identity), publication_id)
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/publications/{publication_id}/observe")
def observe_publication(publication_id: str, request: MonitoringObservationRequest, identity: Identity) -> dict[str, Any]:
    try:
        payload = request.model_dump(exclude_none=True)
        return _service().observe(_owner(identity), publication_id, payload)
    except (FileNotFoundError, RuntimeError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/publications/{publication_id}/tasks")
def publication_tasks(publication_id: str, identity: Identity) -> dict[str, Any]:
    try:
        _service().get_publication(_owner(identity), publication_id)
        return _service().review_tasks(_owner(identity), publication_id)
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/publications/{publication_id}/status")
def publication_status(publication_id: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().status(_owner(identity), publication_id)
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc
