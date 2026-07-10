"""BUILD-049 authenticated harvester command center routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
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


def verified_actor(auth: dict[str, object] = Depends(verify_owner_or_api_key), header_actor: str = Depends(actor)) -> str:
    return str(auth.get("actor") or header_actor)


@router.post("/{harvester_id}/run-once")
def run_once(harvester_id: str, owner: str = Depends(verified_actor)) -> dict[str, Any]:
    try:
        return control_plane.run_once(harvester_id, owner)
    except KeyError as exc:
        raise not_found(exc) from exc


@router.post("/{harvester_id}/pause")
def pause(harvester_id: str, owner: str = Depends(verified_actor)) -> dict[str, Any]:
    try:
        return control_plane.pause(harvester_id, owner)
    except KeyError as exc:
        raise not_found(exc) from exc


@router.post("/{harvester_id}/resume")
def resume(harvester_id: str, owner: str = Depends(verified_actor)) -> dict[str, Any]:
    try:
        return control_plane.resume(harvester_id, owner)
    except KeyError as exc:
        raise not_found(exc) from exc


@router.post("/{harvester_id}/retire")
def retire(harvester_id: str, owner: str = Depends(verified_actor)) -> dict[str, Any]:
    try:
        return control_plane.retire(harvester_id, owner)
    except KeyError as exc:
        raise not_found(exc) from exc


@router.post("/{harvester_id}/restore")
def restore(harvester_id: str, owner: str = Depends(verified_actor)) -> dict[str, Any]:
    try:
        return control_plane.restore(harvester_id, owner)
    except KeyError as exc:
        raise not_found(exc) from exc


@router.post("/{harvester_id}/target-proposals")
def propose_target_change(harvester_id: str, request: TargetProposalRequest, owner: str = Depends(verified_actor)) -> dict[str, Any]:
    try:
        return control_plane.propose_target_change(harvester_id, request.proposed_assignment, request.rationale)
    except KeyError as exc:
        raise not_found(exc) from exc


@router.post("/{harvester_id}/target-proposals/{proposal_id}/approve")
def approve_target_change(harvester_id: str, proposal_id: str, owner: str = Depends(verified_actor)) -> dict[str, Any]:
    try:
        return control_plane.approve_proposal(harvester_id, proposal_id, owner)
    except KeyError as exc:
        raise not_found(exc) from exc


@router.post("/{harvester_id}/target-proposals/{proposal_id}/reject")
def reject_target_change(harvester_id: str, proposal_id: str, owner: str = Depends(verified_actor)) -> dict[str, Any]:
    try:
        return control_plane.reject_proposal(harvester_id, proposal_id, owner)
    except KeyError as exc:
        raise not_found(exc) from exc


@router.patch("/{harvester_id}/schedule")
def update_schedule(harvester_id: str, request: ScheduleRequest, owner: str = Depends(verified_actor)) -> dict[str, Any]:
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


@router.post("/{harvester_id}/reassess")
def request_reassessment(harvester_id: str, owner: str = Depends(verified_actor)) -> dict[str, Any]:
    try:
        return control_plane.reassess(harvester_id)
    except KeyError as exc:
        raise not_found(exc) from exc
