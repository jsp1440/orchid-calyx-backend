"""Protected Mission Control routes for governed orchid show operations."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.orchid_show_operations import OrchidShowOperations

router = APIRouter(
    prefix="/brain/mission-control/orchid-shows",
    tags=["mission-control-orchid-shows"],
)
_service_instance = OrchidShowOperations()
Identity = Annotated[dict[str, object], Depends(verify_owner_or_api_key)]


def _service() -> OrchidShowOperations:
    return _service_instance


def _owner(identity: dict[str, object]) -> str:
    actor = str(identity.get("actor") or identity.get("subject") or "").strip()
    if not actor:
        raise HTTPException(status_code=403, detail={"code": "SHOW_OWNER_SCOPE_REQUIRED"})
    return actor


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(
            status_code=404,
            detail={"code": "SHOW_RECORD_NOT_FOUND", "detail": str(exc)},
        )
    return HTTPException(
        status_code=422,
        detail={"code": str(exc).split(":", 1)[0], "detail": str(exc)},
    )


class ShowRequest(BaseModel):
    show_id: str
    name: str
    organization_name: str | None = None
    venue: str | None = None
    starts_at: str | None = None
    ends_at: str | None = None


class ExhibitorRequest(BaseModel):
    exhibitor_id: str
    display_name: str
    organization: str | None = None
    contact: dict[str, Any] = Field(default_factory=dict)


class EntryClassRequest(BaseModel):
    class_id: str
    name: str
    description: str | None = None
    eligibility_rules: list[str | dict[str, Any]] = Field(default_factory=list)


class EntryRequest(BaseModel):
    entry_id: str
    exhibitor_id: str
    class_id: str
    entered_label_text: str
    canonical_taxon_id: str | None = None
    accepted_name_display: str | None = None
    cultivar_or_clone: str | None = None
    media_artifact_ids: list[str] = Field(default_factory=list)
    media_review_state: str = "not_supplied"


class EntryStateRequest(BaseModel):
    state: str
    rationale: str = Field(min_length=1, max_length=4000)


class JudgingTeamRequest(BaseModel):
    team_id: str
    judge_ids: list[str] = Field(min_length=1)
    class_ids: list[str] = Field(default_factory=list)
    conflicts: list[str | dict[str, Any]] = Field(default_factory=list)


class JudgingDecisionRequest(BaseModel):
    decision_id: str
    entry_id: str
    team_id: str
    decision_type: str
    award_name: str | None = None
    placement: str | None = None
    deciding_judge_ids: list[str] = Field(min_length=1)
    rationale: str = Field(min_length=1, max_length=4000)
    conflicts: list[str | dict[str, Any]] = Field(default_factory=list)
    conflict_resolution: str | None = None
    human_decision: bool


class ScheduleItemRequest(BaseModel):
    item_id: str
    title: str
    starts_at: str | None = None
    ends_at: str | None = None
    location: str | None = None
    notes: str | None = None


class VendorRequest(BaseModel):
    vendor_id: str
    name: str
    contact: dict[str, Any] = Field(default_factory=dict)
    booth: str | None = None


class ShowVolunteerRequest(BaseModel):
    assignment_id: str
    volunteer_id: str
    role: str
    starts_at: str | None = None
    ends_at: str | None = None
    location: str | None = None


@router.post("/shows")
def create_show(request: ShowRequest, identity: Identity) -> dict[str, Any]:
    try:
        owner = _owner(identity)
        return _service().create_show(owner, request.model_dump(), actor=owner)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/shows/{show_id}")
def get_show(show_id: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().get_show(_owner(identity), show_id)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/shows/{show_id}/exhibitors")
def add_exhibitor(
    show_id: str,
    request: ExhibitorRequest,
    identity: Identity,
) -> dict[str, Any]:
    try:
        owner = _owner(identity)
        return _service().add_exhibitor(
            owner,
            show_id,
            request.model_dump(),
            actor=owner,
        )
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/shows/{show_id}/classes")
def add_entry_class(
    show_id: str,
    request: EntryClassRequest,
    identity: Identity,
) -> dict[str, Any]:
    try:
        owner = _owner(identity)
        return _service().add_entry_class(
            owner,
            show_id,
            request.model_dump(),
            actor=owner,
        )
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/shows/{show_id}/entries")
def add_entry(show_id: str, request: EntryRequest, identity: Identity) -> dict[str, Any]:
    try:
        owner = _owner(identity)
        return _service().add_entry(owner, show_id, request.model_dump(), actor=owner)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/shows/{show_id}/entries/{entry_id}/state")
def update_entry_state(
    show_id: str,
    entry_id: str,
    request: EntryStateRequest,
    identity: Identity,
) -> dict[str, Any]:
    try:
        owner = _owner(identity)
        return _service().update_entry_state(
            owner,
            show_id,
            entry_id,
            request.state,
            actor=owner,
            rationale=request.rationale,
        )
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/shows/{show_id}/judging-teams")
def add_judging_team(
    show_id: str,
    request: JudgingTeamRequest,
    identity: Identity,
) -> dict[str, Any]:
    try:
        owner = _owner(identity)
        return _service().add_judging_team(
            owner,
            show_id,
            request.model_dump(),
            actor=owner,
        )
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/shows/{show_id}/judging-decisions")
def record_judging_decision(
    show_id: str,
    request: JudgingDecisionRequest,
    identity: Identity,
) -> dict[str, Any]:
    try:
        owner = _owner(identity)
        return _service().record_judging_decision(
            owner,
            show_id,
            request.model_dump(),
            actor=owner,
        )
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/shows/{show_id}/schedule")
def add_schedule_item(
    show_id: str,
    request: ScheduleItemRequest,
    identity: Identity,
) -> dict[str, Any]:
    try:
        owner = _owner(identity)
        return _service().add_schedule_item(
            owner,
            show_id,
            request.model_dump(),
            actor=owner,
        )
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/shows/{show_id}/vendors")
def add_vendor(
    show_id: str,
    request: VendorRequest,
    identity: Identity,
) -> dict[str, Any]:
    try:
        owner = _owner(identity)
        return _service().add_vendor(owner, show_id, request.model_dump(), actor=owner)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/shows/{show_id}/volunteers")
def assign_volunteer(
    show_id: str,
    request: ShowVolunteerRequest,
    identity: Identity,
) -> dict[str, Any]:
    try:
        owner = _owner(identity)
        return _service().assign_volunteer(
            owner,
            show_id,
            request.model_dump(),
            actor=owner,
        )
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/shows/{show_id}/entries/{entry_id}/label")
def printable_entry_label(
    show_id: str,
    entry_id: str,
    identity: Identity,
) -> dict[str, Any]:
    try:
        return _service().printable_entry_label(_owner(identity), show_id, entry_id)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/shows/{show_id}/results")
def results_export(show_id: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().results_export(_owner(identity), show_id)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/shows/{show_id}/audit")
def audit_history(show_id: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().audit_history(_owner(identity), show_id)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/shows/{show_id}/readiness")
def readiness(show_id: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().readiness(_owner(identity), show_id)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc
