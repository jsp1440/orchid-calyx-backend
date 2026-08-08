"""Protected Mission Control routes for the CALYX volunteer service."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.volunteer_service import VolunteerService

router = APIRouter(prefix="/brain/mission-control/volunteers", tags=["mission-control-volunteers"])
_service_instance = VolunteerService()
Identity = Annotated[dict[str, object], Depends(verify_owner_or_api_key)]


def _service() -> VolunteerService:
    return _service_instance


def _owner(identity: dict[str, object]) -> str:
    actor = str(identity.get("actor") or identity.get("subject") or "").strip()
    if not actor:
        raise HTTPException(status_code=403, detail={"code": "VOLUNTEER_OWNER_SCOPE_REQUIRED"})
    return actor


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail={"code": "VOLUNTEER_RECORD_NOT_FOUND", "detail": str(exc)})
    return HTTPException(status_code=422, detail={"code": str(exc).split(":", 1)[0], "detail": str(exc)})


class ProfileRequest(BaseModel):
    volunteer_id: str
    display_name: str
    contact: dict[str, Any] = Field(default_factory=dict)
    roles: list[str] = Field(default_factory=list, max_length=100)
    skills: list[str] = Field(default_factory=list, max_length=500)
    availability: list[dict[str, Any] | str] = Field(default_factory=list, max_length=500)
    accessibility_or_support_notes: str | None = None
    privacy_level: str = "private"


class AssignmentRequest(BaseModel):
    assignment_id: str
    volunteer_id: str
    title: str
    role: str
    description: str | None = None
    required_skills: list[str] = Field(default_factory=list, max_length=500)
    starts_at: str | None = None
    ends_at: str | None = None
    supervisor_id: str | None = None
    conflicts: list[dict[str, Any] | str] = Field(default_factory=list, max_length=500)


class AssignmentStateRequest(BaseModel):
    state: str
    rationale: str = Field(min_length=1, max_length=4000)


class HourLogRequest(BaseModel):
    log_id: str
    volunteer_id: str
    assignment_id: str
    service_date: str
    hours: float = Field(gt=0, le=24)
    activity: str | None = None


class HourVerificationRequest(BaseModel):
    supervisor_id: str
    decision: str
    rationale: str = Field(min_length=1, max_length=4000)


class TrainingRequest(BaseModel):
    training_id: str
    volunteer_id: str
    title: str
    completed_at: str | None = None
    instructor_or_source: str | None = None
    skills_awarded: list[str] = Field(default_factory=list, max_length=500)
    evidence: list[dict[str, Any] | str] = Field(default_factory=list, max_length=5000)
    reviewed: bool = False


class CertificateRequest(BaseModel):
    certificate_id: str
    volunteer_id: str
    title: str
    issued_at: str | None = None
    issuer: str | None = None
    recognition_basis: str | None = None
    evidence_uris: list[str] = Field(min_length=1, max_length=5000)


class RecognitionRequest(BaseModel):
    recognition_id: str
    volunteer_id: str
    category: str
    citation: str | None = None
    basis: list[dict[str, Any] | str] = Field(default_factory=list, max_length=5000)
    approved_by: str | None = None


class ConflictRequest(BaseModel):
    conflict_id: str
    volunteer_id: str
    type: str = "other"
    description: str | None = None
    mitigation: str | None = None


@router.put("/profiles/{volunteer_id}")
def save_profile(volunteer_id: str, request: ProfileRequest, identity: Identity) -> dict[str, Any]:
    try:
        payload = request.model_dump()
        payload["volunteer_id"] = volunteer_id
        return _service().save_profile(_owner(identity), payload)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/profiles/{volunteer_id}")
def get_profile(volunteer_id: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().get_profile(_owner(identity), volunteer_id)
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/assignments")
def create_assignment(request: AssignmentRequest, identity: Identity) -> dict[str, Any]:
    try:
        return _service().create_assignment(_owner(identity), request.model_dump())
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/assignments/{assignment_id}/state")
def assignment_state(assignment_id: str, request: AssignmentStateRequest, identity: Identity) -> dict[str, Any]:
    try:
        owner = _owner(identity)
        return _service().update_assignment_state(owner, assignment_id, request.state, actor=owner, rationale=request.rationale)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/hours")
def log_hours(request: HourLogRequest, identity: Identity) -> dict[str, Any]:
    try:
        return _service().log_hours(_owner(identity), request.model_dump())
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/hours/{log_id}/verify")
def verify_hours(log_id: str, request: HourVerificationRequest, identity: Identity) -> dict[str, Any]:
    try:
        return _service().verify_hours(
            _owner(identity),
            log_id,
            supervisor_id=request.supervisor_id,
            decision=request.decision,
            rationale=request.rationale,
        )
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/training")
def record_training(request: TrainingRequest, identity: Identity) -> dict[str, Any]:
    try:
        return _service().record_training(_owner(identity), request.model_dump())
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/certificates")
def issue_certificate(request: CertificateRequest, identity: Identity) -> dict[str, Any]:
    try:
        return _service().issue_certificate(_owner(identity), request.model_dump())
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/recognition")
def record_recognition(request: RecognitionRequest, identity: Identity) -> dict[str, Any]:
    try:
        return _service().record_recognition(_owner(identity), request.model_dump())
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/conflicts")
def disclose_conflict(request: ConflictRequest, identity: Identity) -> dict[str, Any]:
    try:
        return _service().disclose_conflict(_owner(identity), request.model_dump())
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/profiles/{volunteer_id}/export")
def export_volunteer(
    volunteer_id: str,
    identity: Identity,
    include_private_contact: Annotated[bool, Query()] = False,
) -> dict[str, Any]:
    try:
        return _service().export(_owner(identity), volunteer_id, include_private_contact=include_private_contact)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/readiness")
def volunteer_readiness(identity: Identity) -> dict[str, Any]:
    try:
        return _service().readiness(_owner(identity))
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc
