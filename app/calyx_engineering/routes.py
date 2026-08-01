from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.calyx_orchestrator.models import CalyxFinding, CalyxJob
from app.database import get_db
from app.security import verify_owner_or_api_key

from .github import FileChange, GitHubEngineeringClient
from .inspection import RepositoryInspector
from .repair import BoundedCIInspector
from .service import CalyxEngineeringService, EngineeringProposal

router = APIRouter(prefix="/engineering", tags=["calyx-engineering"])
DbDependency = Annotated[Session, Depends(get_db)]
AuthDependency = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]


class ChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=240)
    content: str = Field(max_length=250000)
    message: str = Field(min_length=1, max_length=240)


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approved: bool = False
    base: str = Field(default="main", pattern=r"^[A-Za-z0-9._/-]+$")
    changes: list[ChangeRequest] = Field(min_length=1, max_length=20)


class InspectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paths: list[str] = Field(min_length=1, max_length=20)
    ref: str = Field(default="main", pattern=r"^[A-Za-z0-9._/-]+$")


def _owner(auth: dict[str, Any]) -> str:
    owner = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not owner:
        raise HTTPException(401, detail={"code": "AUTHENTICATED_OWNER_REQUIRED"})
    return owner


def _proposal(db: Session, finding_id: str, owner: str) -> EngineeringProposal:
    finding = db.get(CalyxFinding, finding_id)
    if finding is None:
        raise HTTPException(404, detail={"code": "FINDING_NOT_FOUND"})
    job = db.get(CalyxJob, finding.job_id)
    if job is None or job.owner != owner:
        raise HTTPException(404, detail={"code": "FINDING_NOT_FOUND"})
    return CalyxEngineeringService().propose(
        finding_id=finding.finding_id,
        title=f"Calyx follow-up: {finding.title}",
        summary=finding.summary,
        recommendation=finding.recommendation,
    )


@router.get("/status")
def status(auth: AuthDependency) -> dict:
    _owner(auth)
    return {
        "enabled": CalyxEngineeringService.enabled(),
        "mode": "preproduction",
        "capabilities": [
            "inspect_repository",
            "inspect_ci_failures",
            "create_issue",
            "create_branch",
            "commit_changes",
            "open_draft_pr",
        ],
        "autonomous_merge": False,
        "deployment": False,
    }


@router.post("/inspect")
def inspect_repository(payload: InspectRequest, auth: AuthDependency) -> dict:
    _owner(auth)
    try:
        service = CalyxEngineeringService()
        client = GitHubEngineeringClient(service.repository)
        return RepositoryInspector(client).inspect(payload.paths, ref=payload.ref).to_dict()
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(422, detail={"code": str(exc)}) from exc


@router.get("/pull-requests/{pull_request_number}/failures")
def inspect_failures(
    pull_request_number: int,
    auth: AuthDependency,
    limit: int = 5,
) -> dict:
    _owner(auth)
    try:
        service = CalyxEngineeringService()
        client = GitHubEngineeringClient(service.repository)
        failures = BoundedCIInspector(client).failed_checks(pull_request_number, limit=limit)
        return {
            "pull_request_number": pull_request_number,
            "failures": [item.to_dict() for item in failures],
            "repair_attempt_limit": 3,
            "autonomous_merge": False,
        }
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(422, detail={"code": str(exc)}) from exc


@router.post("/findings/{finding_id}/proposal")
def proposal(finding_id: str, auth: AuthDependency, db: DbDependency) -> dict:
    return _proposal(db, finding_id, _owner(auth)).to_dict()


@router.post("/findings/{finding_id}/execute", status_code=201)
def execute(
    finding_id: str,
    payload: ExecuteRequest,
    auth: AuthDependency,
    db: DbDependency,
) -> dict:
    try:
        return CalyxEngineeringService().execute(
            proposal=_proposal(db, finding_id, _owner(auth)),
            changes=[FileChange(item.path, item.content, item.message) for item in payload.changes],
            approved=payload.approved,
            base=payload.base,
        )
    except PermissionError as exc:
        raise HTTPException(403, detail={"code": str(exc)}) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(422, detail={"code": str(exc)}) from exc
