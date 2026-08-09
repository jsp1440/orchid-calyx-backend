from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.notification_service import NotificationService

router = APIRouter(
    prefix="/brain/mission-control/notifications",
    tags=["mission-control-notifications"],
)
Identity = Annotated[dict[str, object], Depends(verify_owner_or_api_key)]
_service_instance = NotificationService()


def _service() -> NotificationService:
    return _service_instance


def _owner(identity: dict[str, object]) -> str:
    actor = str(identity.get("actor") or identity.get("subject") or "").strip()
    if not actor:
        raise HTTPException(status_code=403, detail={"code": "NOTIFICATION_OWNER_SCOPE_REQUIRED"})
    return actor


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail={"code": "NOTIFICATION_RECORD_NOT_FOUND"})
    return HTTPException(status_code=422, detail={"code": str(exc).split(":", 1)[0], "detail": str(exc)})


class PreferencesRequest(BaseModel):
    recipient_id: str
    timezone: str = "UTC"
    quiet_hours: dict[str, str] = Field(default_factory=dict)
    minimum_severity: str = "info"
    digest_enabled: bool = True
    digest_group: str = "default"
    channels: list[str] = Field(default_factory=lambda: ["in_app"])


class EventRequest(BaseModel):
    event_id: str
    event_type: str
    severity: str = "medium"
    recipient_id: str
    title: str
    message: str
    source_ref: str | None = None
    dedupe_key: str | None = None
    digest_group: str | None = None


class AckRequest(BaseModel):
    note: str | None = None


class EscalateRequest(BaseModel):
    rationale: str = Field(min_length=1, max_length=4000)


class ReceiptRequest(BaseModel):
    provider: str
    provider_message_id: str | None = None
    status: str = "recorded"


@router.put("/preferences")
def save_preferences(request: PreferencesRequest, identity: Identity) -> dict[str, Any]:
    try:
        return _service().save_preferences(_owner(identity), request.model_dump())
    except (TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/events")
def create_event(request: EventRequest, identity: Identity) -> dict[str, Any]:
    try:
        return _service().create_event(_owner(identity), request.model_dump())
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/recipients/{recipient_id}/pending")
def pending(recipient_id: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().pending_for_recipient(_owner(identity), recipient_id)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/recipients/{recipient_id}/digest")
def digest(recipient_id: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().digest(_owner(identity), recipient_id)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/events/{event_id}/acknowledge")
def acknowledge(event_id: str, request: AckRequest, identity: Identity) -> dict[str, Any]:
    try:
        owner = _owner(identity)
        return _service().acknowledge(owner, event_id, actor=owner, note=request.note)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/events/{event_id}/escalate")
def escalate(event_id: str, request: EscalateRequest, identity: Identity) -> dict[str, Any]:
    try:
        owner = _owner(identity)
        return _service().escalate(owner, event_id, actor=owner, rationale=request.rationale)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/events/{event_id}/receipts")
def receipt(event_id: str, request: ReceiptRequest, identity: Identity) -> dict[str, Any]:
    try:
        return _service().record_delivery_receipt(_owner(identity), event_id, request.model_dump())
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/readiness")
def readiness(identity: Identity) -> dict[str, Any]:
    return _service().readiness(_owner(identity))
