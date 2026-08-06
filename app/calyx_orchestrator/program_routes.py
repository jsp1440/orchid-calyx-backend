from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import verify_owner_or_api_key

from .program_repository import PersistentProgramRepository, ProgramJobSpec

router = APIRouter(prefix="/orchestrator/programs", tags=["calyx-engineering-programs"])

DbDependency = Annotated[Session, Depends(get_db)]
AuthDependency = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]


class ProgramJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_key: str = Field(min_length=1, max_length=120)
    role_key: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=240)
    repository: str = Field(min_length=1, max_length=240)
    branch: str | None = Field(default=None, max_length=240)
    mutating: bool = False


class DependencyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    upstream: str = Field(min_length=1, max_length=120)
    downstream: str = Field(min_length=1, max_length=120)


class ProgramRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=1, max_length=240)
    objective: str = Field(min_length=1, max_length=12000)
    jobs: list[ProgramJobRequest] = Field(min_length=1, max_length=50)
    dependencies: list[DependencyRequest] = Field(default_factory=list, max_length=200)
    max_active_jobs: int = Field(default=6, ge=1, le=6)
    start_immediately: bool = True


class CancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=1, max_length=2000)


class OutcomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    blocker: str | None = Field(default=None, max_length=4000)
    human_action: str | None = Field(default=None, max_length=4000)


def _owner(auth: dict[str, Any]) -> str:
    owner = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not owner:
        raise HTTPException(401, detail={"code": "AUTHENTICATED_OWNER_REQUIRED"})
    return owner


def _translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(404, detail={"code": str(exc)})
    return HTTPException(409, detail={"code": str(exc)})


@router.post("", status_code=201)
def create_program(payload: ProgramRequest, auth: AuthDependency, db: DbDependency) -> dict:
    repository = PersistentProgramRepository(db)
    try:
        program = repository.create_program(
            owner=_owner(auth),
            title=payload.title,
            objective=payload.objective,
            jobs=[ProgramJobSpec(**item.model_dump()) for item in payload.jobs],
            dependencies=[(item.upstream, item.downstream) for item in payload.dependencies],
            max_active_jobs=payload.max_active_jobs,
        )
        if payload.start_immediately:
            repository.start(owner=_owner(auth), program_id=program.program_id)
        return repository.snapshot(owner=_owner(auth), program_id=program.program_id)
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@router.get("/{program_id}")
def get_program(program_id: str, auth: AuthDependency, db: DbDependency) -> dict:
    try:
        return PersistentProgramRepository(db).snapshot(owner=_owner(auth), program_id=program_id)
    except LookupError as exc:
        raise _translate_error(exc) from exc


@router.post("/{program_id}/start")
def start_program(program_id: str, auth: AuthDependency, db: DbDependency) -> dict:
    repository = PersistentProgramRepository(db)
    try:
        repository.start(owner=_owner(auth), program_id=program_id)
        return repository.snapshot(owner=_owner(auth), program_id=program_id)
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@router.post("/{program_id}/pause")
def pause_program(program_id: str, auth: AuthDependency, db: DbDependency) -> dict:
    repository = PersistentProgramRepository(db)
    try:
        repository.pause(owner=_owner(auth), program_id=program_id)
        return repository.snapshot(owner=_owner(auth), program_id=program_id)
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@router.post("/{program_id}/resume")
def resume_program(program_id: str, auth: AuthDependency, db: DbDependency) -> dict:
    repository = PersistentProgramRepository(db)
    try:
        repository.start(owner=_owner(auth), program_id=program_id)
        return repository.snapshot(owner=_owner(auth), program_id=program_id)
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@router.post("/{program_id}/cancel")
def cancel_program(
    program_id: str,
    payload: CancelRequest,
    auth: AuthDependency,
    db: DbDependency,
) -> dict:
    repository = PersistentProgramRepository(db)
    try:
        repository.cancel(owner=_owner(auth), program_id=program_id, reason=payload.reason)
        return repository.snapshot(owner=_owner(auth), program_id=program_id)
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc


@router.post("/{program_id}/jobs/{job_key}/outcome")
def record_job_outcome(
    program_id: str,
    job_key: str,
    payload: OutcomeRequest,
    auth: AuthDependency,
    db: DbDependency,
) -> dict:
    repository = PersistentProgramRepository(db)
    try:
        repository.record_outcome(
            owner=_owner(auth),
            program_id=program_id,
            job_key=job_key,
            outcome=payload.outcome,
            evidence=payload.evidence,
            blocker=payload.blocker,
            human_action=payload.human_action,
        )
        return repository.snapshot(owner=_owner(auth), program_id=program_id)
    except (LookupError, ValueError) as exc:
        raise _translate_error(exc) from exc
