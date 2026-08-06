from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key

from .operator import MultimodalError, operator_service
from .status import capability_status

router = APIRouter(
    prefix="/api/mission-control/multimodal-intelligence",
    tags=["multimodal-intelligence"],
)

AuthDependency = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]


class BatchItem(BaseModel):
    operation_type: str
    payload: dict[str, Any] = Field(default_factory=dict)


class BatchRequest(BaseModel):
    operations: list[BatchItem] = Field(default_factory=list, max_length=100)


class ReviewDecisionRequest(BaseModel):
    decision: str
    rationale: str = Field(min_length=1, max_length=4000)
    reviewer: str = Field(min_length=1, max_length=200)


def _http_error(error: MultimodalError) -> HTTPException:
    status_code = 404 if error.code == "OPERATION_NOT_FOUND" else 422
    return HTTPException(status_code=status_code, detail={"code": error.code, "message": str(error)})


@router.get("/status")
def status(auth: AuthDependency) -> dict:
    del auth
    return capability_status()


@router.get("/configuration")
def configuration(auth: AuthDependency) -> dict:
    del auth
    return operator_service.configuration()


@router.post("/batch/plan")
def batch_plan(request: BatchRequest, auth: AuthDependency) -> dict:
    del auth
    return operator_service.batch(
        tuple((item.operation_type, item.payload) for item in request.operations)
    )


@router.get("/review-queue")
def review_queue(
    auth: AuthDependency,
    operation_type: str | None = None,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> dict:
    del auth
    try:
        page = operator_service.review_queue(
            operation_type=operation_type,
            offset=offset,
            limit=limit,
        )
    except MultimodalError as error:
        raise _http_error(error) from error
    return {
        "items": [asdict(record) for record in page["items"]],
        "total": page["total"],
        "offset": page["offset"],
        "limit": page["limit"],
        "human_review_required": True,
    }


@router.get("/operations/{operation_id}")
def operation_detail(operation_id: str, auth: AuthDependency) -> dict:
    del auth
    try:
        return asdict(operator_service.get_operation(operation_id))
    except MultimodalError as error:
        raise _http_error(error) from error


@router.post("/operations/{operation_id}/review")
def review_operation(
    operation_id: str,
    request: ReviewDecisionRequest,
    auth: AuthDependency,
) -> dict:
    del auth
    try:
        return asdict(
            operator_service.decide_review(
                operation_id,
                decision=request.decision,
                rationale=request.rationale,
                reviewer=request.reviewer,
            )
        )
    except MultimodalError as error:
        raise _http_error(error) from error


@router.get("/operations/{operation_id}/provenance")
def operation_provenance(operation_id: str, auth: AuthDependency) -> dict:
    del auth
    try:
        return operator_service.provenance_bundle(operation_id)
    except MultimodalError as error:
        raise _http_error(error) from error


@router.get("/audit/export")
def audit_export(auth: AuthDependency) -> dict:
    del auth
    return operator_service.export_audit()


@router.get("/benchmark")
def benchmark(auth: AuthDependency) -> dict:
    del auth
    return operator_service.benchmark()
