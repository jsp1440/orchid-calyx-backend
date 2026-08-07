from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key

from .api_models import (
    IntegratedIdentificationRequest,
    LiteratureValidationRequest,
    MatrixRankingRequest,
    VisionAnalysisRequest,
)
from .operator import MultimodalError, operator_service
from .promotion import build_candidate_knowledge_promotion_plan
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


def _validation_error(error: ValueError) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={"code": "MULTIMODAL_VALIDATION_ERROR", "message": str(error)},
    )


@router.get("/status")
def status(auth: AuthDependency) -> dict:
    del auth
    return capability_status()


@router.get("/configuration")
def configuration(auth: AuthDependency) -> dict:
    del auth
    return operator_service.configuration()


@router.post("/literature/validate")
def validate_literature(request: LiteratureValidationRequest, auth: AuthDependency) -> dict:
    del auth
    try:
        return asdict(operator_service.validate_literature_claim(request.contract()))
    except MultimodalError as error:
        raise _http_error(error) from error
    except ValueError as error:
        raise _validation_error(error) from error


@router.post("/matrix/rank")
def rank_matrix(request: MatrixRankingRequest, auth: AuthDependency) -> dict:
    del auth
    try:
        definitions, observations, profiles = request.contracts()
        return asdict(
            operator_service.rank_matrix(
                definitions=definitions,
                observations=observations,
                profiles=profiles,
            )
        )
    except MultimodalError as error:
        raise _http_error(error) from error
    except ValueError as error:
        raise _validation_error(error) from error


@router.post("/vision/convert")
def convert_vision(request: VisionAnalysisRequest, auth: AuthDependency) -> dict:
    del auth
    try:
        return asdict(operator_service.convert_vision(request.contract()))
    except MultimodalError as error:
        raise _http_error(error) from error
    except (PermissionError, ValueError) as error:
        raise _validation_error(error) from error


@router.post("/identify")
def identify(request: IntegratedIdentificationRequest, auth: AuthDependency) -> dict:
    del auth
    try:
        analysis, definitions, profiles, minimum_margin = request.contracts()
        return asdict(
            operator_service.integrated_identification(
                analysis=analysis,
                definitions=definitions,
                profiles=profiles,
                minimum_margin=minimum_margin,
            )
        )
    except MultimodalError as error:
        raise _http_error(error) from error
    except (PermissionError, ValueError) as error:
        raise _validation_error(error) from error


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


@router.get("/operations/{operation_id}/candidate-knowledge-plan")
def candidate_knowledge_plan(operation_id: str, auth: AuthDependency) -> dict:
    del auth
    try:
        record = operator_service.get_operation(operation_id)
        return asdict(build_candidate_knowledge_promotion_plan(record))
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
