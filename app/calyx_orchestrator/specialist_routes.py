from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import verify_owner_or_api_key

from .schema import ensure_orchestrator_schema
from .specialist_service import MissionSpec, SpecialistMissionRepository

router = APIRouter(prefix="/specialist-missions", tags=["calyx-specialist-council"])

DbDependency = Annotated[Session, Depends(get_db)]
AuthDependency = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]


def _owner(auth: dict[str, Any]) -> str:
    owner = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not owner:
        raise HTTPException(401, detail={"code": "AUTHENTICATED_OWNER_REQUIRED"})
    return owner


def _error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(404, detail={"code": str(exc)})
    if isinstance(exc, PermissionError):
        return HTTPException(403, detail={"code": str(exc)})
    return HTTPException(409, detail={"code": str(exc)})


class MissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=8, max_length=160)
    kind: str = Field(min_length=1, max_length=80)
    question: str = Field(min_length=1, max_length=12000)
    scientific: bool = True
    publication_candidate: bool = False
    max_specialists: int = Field(default=4, ge=1, le=7)
    token_budget: int = Field(default=100000, ge=0, le=10000000)
    cost_budget_microusd: int = Field(default=0, ge=0, le=100000000000)
    constraints: dict[str, Any] = Field(default_factory=dict)


class ArtifactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    artifact_key: str = Field(min_length=1, max_length=160)
    specialist_id: str = Field(min_length=1, max_length=80)
    artifact_type: str = Field(min_length=1, max_length=80)
    content: dict[str, Any]
    provenance: dict[str, Any]
    tokens_used: int = Field(default=0, ge=0, le=10000000)
    cost_microusd: int = Field(default=0, ge=0, le=100000000000)


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    review_key: str = Field(min_length=1, max_length=160)
    reviewer_id: str = "scientific-reviewer"
    passed: bool
    findings: dict[str, Any] = Field(default_factory=dict)
    provenance: dict[str, Any]


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_key: str = Field(min_length=1, max_length=160)
    decision: str
    note: str | None = Field(default=None, max_length=4000)


@router.post("", status_code=201)
def create_mission(payload: MissionRequest, auth: AuthDependency, db: DbDependency) -> dict:
    ensure_orchestrator_schema(db)
    owner = _owner(auth)
    try:
        mission = SpecialistMissionRepository(db).create(
            owner=owner,
            spec=MissionSpec(
                idempotency_key=payload.idempotency_key,
                kind=payload.kind,
                question=payload.question,
                scientific=payload.scientific,
                publication_candidate=payload.publication_candidate,
                max_specialists=payload.max_specialists,
                token_budget=payload.token_budget,
                cost_budget_microusd=payload.cost_budget_microusd,
                constraints=payload.constraints,
            ),
        )
        return SpecialistMissionRepository(db).snapshot(owner=owner, mission_id=mission.mission_id)
    except (LookupError, PermissionError, ValueError) as exc:
        raise _error(exc) from exc


@router.get("/{mission_id}")
def get_mission(mission_id: str, auth: AuthDependency, db: DbDependency) -> dict:
    ensure_orchestrator_schema(db)
    try:
        return SpecialistMissionRepository(db).snapshot(owner=_owner(auth), mission_id=mission_id)
    except (LookupError, PermissionError, ValueError) as exc:
        raise _error(exc) from exc


@router.post("/{mission_id}/artifacts", status_code=201)
def add_artifact(mission_id: str, payload: ArtifactRequest, auth: AuthDependency, db: DbDependency) -> dict:
    ensure_orchestrator_schema(db)
    owner = _owner(auth)
    repository = SpecialistMissionRepository(db)
    try:
        repository.add_artifact(owner=owner, mission_id=mission_id, **payload.model_dump())
        return repository.snapshot(owner=owner, mission_id=mission_id)
    except (LookupError, PermissionError, ValueError) as exc:
        raise _error(exc) from exc


@router.post("/{mission_id}/reviews", status_code=201)
def add_review(mission_id: str, payload: ReviewRequest, auth: AuthDependency, db: DbDependency) -> dict:
    ensure_orchestrator_schema(db)
    owner = _owner(auth)
    repository = SpecialistMissionRepository(db)
    try:
        repository.record_review(owner=owner, mission_id=mission_id, **payload.model_dump())
        return repository.snapshot(owner=owner, mission_id=mission_id)
    except (LookupError, PermissionError, ValueError) as exc:
        raise _error(exc) from exc


@router.post("/{mission_id}/approvals", status_code=201)
def add_approval(mission_id: str, payload: ApprovalRequest, auth: AuthDependency, db: DbDependency) -> dict:
    ensure_orchestrator_schema(db)
    owner = _owner(auth)
    repository = SpecialistMissionRepository(db)
    try:
        repository.record_approval(
            owner=owner,
            mission_id=mission_id,
            actor=owner,
            approval_key=payload.approval_key,
            decision=payload.decision,
            note=payload.note,
        )
        return repository.snapshot(owner=owner, mission_id=mission_id)
    except (LookupError, PermissionError, ValueError) as exc:
        raise _error(exc) from exc
