from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import verify_owner_or_api_key

from .sandbox_supervisor_evidence import SupervisorCredentialVerifier
from .sandbox_supervisor_service import SandboxSupervisorService

router = APIRouter(prefix="/sandbox-validation", tags=["calyx-sandbox-validation"])

DbDependency = Annotated[Session, Depends(get_db)]
AuthDependency = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]


class ValidationTargetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=500)
    sha256: str = Field(min_length=64, max_length=64)


class CreateValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    program_job_id: str | None = Field(default=None, max_length=36)
    repository: str = Field(min_length=3, max_length=240)
    branch: str = Field(min_length=1, max_length=240)
    checkout_commit_sha: str = Field(min_length=40, max_length=40)
    preset: str = Field(min_length=1, max_length=20)
    targets: list[ValidationTargetRequest] = Field(min_length=1, max_length=24)
    timeout_seconds: int = Field(default=60, ge=1, le=120)


class SupervisorClaimRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker_id: str = Field(min_length=1, max_length=240)


class SupervisorCompleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker_id: str = Field(min_length=1, max_length=240)
    claim_token: str = Field(min_length=36, max_length=36)
    receipt: dict[str, Any]


def _owner(auth: dict[str, Any]) -> str:
    owner = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not owner:
        raise HTTPException(401, detail={"code": "AUTHENTICATED_OWNER_REQUIRED"})
    return owner


def _require_supervisor(token: str | None) -> None:
    if not token:
        raise HTTPException(401, detail={"code": "SANDBOX_SUPERVISOR_CREDENTIAL_REQUIRED"})
    try:
        SupervisorCredentialVerifier.from_environ().verify(token)
    except (PermissionError, RuntimeError) as exc:
        raise HTTPException(403, detail={"code": str(exc)}) from exc


@router.post("/requests", status_code=201)
def create_validation_request(
    payload: CreateValidationRequest,
    auth: AuthDependency,
    db: DbDependency,
) -> dict:
    try:
        record = SandboxSupervisorService(db).create_request(
            owner=_owner(auth),
            program_job_id=payload.program_job_id,
            repository=payload.repository,
            branch=payload.branch,
            checkout_commit_sha=payload.checkout_commit_sha,
            preset=payload.preset,
            targets=[item.model_dump() for item in payload.targets],
            timeout_seconds=payload.timeout_seconds,
        )
        return SandboxSupervisorService.public_snapshot(record)
    except (PermissionError, TypeError, ValueError) as exc:
        raise HTTPException(422, detail={"code": str(exc)}) from exc


@router.get("/requests/{request_id}")
def get_validation_request(request_id: str, auth: AuthDependency, db: DbDependency) -> dict:
    try:
        record = SandboxSupervisorService(db).get_owned(owner=_owner(auth), request_id=request_id)
        return SandboxSupervisorService.public_snapshot(record)
    except LookupError as exc:
        raise HTTPException(404, detail={"code": str(exc)}) from exc


@router.post("/supervisor/claim")
def claim_validation_request(
    payload: SupervisorClaimRequest,
    db: DbDependency,
    x_calyx_sandbox_supervisor_token: Annotated[str | None, Header()] = None,
) -> dict:
    _require_supervisor(x_calyx_sandbox_supervisor_token)
    record = SandboxSupervisorService(db).claim_next(worker_id=payload.worker_id)
    if record is None:
        return {"claimed": False, "request": None}
    return {"claimed": True, "request": SandboxSupervisorService.supervisor_claim_snapshot(record)}


@router.post("/supervisor/requests/{request_id}/complete")
def complete_validation_request(
    request_id: str,
    payload: SupervisorCompleteRequest,
    db: DbDependency,
    x_calyx_sandbox_supervisor_token: Annotated[str | None, Header()] = None,
) -> dict:
    _require_supervisor(x_calyx_sandbox_supervisor_token)
    try:
        record = SandboxSupervisorService(db).complete(
            request_id=request_id,
            worker_id=payload.worker_id,
            claim_token=payload.claim_token,
            receipt_payload=payload.receipt,
        )
        return {
            "completed": True,
            "request_id": record.request_id,
            "request_digest": record.request_digest,
            "receipt_digest": record.receipt_digest,
            "outcome": record.outcome,
            "status": record.status,
        }
    except LookupError as exc:
        raise HTTPException(404, detail={"code": str(exc)}) from exc
    except (PermissionError, TypeError, ValueError) as exc:
        raise HTTPException(409, detail={"code": str(exc)}) from exc
