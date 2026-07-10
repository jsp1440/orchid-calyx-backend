"""BUILD-049 authenticated harvester command center routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_api_key
from runtime.harvester_control import control_plane

router = APIRouter(prefix="/api/harvesters", tags=["harvesters"])


class ScheduleRequest(BaseModel):
    schedule: str = Field(min_length=1)


class TargetProposalRequest(BaseModel):
    proposed_assignment: dict[str, Any]
    rationale: str = Field(min_length=1)


def actor(x_orchid_actor: str | None = Header(default=None, alias="X-Orchid-Actor")) -> str:
    return x_orchid_actor or "authenticated_backend_actor"


def not_found(exc: KeyError) -> HTTPException:
    return HTTPException(status_code=404, detail=f"Unknown harvester: {exc.args[0]}")


@router.get("")
def list_harvesters() -> dict[str, Any]:
    return {"harvesters": control_plane.list_harvesters()}


@router.get("/{harvester_id}")
def inspect_harvester(harvester_id: str) -> dict[str, Any]:
    try:
        return {"harvester": control_plane.get_harvester(harvester_id)}
    except KeyError as exc:
        raise not_found(exc) from exc


@router.get("/{harvester_id}/runs")
def inspect_run_history(harvester_id: str) -> dict[str, Any]:
    try:
        return {"runs": control_plane.get_runs(harvester_id)}
    except KeyError as exc:
        raise not_found(exc) from exc


@router.post("/{harvester_id}/run-once", dependencies=[Depends(verify_api_key)])
def run_once(harvester_id: str, owner: str = Depends(actor)) -> dict[str, Any]:
    try:
        return control_plane.run_once(harvester_id, owner)
    except KeyError as exc:
        raise not_found(exc) from exc


@router.post("/{harvester_id}/pause", dependencies=[Depends(verify_api_key)])
def pause(harvester_id: str, owner: str = Depends(actor)) -> dict[str, Any]:
    try:
        return control_plane.pause(harvester_id, owner)
    except KeyError as exc:
        raise not_found(exc) from exc


@router.post("/{harvester_id}/resume", dependencies=[Depends(verify_api_key)])
def resume(harvester_id: str, owner: str = Depends(actor)) -> dict[str, Any]:
    try:
        return control_plane.resume(harvester_id, owner)
    except KeyError as exc:
        raise not_found(exc) from exc


@router.post("/{harvester_id}/retire", dependencies=[Depends(verify_api_key)])
def retire(harvester_id: str, owner: str = Depends(actor)) -> dict[str, Any]:
    try:
        return control_plane.retire(harvester_id, owner)
    except KeyError as exc:
        raise not_found(exc) from exc


@router.post("/{harvester_id}/restore", dependencies=[Depends(verify_api_key)])
def restore(harvester_id: str, owner: str = Depends(actor)) -> dict[str, Any]:
    try:
        return control_plane.restore(harvester_id, owner)
    except KeyError as exc:
        raise not_found(exc) from exc


@router.post("/{harvester_id}/target-proposals", dependencies=[Depends(verify_api_key)])
def propose_target_change(harvester_id: str, request: TargetProposalRequest) -> dict[str, Any]:
    try:
        return control_plane.propose_target_change(harvester_id, request.proposed_assignment, request.rationale)
    except KeyError as exc:
        raise not_found(exc) from exc


@router.post("/{harvester_id}/target-proposals/{proposal_id}/approve", dependencies=[Depends(verify_api_key)])
def approve_target_change(harvester_id: str, proposal_id: str, owner: str = Depends(actor)) -> dict[str, Any]:
    try:
        return control_plane.approve_proposal(harvester_id, proposal_id, owner)
    except KeyError as exc:
        raise not_found(exc) from exc


@router.post("/{harvester_id}/target-proposals/{proposal_id}/reject", dependencies=[Depends(verify_api_key)])
def reject_target_change(harvester_id: str, proposal_id: str, owner: str = Depends(actor)) -> dict[str, Any]:
    try:
        return control_plane.reject_proposal(harvester_id, proposal_id, owner)
    except KeyError as exc:
        raise not_found(exc) from exc


@router.patch("/{harvester_id}/schedule", dependencies=[Depends(verify_api_key)])
def update_schedule(harvester_id: str, request: ScheduleRequest, owner: str = Depends(actor)) -> dict[str, Any]:
    try:
        return control_plane.update_schedule(harvester_id, request.schedule, owner)
    except KeyError as exc:
        raise not_found(exc) from exc


@router.get("/{harvester_id}/recommendation")
def inspect_current_recommendation(harvester_id: str) -> dict[str, Any]:
    try:
        return {"recommendation": control_plane.recommendation(harvester_id)}
    except KeyError as exc:
        raise not_found(exc) from exc


@router.post("/{harvester_id}/reassess", dependencies=[Depends(verify_api_key)])
def request_reassessment(harvester_id: str) -> dict[str, Any]:
    try:
        return control_plane.reassess(harvester_id)
    except KeyError as exc:
        raise not_found(exc) from exc
