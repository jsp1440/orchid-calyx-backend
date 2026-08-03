from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.parallel_platform.brain_candidate_handoff import (
    BrainCandidateHandoffRequest,
    handoff_brain_candidate,
)
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
from app.security import verify_owner_or_api_key

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


@router.post(
    "/brain/candidate-knowledge",
    status_code=201,
    dependencies=[Depends(verify_owner_or_api_key)],
)
def post_brain_candidate_knowledge(request: BrainCandidateHandoffRequest):
    try:
        return handoff_brain_candidate(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc
