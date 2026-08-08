"""Protected owner-scoped Conservatory routes for CALYX issue #451."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.conservatory_operational import ConservatoryService

router = APIRouter(prefix="/brain/mission-control/conservatory", tags=["mission-control-conservatory"])
_service_instance = ConservatoryService()


def _service() -> ConservatoryService:
    return _service_instance


def _owner(identity: dict[str, object]) -> str:
    actor = str(identity.get("actor") or "").strip()
    if not actor:
        raise HTTPException(status_code=403, detail="conservatory owner scope unavailable")
    return actor


class LocationRequest(BaseModel):
    location_id: str | None = None
    label: str
    zone: str | None = None
    microclimate: dict[str, Any] = Field(default_factory=dict)
    privacy: str = "private"


class IntakeRequest(BaseModel):
    import_id: str | None = None
    collection: dict[str, Any]
    accession: dict[str, Any]
    plant: dict[str, Any]
    location: dict[str, Any]
    media: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


class EventRequest(BaseModel):
    event_type: str
    occurred_at: str
    details: dict[str, Any] = Field(default_factory=dict)
    location_id: str | None = None


@router.post("/locations")
def create_location(
    request: LocationRequest,
    identity: dict[str, object] = Depends(verify_owner_or_api_key),
) -> dict:
    try:
        return _service().create_location(_owner(identity), request.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/intake")
def intake(
    request: IntakeRequest,
    identity: dict[str, object] = Depends(verify_owner_or_api_key),
) -> dict:
    try:
        return _service().intake(_owner(identity), request.model_dump())
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/plants/{plant_id}/events")
def add_event(
    plant_id: str,
    request: EventRequest,
    identity: dict[str, object] = Depends(verify_owner_or_api_key),
) -> dict:
    try:
        return _service().add_event(
            _owner(identity),
            plant_id,
            event_type=request.event_type,
            occurred_at=request.occurred_at,
            details=request.details,
            location_id=request.location_id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/plants/{plant_id}")
def dossier(
    plant_id: str,
    identity: dict[str, object] = Depends(verify_owner_or_api_key),
) -> dict:
    try:
        return _service().dossier(_owner(identity), plant_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/scan/{label_id}")
def scan(
    label_id: str,
    identity: dict[str, object] = Depends(verify_owner_or_api_key),
) -> dict:
    try:
        return _service().scan(_owner(identity), label_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/labels/{label_id}/printable")
def printable_label(
    label_id: str,
    identity: dict[str, object] = Depends(verify_owner_or_api_key),
) -> dict:
    try:
        return _service().printable_label(_owner(identity), label_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/readiness")
def readiness(identity: dict[str, object] = Depends(verify_owner_or_api_key)) -> dict:
    return _service().readiness(_owner(identity))
