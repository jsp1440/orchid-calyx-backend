"""Protected owner-scoped OASIS greenhouse decision-support routes."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.oasis_operational import OasisService

router = APIRouter(prefix="/brain/mission-control/oasis", tags=["mission-control-oasis"])
_service_instance = OasisService()
OwnerIdentity = Annotated[dict[str, object], Depends(verify_owner_or_api_key)]


def _service() -> OasisService:
    return _service_instance


def _owner(identity: dict[str, object]) -> str:
    actor = str(identity.get("actor") or "").strip()
    if not actor:
        raise HTTPException(status_code=403, detail="OASIS owner scope unavailable")
    return actor


class SpaceRequest(BaseModel):
    space_id: str
    label: str
    conservatory_location_id: str
    notes: str | None = None


class SensorRequest(BaseModel):
    sensor_id: str
    space_id: str
    metric: str
    unit: str
    source: str


class ThresholdRequest(BaseModel):
    thresholds: list[dict[str, Any]] = Field(min_length=1, max_length=20)


class AssignmentRequest(BaseModel):
    space_id: str


class ObservationRequest(BaseModel):
    sensor_id: str
    value: float | str
    observed_at: str
    quality: str = "accepted"


class EvaluationRequest(BaseModel):
    evaluated_at: str


class AcknowledgeRequest(BaseModel):
    acknowledged_at: str
    suppress_until: str | None = None
    repeat_enabled: bool = True


class InterventionRequest(BaseModel):
    intervention_type: str
    performed_at: str
    notes: str | None = None
    handoff_to_conservatory: bool = True


class OutcomeRequest(BaseModel):
    recorded_at: str
    state: str
    notes: str | None = None


def _translate(call):
    try:
        return call()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/spaces")
def configure_space(request: SpaceRequest, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _service().configure_space(_owner(identity), request.model_dump()))


@router.post("/sensors")
def register_sensor(request: SensorRequest, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _service().register_sensor(_owner(identity), request.model_dump()))


@router.put("/plants/{plant_id}/thresholds")
def set_thresholds(plant_id: str, request: ThresholdRequest, identity: OwnerIdentity) -> dict:
    return _translate(
        lambda: _service().set_thresholds(_owner(identity), plant_id, request.thresholds)
    )


@router.put("/plants/{plant_id}/assignment")
def assign_plant(plant_id: str, request: AssignmentRequest, identity: OwnerIdentity) -> dict:
    return _translate(
        lambda: _service().assign_plant(_owner(identity), plant_id, request.space_id)
    )


@router.post("/observations")
def observe(request: ObservationRequest, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _service().observe(_owner(identity), request.model_dump()))


@router.post("/plants/{plant_id}/evaluate")
def evaluate(plant_id: str, request: EvaluationRequest, identity: OwnerIdentity) -> dict:
    return _translate(
        lambda: _service().evaluate(
            _owner(identity), plant_id, evaluated_at=request.evaluated_at
        )
    )


@router.post("/recommendations/{recommendation_id}/acknowledge")
def acknowledge(
    recommendation_id: str,
    request: AcknowledgeRequest,
    identity: OwnerIdentity,
) -> dict:
    owner = _owner(identity)
    return _translate(
        lambda: _service().acknowledge(
            owner,
            recommendation_id,
            actor=owner,
            acknowledged_at=request.acknowledged_at,
            suppress_until=request.suppress_until,
            repeat_enabled=request.repeat_enabled,
        )
    )


@router.post("/recommendations/{recommendation_id}/interventions")
def intervene(
    recommendation_id: str,
    request: InterventionRequest,
    identity: OwnerIdentity,
) -> dict:
    owner = _owner(identity)
    return _translate(
        lambda: _service().record_intervention(
            owner,
            recommendation_id,
            intervention_type=request.intervention_type,
            performed_at=request.performed_at,
            actor=owner,
            notes=request.notes,
            handoff_to_conservatory=request.handoff_to_conservatory,
        )
    )


@router.post("/interventions/{intervention_id}/outcomes")
def outcome(intervention_id: str, request: OutcomeRequest, identity: OwnerIdentity) -> dict:
    return _translate(
        lambda: _service().record_outcome(
            _owner(identity),
            intervention_id,
            recorded_at=request.recorded_at,
            state=request.state,
            notes=request.notes,
        )
    )


@router.get("/status")
def status(identity: OwnerIdentity) -> dict:
    return _service().status(_owner(identity))
