from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import verify_owner_or_api_key

from .program_cycle import run_deterministic_program_cycle

router = APIRouter(prefix="/programs/workers", tags=["calyx-program-autonomy"])

DbDependency = Annotated[Session, Depends(get_db)]
AuthDependency = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]


class AutonomousCycleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker_id: str = Field(default="calyx-program-autonomy", min_length=1, max_length=240)
    max_jobs: int = Field(default=10, ge=1, le=50)
    lease_seconds: int = Field(default=300, ge=60, le=3600)
    timeout_seconds: int = Field(default=300, ge=1, le=3600)


def _owner(auth: dict[str, Any]) -> str:
    owner = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not owner:
        raise HTTPException(401, detail={"code": "AUTHENTICATED_OWNER_REQUIRED"})
    return owner


@router.post("/run-cycle")
def run_autonomous_cycle(
    payload: AutonomousCycleRequest,
    auth: AuthDependency,
    db: DbDependency,
) -> dict[str, Any]:
    try:
        result = run_deterministic_program_cycle(
            db,
            owner=_owner(auth),
            worker_id=payload.worker_id,
            max_jobs=payload.max_jobs,
            lease_seconds=payload.lease_seconds,
            timeout_seconds=payload.timeout_seconds,
        )
    except ValueError as exc:
        raise HTTPException(422, detail={"code": str(exc)}) from exc
    return result.as_dict()
