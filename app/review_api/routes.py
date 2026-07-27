from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.mission_control_access import AccessPrincipal, CapabilityService
from app.review_tasks.models import ReviewDecisionInput, ReviewDecisionType
from app.review_tasks.service import GovernedReviewTaskService, ReviewTaskError

from .dependencies import authenticated_principal, review_service_dependency

router = APIRouter(prefix="/api/mission-control/review", tags=["MISSION-CONTROL-ROLE-001F"])

_capability_service = CapabilityService()


class ReviewDecisionRequest(BaseModel):
    decision: ReviewDecisionType
    comment: str | None = None
    modified_value: dict[str, Any] | None = None
    provenance: dict[str, Any] = Field(default_factory=dict)


def _translate_review_error(exc: ReviewTaskError) -> HTTPException:
    status = 404 if exc.code == "TASK_NOT_FOUND" else 409 if exc.code in {
        "TASK_NOT_AVAILABLE",
        "AUTHORITATIVE_DECISION_LOCKED",
    } else 403 if exc.code in {"CAPABILITY_REQUIRED", "PRINCIPAL_REVIEWER_MISMATCH"} else 400
    return HTTPException(status_code=status, detail={"code": exc.code, "details": exc.details})


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
