from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.calyx_orchestrator.models import CalyxFinding, CalyxJob
from app.database import get_db
from app.security import verify_owner_or_api_key

from .anthropic_provider import (
    AnthropicPatchProviderError,
    AnthropicPatchRequest,
    generate_file_changes,
)
from .completion_loop import GovernedAutonomousCompletionLoop
from .completion_scheduler import EngineeringCompletionScheduler
from .github import FileChange, GitHubEngineeringClient
from .inspection import RepositoryInspector
from .provider import EngineeringProviderError, StructuredPatchProvider
from .repair import BoundedCIInspector
from .repair_loop import BoundedRepairLoop
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


class RepairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paths: list[str] = Field(min_length=1, max_length=20)
    objective: str = Field(min_length=1, max_length=12000)
    attempt: int = Field(ge=1, le=3)
    approved: bool = False


class CompletionCycleRequest(BaseModel):
    """Read-only completion inspection; mutating cycles require a persisted job."""

    model_config = ConfigDict(extra="forbid")
    paths: list[str] = Field(min_length=1, max_length=20)
    objective: str = Field(min_length=1, max_length=12000)
    required_checks: list[str] = Field(min_length=1, max_length=50)


class CompletionJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    paths: list[str] = Field(min_length=1, max_length=20)
    objective: str = Field(min_length=1, max_length=12000)
    required_checks: list[str] = Field(min_length=1, max_length=50)
    repairs_authorized: bool = False
    priority: int = Field(default=20, ge=1, le=1000)


class ProviderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str = Field(min_length=1, max_length=120)
    response_format: str = Field(pattern=r"^calyx_file_changes_v1$")
    objective: str = Field(min_length=1, max_length=12000)
    attempt: int = Field(ge=1, le=3)
    constraints: dict[str, Any]
    repository_files: dict[str, str] = Field(min_length=1, max_length=10)
    failure_logs: list[str] = Field(min_length=1, max_length=5)


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


def _completion_scheduler(db: Session) -> EngineeringCompletionScheduler:
    service = CalyxEngineeringService()
    client = GitHubEngineeringClient(service.repository)
    return EngineeringCompletionScheduler(db, client)


@router.get("/status")
def status(auth: AuthDependency) -> dict:
    _owner(auth)
    return {
        "enabled": CalyxEngineeringService.enabled(),
        "mode": "preproduction",
        "capabilities": [
            "inspect_repository",
            "inspect_ci_failures",
            "generate_structured_patches",
            "apply_bounded_ci_repairs",
            "inspect_governed_completion_cycle",
            "persist_governed_completion_job",
            "run_persisted_completion_worker_cycle",
            "create_issue",
            "create_branch",
            "commit_changes",
            "open_draft_pr",
        ],
        "repair_attempt_limit": 3,
        "direct_completion_mutation": False,
        "autonomous_merge": False,
        "deployment": False,
    }


@router.post("/provider/anthropic")
def anthropic_provider(payload: ProviderRequest, auth: AuthDependency) -> dict:
    _owner(auth)
    if payload.constraints.get("workflow_files_forbidden") is not True:
        raise HTTPException(422, detail={"code": "PROVIDER_WORKFLOW_GUARD_REQUIRED"})
    if payload.constraints.get("complete_file_replacements") is not True:
        raise HTTPException(422, detail={"code": "PROVIDER_COMPLETE_FILES_REQUIRED"})
    if payload.constraints.get("merge_forbidden") is not True:
        raise HTTPException(422, detail={"code": "PROVIDER_MERGE_GUARD_REQUIRED"})
    if payload.constraints.get("deployment_forbidden") is not True:
        raise HTTPException(422, detail={"code": "PROVIDER_DEPLOYMENT_GUARD_REQUIRED"})
    try:
        return generate_file_changes(
            AnthropicPatchRequest(
                objective=payload.objective,
                attempt=payload.attempt,
                constraints=payload.constraints,
                repository_files=payload.repository_files,
                failure_logs=payload.failure_logs,
            )
        )
    except AnthropicPatchProviderError as exc:
        raise HTTPException(422, detail={"code": str(exc)}) from exc


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


@router.post("/pull-requests/{pull_request_number}/repair")
def repair_pull_request(
    pull_request_number: int,
    payload: RepairRequest,
    auth: AuthDependency,
) -> dict:
    _owner(auth)
    if not payload.approved:
        raise HTTPException(403, detail={"code": "ENGINEERING_REPAIR_APPROVAL_REQUIRED"})
    if not CalyxEngineeringService.enabled():
        raise HTTPException(422, detail={"code": "CALYX_ENGINEERING_DISABLED"})
    try:
        service = CalyxEngineeringService()
        client = GitHubEngineeringClient(service.repository)
        result = BoundedRepairLoop(client, StructuredPatchProvider()).repair_once(
            pull_request_number=pull_request_number,
            paths=payload.paths,
            objective=payload.objective,
            attempt=payload.attempt,
        )
        return result.to_dict()
    except PermissionError as exc:
        raise HTTPException(403, detail={"code": str(exc)}) from exc
    except (EngineeringProviderError, RuntimeError, ValueError) as exc:
        raise HTTPException(422, detail={"code": str(exc)}) from exc


@router.post("/pull-requests/{pull_request_number}/completion-cycle")
def inspect_completion_cycle(
    pull_request_number: int,
    payload: CompletionCycleRequest,
    auth: AuthDependency,
) -> dict:
    """Inspect one governed CI state without permitting a code-writing repair."""
    _owner(auth)
    if not CalyxEngineeringService.enabled():
        raise HTTPException(422, detail={"code": "CALYX_ENGINEERING_DISABLED"})
    try:
        service = CalyxEngineeringService()
        client = GitHubEngineeringClient(service.repository)
        result = GovernedAutonomousCompletionLoop(client).advance(
            pull_request_number=pull_request_number,
            repair_paths=payload.paths,
            objective=payload.objective,
            attempt=1,
            repairs_authorized=False,
            required_checks=payload.required_checks,
        ).to_dict()
        result["mutating"] = False
        result["repair_requires_persisted_job"] = True
        return result
    except PermissionError as exc:
        raise HTTPException(403, detail={"code": str(exc)}) from exc
    except (EngineeringProviderError, RuntimeError, ValueError) as exc:
        raise HTTPException(422, detail={"code": str(exc)}) from exc


@router.post("/pull-requests/{pull_request_number}/completion-jobs", status_code=201)
def create_completion_job(
    pull_request_number: int,
    payload: CompletionJobRequest,
    auth: AuthDependency,
    db: DbDependency,
) -> dict:
    owner = _owner(auth)
    if not CalyxEngineeringService.enabled():
        raise HTTPException(422, detail={"code": "CALYX_ENGINEERING_DISABLED"})
    try:
        job = _completion_scheduler(db).enqueue(
            owner=owner,
            pull_request_number=pull_request_number,
            repair_paths=payload.paths,
            objective=payload.objective,
            repairs_authorized=payload.repairs_authorized,
            required_checks=payload.required_checks,
            priority=payload.priority,
        )
        return {
            "job_id": job.job_id,
            "pull_request_number": pull_request_number,
            "status": job.status,
            "attempt_count": job.attempt_count,
            "max_attempts": job.max_attempts,
            "autonomous_merge": False,
            "deployment": False,
        }
    except PermissionError as exc:
        raise HTTPException(403, detail={"code": str(exc)}) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(422, detail={"code": str(exc)}) from exc


@router.post("/completion-jobs/run-once")
def run_completion_job_once(auth: AuthDependency, db: DbDependency) -> dict:
    owner = _owner(auth)
    if not CalyxEngineeringService.enabled():
        raise HTTPException(422, detail={"code": "CALYX_ENGINEERING_DISABLED"})
    try:
        return _completion_scheduler(db).run_once(worker_id=f"engineering-api:{owner}")
    except PermissionError as exc:
        raise HTTPException(403, detail={"code": str(exc)}) from exc
    except (EngineeringProviderError, RuntimeError, ValueError) as exc:
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
            changes=[
                FileChange(item.path, item.content, item.message) for item in payload.changes
            ],
            approved=payload.approved,
            base=payload.base,
        )
    except PermissionError as exc:
        raise HTTPException(403, detail={"code": str(exc)}) from exc
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(422, detail={"code": str(exc)}) from exc
