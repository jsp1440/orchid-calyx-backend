from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import verify_owner_or_api_key

from .scientific_execution import complete_scientific_job, create_scientific_program

router = APIRouter(prefix="/scientific", tags=["calyx-scientific-programs"])

DbDependency = Annotated[Session, Depends(get_db)]
AuthDependency = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]


class ScientificProgramRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start_immediately: bool = True


class ScientificCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker_id: str = Field(min_length=1, max_length=240)
    lease_token: str = Field(min_length=1, max_length=36)
    outcome: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    blocker: str | None = Field(default=None, max_length=4000)
    human_action: str | None = Field(default=None, max_length=4000)


def _owner(auth: dict[str, Any]) -> str:
    owner = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not owner:
        raise HTTPException(401, detail={"code": "AUTHENTICATED_OWNER_REQUIRED"})
    return owner


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(404, detail={"code": str(exc)})
    if isinstance(exc, PermissionError):
        return HTTPException(409, detail={"code": str(exc)})
    return HTTPException(422, detail={"code": str(exc)})


@router.post("/programs/phase-2-demo", status_code=201)
def create_phase_2_demo(
    payload: ScientificProgramRequest,
    auth: AuthDependency,
    db: DbDependency,
) -> dict[str, Any]:
    try:
        return create_scientific_program(
            db,
            owner=_owner(auth),
            start_immediately=payload.start_immediately,
        )
    except (LookupError, PermissionError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/workers/jobs/{program_job_id}/complete")
def complete_phase_2_job(
    program_job_id: str,
    payload: ScientificCompleteRequest,
    auth: AuthDependency,
    db: DbDependency,
) -> dict[str, Any]:
    _owner(auth)
    try:
        job = complete_scientific_job(
            db,
            program_job_id=program_job_id,
            worker_id=payload.worker_id,
            lease_token=payload.lease_token,
            outcome=payload.outcome,
            evidence=payload.evidence,
            blocker=payload.blocker,
            human_action=payload.human_action,
        )
        return {
            "completed": True,
            "program_job_id": job.program_job_id,
            "outcome": job.outcome,
            "scientific_evidence_persisted": True,
        }
    except (LookupError, PermissionError, ValueError) as exc:
        raise _translate(exc) from exc
