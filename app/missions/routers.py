from typing import Any, Callable

import psycopg
from fastapi import APIRouter, Depends, HTTPException

from app.routers.health import add_mission_control_cors_headers
from app.security import verify_owner_or_api_key

from .dependencies import get_mission_service
from .schemas import ActorReason, CycleRequest, MissionCreate, MissionPatch
from .services import MissionService

router = APIRouter(prefix="/api/missions", tags=["controlled-missions"], dependencies=[Depends(verify_owner_or_api_key), Depends(add_mission_control_cors_headers)])
templates_router = APIRouter(prefix="/api/mission-templates", tags=["controlled-missions"], dependencies=[Depends(verify_owner_or_api_key), Depends(add_mission_control_cors_headers)])
runtime_queue_router = APIRouter(prefix="/api/runtime", tags=["controlled-mission-runtime"], dependencies=[Depends(verify_owner_or_api_key), Depends(add_mission_control_cors_headers)])


def _invoke(operation: Callable[[], Any]) -> Any:
    try:
        return operation()
    except LookupError as exc:
        raise HTTPException(404, detail={"code": str(exc)}) from exc
    except psycopg.errors.UniqueViolation as exc:
        raise HTTPException(409, detail={"code": "MISSION_CONFLICT"}) from exc
    except RuntimeError as exc:
        raise HTTPException(503, detail={"code": "MISSION_DATABASE_UNAVAILABLE"}) from exc
    except ValueError as exc:
        status = 409 if "CONFLICT" in str(exc) else 422
        raise HTTPException(status, detail={"code": str(exc)}) from exc


@router.post("", status_code=201)
def create_mission(payload: MissionCreate, auth: dict[str, object] = Depends(verify_owner_or_api_key), service: MissionService = Depends(get_mission_service)) -> dict[str, Any]:
    return _invoke(lambda: service.create(payload.model_dump(mode="json"), auth))


@router.get("")
def list_missions(service: MissionService = Depends(get_mission_service)) -> dict[str, Any]:
    return {"items": _invoke(service.list)}


@router.get("/{mission_id}")
def get_mission(mission_id: int, service: MissionService = Depends(get_mission_service)) -> dict[str, Any]:
    return _invoke(lambda: service.get(mission_id))


@router.patch("/{mission_id}")
def update_mission(mission_id: int, payload: MissionPatch, service: MissionService = Depends(get_mission_service)) -> dict[str, Any]:
    return _invoke(lambda: service.update(mission_id, payload.model_dump(mode="json", exclude_none=True)))


@router.post("/{mission_id}/submit")
def submit_mission(mission_id: int, payload: ActorReason, service: MissionService = Depends(get_mission_service)) -> dict[str, Any]:
    return _invoke(lambda: service.submit(mission_id, payload.actor, payload.reason))


@router.post("/{mission_id}/approve")
def approve_mission(mission_id: int, payload: ActorReason, service: MissionService = Depends(get_mission_service)) -> dict[str, Any]:
    return _invoke(lambda: service.approve(mission_id, payload.actor, payload.reason, payload.approval_reference, payload.publication_authority))


@router.post("/{mission_id}/reject")
def reject_mission(mission_id: int, payload: ActorReason, service: MissionService = Depends(get_mission_service)) -> dict[str, Any]:
    return _invoke(lambda: service.reject(mission_id, payload.actor, payload.reason))


@router.post("/{mission_id}/queue")
def queue_mission(mission_id: int, payload: ActorReason, service: MissionService = Depends(get_mission_service)) -> dict[str, Any]:
    return _invoke(lambda: service.queue(mission_id, payload.actor, payload.reason))


@router.post("/{mission_id}/pause")
def pause_mission(mission_id: int, payload: ActorReason, service: MissionService = Depends(get_mission_service)) -> dict[str, Any]:
    return _invoke(lambda: service.pause(mission_id, payload.actor, payload.reason))


@router.post("/{mission_id}/resume")
def resume_mission(mission_id: int, payload: ActorReason, service: MissionService = Depends(get_mission_service)) -> dict[str, Any]:
    return _invoke(lambda: service.resume(mission_id, payload.actor, payload.reason))


@router.post("/{mission_id}/cancel")
def cancel_mission(mission_id: int, payload: ActorReason, service: MissionService = Depends(get_mission_service)) -> dict[str, Any]:
    return _invoke(lambda: service.cancel(mission_id, payload.actor, payload.reason))


@router.post("/{mission_id}/retry")
def retry_mission(mission_id: int, payload: ActorReason, service: MissionService = Depends(get_mission_service)) -> dict[str, Any]:
    return _invoke(lambda: service.retry(mission_id, payload.actor, payload.reason))


@router.get("/{mission_id}/jobs")
def mission_jobs(mission_id: int, service: MissionService = Depends(get_mission_service)) -> dict[str, Any]:
    return {"items": _invoke(lambda: service.jobs(mission_id))}


@router.get("/{mission_id}/events")
def mission_events(mission_id: int, service: MissionService = Depends(get_mission_service)) -> dict[str, Any]:
    return {"items": _invoke(lambda: service.events(mission_id))}


@router.post("/{mission_id}/execute-one")
def execute_one(mission_id: int, payload: CycleRequest, service: MissionService = Depends(get_mission_service)) -> dict[str, Any]:
    return _invoke(lambda: service.run_one(mission_id, payload.worker_id))


@templates_router.get("")
def mission_templates(service: MissionService = Depends(get_mission_service)) -> dict[str, Any]:
    return {"items": _invoke(service.templates)}


@runtime_queue_router.get("/queue")
def runtime_queue(service: MissionService = Depends(get_mission_service)) -> dict[str, Any]:
    return _invoke(service.queue_status)


@runtime_queue_router.get("/dead-letter")
def dead_letter(service: MissionService = Depends(get_mission_service)) -> dict[str, Any]:
    return {"items": _invoke(service.dead_letters)}


@runtime_queue_router.post("/cycle")
def runtime_cycle(payload: CycleRequest, service: MissionService = Depends(get_mission_service)) -> dict[str, Any]:
    _invoke(lambda: service.enqueue_cycle(payload.worker_id))
    return _invoke(lambda: service.execute_cycle(payload.worker_id, payload.limit))
