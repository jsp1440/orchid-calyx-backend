from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import verify_owner_or_api_key

from .product_execution import complete_product_job, create_product_program
from .product_program import product_mission_control_snapshot

router = APIRouter(prefix="/product", tags=["calyx-product-agents"])

DbDependency = Annotated[Session, Depends(get_db)]
AuthDependency = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]


class ProductCompleteRequest(BaseModel):
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


def _translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(404, detail={"code": str(exc)})
    if isinstance(exc, (PermissionError, ValueError, TypeError)):
        return HTTPException(409, detail={"code": str(exc)})
    return HTTPException(500, detail={"code": "PRODUCT_EXECUTION_FAILED"})


@router.get("/status")
def product_status(auth: AuthDependency) -> dict:
    _owner(auth)
    return product_mission_control_snapshot()


@router.post("/programs/phase-3-demo", status_code=201)
def create_phase_3_program(auth: AuthDependency, db: DbDependency) -> dict:
    try:
        return create_product_program(db, owner=_owner(auth), start_immediately=True)
    except (LookupError, PermissionError, ValueError, TypeError) as exc:
        raise _translate_error(exc) from exc


@router.post("/workers/jobs/{program_job_id}/complete")
def complete_phase_3_job(
    program_job_id: str,
    payload: ProductCompleteRequest,
    auth: AuthDependency,
    db: DbDependency,
) -> dict:
    _owner(auth)
    try:
        job = complete_product_job(
            db,
            program_job_id=program_job_id,
            worker_id=payload.worker_id,
            lease_token=payload.lease_token,
            outcome=payload.outcome,
            evidence=payload.evidence,
            blocker=payload.blocker,
            human_action=payload.human_action,
        )
        return {"completed": True, "program_job_id": job.program_job_id, "outcome": job.outcome}
    except (LookupError, PermissionError, ValueError, TypeError) as exc:
        raise _translate_error(exc) from exc
