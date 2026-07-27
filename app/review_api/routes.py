from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.mission_control_access import AccessPrincipal, CapabilityService
from app.review_tasks.models import ReviewDecisionInput, ReviewDecisionType
from app.review_tasks.operations import ReviewQueueOperations
from app.review_tasks.service import GovernedReviewTaskService, ReviewTaskError
from app.review_tasks.workforce import WorkforceImportError, WorkforceResultReconciler, frontend_contract

from .dependencies import authenticated_principal, review_service_dependency

router = APIRouter(prefix="/api/mission-control/review", tags=["MISSION-CONTROL-ROLE-001I"])

_capability_service = CapabilityService()


class ReviewDecisionRequest(BaseModel):
    decision: ReviewDecisionType
    comment: str | None = None
    modified_value: dict[str, Any] | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class ExpireReservationsRequest(BaseModel):
    dry_run: bool = False


class WorkforceResultItem(BaseModel):
    task_id: str
    external_result_id: str | None = None
    reviewer_id: str | None = None
    decision: ReviewDecisionType
    comment: str | None = None
    modified_value: dict[str, Any] | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


class WorkforceImportRequest(BaseModel):
    source: str
    batch_id: str
    dry_run: bool = False
    results: list[WorkforceResultItem]


def _translate_review_error(exc: ReviewTaskError) -> HTTPException:
    status = 404 if exc.code == "TASK_NOT_FOUND" else 409 if exc.code in {
        "TASK_NOT_AVAILABLE",
        "AUTHORITATIVE_DECISION_LOCKED",
    } else 403 if exc.code in {"CAPABILITY_REQUIRED", "PRINCIPAL_REVIEWER_MISMATCH"} else 400
    return HTTPException(status_code=status, detail={"code": exc.code, "details": exc.details})


def _require_capability(principal: AccessPrincipal, capability: str) -> None:
    decision = _capability_service.evaluate(principal, capability)
    if not decision.allowed:
        raise HTTPException(
            status_code=403,
            detail={"code": decision.reason_code, "details": _capability_service.audit_payload(decision)},
        )


@router.get("/queue")
def review_queue(
    limit: int = Query(default=50, ge=1, le=200),
    principal: AccessPrincipal = Depends(authenticated_principal),
    service: GovernedReviewTaskService = Depends(review_service_dependency),
) -> dict[str, Any]:
    tasks = service.queue_for_principal(principal)
    return {
        "principal_id": principal.principal_id,
        "count": min(len(tasks), limit),
        "tasks": tasks[:limit],
    }


@router.get("/queue/metrics")
def review_queue_metrics(
    principal: AccessPrincipal = Depends(authenticated_principal),
    service: GovernedReviewTaskService = Depends(review_service_dependency),
) -> dict[str, Any]:
    _require_capability(principal, "mission_control.view.operations")
    return ReviewQueueOperations(service).metrics()


@router.post("/reservations/expire")
def expire_review_reservations(
    request: ExpireReservationsRequest,
    principal: AccessPrincipal = Depends(authenticated_principal),
    service: GovernedReviewTaskService = Depends(review_service_dependency),
) -> dict[str, Any]:
    _require_capability(principal, "review.assignments.manage")
    operations = ReviewQueueOperations(service)
    expired = [] if request.dry_run else operations.expire_reservations()
    return {"dry_run": request.dry_run, "expired_count": len(expired), "tasks": expired}


@router.get("/workforce/export")
def export_review_workforce_queue(
    principal: AccessPrincipal = Depends(authenticated_principal),
    service: GovernedReviewTaskService = Depends(review_service_dependency),
) -> dict[str, Any]:
    payload = ReviewQueueOperations(service).export_for_principal(principal)
    if not payload["allowed"]:
        raise HTTPException(status_code=403, detail=payload["authorization"])
    return payload


@router.post("/workforce/import")
def import_review_workforce_results(
    request: WorkforceImportRequest,
    principal: AccessPrincipal = Depends(authenticated_principal),
    service: GovernedReviewTaskService = Depends(review_service_dependency),
) -> dict[str, Any]:
    try:
        return WorkforceResultReconciler(service).import_results(
            principal,
            source=request.source,
            batch_id=request.batch_id,
            results=[item.model_dump() for item in request.results],
            dry_run=request.dry_run,
        )
    except WorkforceImportError as exc:
        status = 403 if exc.code == "CAPABILITY_REQUIRED" else 400
        raise HTTPException(status_code=status, detail={"code": exc.code, "details": exc.details}) from exc


@router.get("/frontend-contract")
def review_frontend_contract(
    principal: AccessPrincipal = Depends(authenticated_principal),
) -> dict[str, Any]:
    return frontend_contract(principal)


@router.get("/tasks/{task_id}")
def review_task_detail(
    task_id: str,
    principal: AccessPrincipal = Depends(authenticated_principal),
    service: GovernedReviewTaskService = Depends(review_service_dependency),
) -> dict[str, Any]:
    try:
        return service._authorized_task_for_principal(task_id, principal)
    except ReviewTaskError as exc:
        raise _translate_review_error(exc) from exc


@router.post("/tasks/{task_id}/reserve")
def reserve_review_task(
    task_id: str,
    principal: AccessPrincipal = Depends(authenticated_principal),
    service: GovernedReviewTaskService = Depends(review_service_dependency),
) -> dict[str, Any]:
    try:
        return service.reserve_for_principal(task_id, principal)
    except ReviewTaskError as exc:
        raise _translate_review_error(exc) from exc


@router.post("/tasks/{task_id}/decisions")
def decide_review_task(
    task_id: str,
    request: ReviewDecisionRequest,
    principal: AccessPrincipal = Depends(authenticated_principal),
    service: GovernedReviewTaskService = Depends(review_service_dependency),
) -> dict[str, Any]:
    try:
        decision = ReviewDecisionInput(
            decision=request.decision,
            reviewer_id=principal.principal_id,
            reviewer_capabilities=(),
            comment=request.comment,
            modified_value=request.modified_value,
            provenance=request.provenance,
        )
        return service.decide_for_principal(task_id, principal, decision)
    except ReviewTaskError as exc:
        raise _translate_review_error(exc) from exc


@router.get("/capabilities")
def review_capabilities(
    principal: AccessPrincipal = Depends(authenticated_principal),
) -> dict[str, Any]:
    return {
        "principal_id": principal.principal_id,
        "authenticated": principal.authenticated,
        "roles": [role.value for role in principal.roles],
        "qualifications": list(principal.qualifications),
        "specialties": list(principal.specialties),
        "effective_capabilities": list(_capability_service.effective_capabilities(principal)),
    }
