from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key

from .operator import operator_service
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


@router.get("/status")
def status(auth: AuthDependency) -> dict:
    del auth
    return capability_status()


@router.post("/batch/plan")
def batch_plan(request: BatchRequest, auth: AuthDependency) -> dict:
    del auth
    return operator_service.batch(
        tuple((item.operation_type, item.payload) for item in request.operations)
    )


@router.get("/review-queue")
def review_queue(auth: AuthDependency) -> dict:
    del auth
    records = operator_service.review_queue()
    return {
        "items": [
            {
                "operation_id": record.operation_id,
                "operation_type": record.operation_type,
                "state": record.state,
                "request_hash": record.request_hash,
            }
            for record in records
        ],
        "human_review_required": True,
    }


@router.get("/audit/export")
def audit_export(auth: AuthDependency) -> dict:
    del auth
    return operator_service.export_audit()


@router.get("/benchmark")
def benchmark(auth: AuthDependency) -> dict:
    del auth
    return operator_service.benchmark()
