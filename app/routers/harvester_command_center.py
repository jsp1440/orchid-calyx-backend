"""Protected Mission Control harvester command-center routes for CALYX issue #455."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.security import verify_owner_or_api_key
from runtime.harvester_command_center import CommandError, HarvesterCommandCenter

router = APIRouter(prefix="/brain/mission-control/harvesters", tags=["mission-control-harvesters"])
_service_instance = HarvesterCommandCenter()
Identity = Annotated[dict[str, object], Depends(verify_owner_or_api_key)]


def _service() -> HarvesterCommandCenter:
    return _service_instance


def _actor(identity: dict[str, object]) -> str:
    actor = str(identity.get("actor") or "").strip()
    if not actor:
        raise HTTPException(status_code=403, detail={"code": "OWNER_SCOPE_REQUIRED", "message": "Harvester owner scope unavailable"})
    return actor


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, CommandError):
        status = 404 if exc.code == "HARVESTER_NOT_FOUND" else 409 if exc.code.startswith("CONFIRMATION") else 422
        return HTTPException(status_code=status, detail={"code": exc.code, "message": exc.detail})
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail={"code": "HARVESTER_NOT_FOUND", "message": f"Unknown harvester: {exc.args[0]}"})
    return HTTPException(status_code=422, detail={"code": "HARVESTER_COMMAND_INVALID", "message": str(exc)})


class PreviewRequest(BaseModel):
    action: str
    schedule: str | None = None


class CommandRequest(BaseModel):
    action: str
    confirmed: bool = False
    confirmation_phrase: str | None = None
    schedule: str | None = None


@router.get("")
def list_state(identity: Identity) -> dict:
    _actor(identity)
    try:
        return _service().list_state()
    except (KeyError, ValueError, CommandError) as exc:
        raise _error(exc) from exc


@router.get("/readiness")
def readiness(identity: Identity) -> dict:
    _actor(identity)
    return _service().readiness()


@router.get("/{harvester_id}")
def detail(harvester_id: str, identity: Identity) -> dict:
    _actor(identity)
    try:
        return _service().detail(harvester_id)
    except (KeyError, ValueError, CommandError) as exc:
        raise _error(exc) from exc


@router.post("/{harvester_id}/preview")
def preview(harvester_id: str, request: PreviewRequest, identity: Identity) -> dict:
    _actor(identity)
    try:
        return _service().preview(harvester_id, request.action, schedule=request.schedule)
    except (KeyError, ValueError, CommandError) as exc:
        raise _error(exc) from exc


@router.post("/{harvester_id}/commands")
def command(harvester_id: str, request: CommandRequest, identity: Identity) -> dict:
    try:
        return _service().execute(
            harvester_id,
            request.action,
            _actor(identity),
            confirmed=request.confirmed,
            confirmation_phrase=request.confirmation_phrase,
            schedule=request.schedule,
        )
    except (KeyError, ValueError, CommandError) as exc:
        raise _error(exc) from exc
