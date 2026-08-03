from __future__ import annotations

from fastapi import APIRouter

from app.parallel_platform.contracts import IdentificationRequest, MatrixRequest
from app.parallel_platform.service import capabilities, homepage_document, rank_candidates, score_matrix

router = APIRouter(prefix="/api/platform", tags=["parallel-platform"])


@router.get("/capabilities")
def get_capabilities():
    return capabilities()


@router.get("/homepage")
def get_homepage_document():
    return homepage_document()


@router.post("/matrix/pairwise")
def post_pairwise_matrix(request: MatrixRequest):
    return score_matrix(request)


@router.post("/identification/rank")
def post_identification_rank(request: IdentificationRequest):
    return rank_candidates(request)
