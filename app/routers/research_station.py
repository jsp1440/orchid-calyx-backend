"""Protected private Research Station routes for CALYX issue #453."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.research_station import ResearchStationService

router = APIRouter(prefix="/brain/mission-control/research", tags=["mission-control-research"])
_service_instance = ResearchStationService()
OwnerIdentity = Annotated[dict[str, object], Depends(verify_owner_or_api_key)]


def _service() -> ResearchStationService:
    return _service_instance


def _owner(identity: dict[str, object]) -> str:
    actor = str(identity.get("actor") or "").strip()
    if not actor:
        raise HTTPException(status_code=403, detail="Research Station owner scope unavailable")
    return actor


def _translate(call):
    try:
        return call()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ValueError, LookupError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class ProjectRequest(BaseModel):
    project_id: str | None = None
    title: str
    objective: str
    state: str = "planned"
    created_at: str


class RecordRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


class NotebookRequest(BaseModel):
    body: str
    authored_at: str
    author: str


class TaskRequest(BaseModel):
    task_id: str | None = None
    title: str
    state: str = "todo"
    milestone: str | None = None
    due_at: str | None = None
    blockers: list[str] = Field(default_factory=list)
    updated_at: str


@router.post("/projects")
def create_project(request: ProjectRequest, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _service().create_project(_owner(identity), request.model_dump()))


@router.post("/projects/{project_id}/questions")
def add_question(project_id: str, request: RecordRequest, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _service().add_question(_owner(identity), project_id, request.payload))


@router.post("/projects/{project_id}/protocols")
def add_protocol(project_id: str, request: RecordRequest, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _service().add_protocol(_owner(identity), project_id, request.payload))


@router.post("/projects/{project_id}/notebook/{entry_id}/revisions")
def revise_notebook(
    project_id: str,
    entry_id: str,
    request: NotebookRequest,
    identity: OwnerIdentity,
) -> dict:
    return _translate(
        lambda: _service().revise_notebook(
            _owner(identity), project_id, entry_id, request.model_dump()
        )
    )


@router.post("/projects/{project_id}/samples")
def add_sample(project_id: str, request: RecordRequest, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _service().add_sample(_owner(identity), project_id, request.payload))


@router.post("/projects/{project_id}/datasets")
def add_dataset(project_id: str, request: RecordRequest, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _service().add_dataset(_owner(identity), project_id, request.payload))


@router.post("/projects/{project_id}/attachments")
def attach(project_id: str, request: RecordRequest, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _service().attach(_owner(identity), project_id, request.payload))


@router.post("/projects/{project_id}/claims")
def add_claim(project_id: str, request: RecordRequest, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _service().add_claim(_owner(identity), project_id, request.payload))


@router.post("/projects/{project_id}/evidence")
def add_evidence(project_id: str, request: RecordRequest, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _service().add_evidence(_owner(identity), project_id, request.payload))


@router.post("/projects/{project_id}/decisions")
def add_decision(project_id: str, request: RecordRequest, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _service().add_decision(_owner(identity), project_id, request.payload))


@router.put("/projects/{project_id}/tasks")
def upsert_task(project_id: str, request: TaskRequest, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _service().upsert_task(_owner(identity), project_id, request.model_dump()))


@router.get("/projects/{project_id}/manifest")
def manifest(project_id: str, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _service().manifest(_owner(identity), project_id))


@router.get("/projects/{project_id}/readiness")
def readiness(project_id: str, identity: OwnerIdentity) -> dict:
    return _translate(lambda: _service().readiness(_owner(identity), project_id))
