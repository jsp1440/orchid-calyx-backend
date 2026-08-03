from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.parallel_platform.contracts import IdentificationRequest, MatrixRequest
from app.parallel_platform.integration_contracts import (
    HomepageSelectionRequest,
    IdentificationSessionRequest,
    MatrixNeighborhoodRequest,
)
from app.parallel_platform.integration_service import (
    homepage_selection,
    identification_session,
    matrix_neighborhood,
)
from app.parallel_platform.service import (
    capabilities,
    homepage_document,
    rank_candidates,
    score_matrix,
)

router = APIRouter(prefix="/api/platform", tags=["parallel-platform"])


@router.get("/capabilities")
def get_capabilities():
    return capabilities()


@router.get("/homepage")
def get_homepage_document():
    return homepage_document()


@router.post("/homepage/select")
def post_homepage_selection(request: HomepageSelectionRequest):
    try:
        return homepage_selection(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/matrix/pairwise")
def post_pairwise_matrix(request: MatrixRequest):
    return score_matrix(request)


@router.post("/matrix/neighborhood")
def post_matrix_neighborhood(request: MatrixNeighborhoodRequest):
    try:
        return matrix_neighborhood(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/identification/rank")
def post_identification_rank(request: IdentificationRequest):
    return rank_candidates(request)


@router.post("/identification/session")
def post_identification_session(request: IdentificationSessionRequest):
    try:
        return identification_session(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
