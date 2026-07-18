from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.routers.health import add_mission_control_cors_headers
from app.security import verify_owner_or_api_key

from .dependencies import get_candidate_repository, get_extraction_service, get_review_repository
from .interfaces import SemanticCandidateRepository, SemanticReviewRepository
from .schemas import CandidatePatch, ExtractRequest, ReviewRequest
from .services import ExtractionOrchestrationService, candidate_changes

router = APIRouter(
    prefix="/semantic",
    tags=["semantic-extraction"],
    dependencies=[Depends(verify_owner_or_api_key), Depends(add_mission_control_cors_headers)],
)


@router.post("/extract", status_code=201)
def extract_semantics(payload: ExtractRequest, service: ExtractionOrchestrationService = Depends(get_extraction_service)) -> dict[str, Any]:
    try:
        return {**service.extract(payload.document_id, payload.actor), "canonical_graph_mutated": False}
    except LookupError as exc:
        raise HTTPException(404, detail={"code": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(422, detail={"code": str(exc)}) from exc


@router.get("/session/{session_id}")
def semantic_session(session_id: int, repository: SemanticCandidateRepository = Depends(get_candidate_repository)) -> dict[str, Any]:
    result = repository.get_session(session_id)
    if result is None:
        raise HTTPException(404, detail={"code": "SESSION_NOT_FOUND"})
    return {**result, "canonical_graph_mutated": False}


@router.get("/evidence/{evidence_id}")
def semantic_evidence(evidence_id: int, repository: SemanticCandidateRepository = Depends(get_candidate_repository)) -> dict[str, Any]:
    result = repository.get_evidence(evidence_id)
    if result is None:
        raise HTTPException(404, detail={"code": "EVIDENCE_NOT_FOUND"})
    return result


@router.get("/candidates/{session_id}")
def semantic_candidates(session_id: int, repository: SemanticCandidateRepository = Depends(get_candidate_repository)) -> dict[str, Any]:
    result = repository.get_candidates(session_id)
    if result is None:
        raise HTTPException(404, detail={"code": "SESSION_NOT_FOUND"})
    return result


@router.patch("/candidate/{candidate_id}")
def patch_semantic_candidate(candidate_id: int, payload: CandidatePatch, repository: SemanticCandidateRepository = Depends(get_candidate_repository)) -> dict[str, Any]:
    try:
        result = repository.update_candidate(candidate_id, candidate_changes(payload.model_dump()), payload.actor, payload.reason)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": str(exc)}) from exc
    if result is None:
        raise HTTPException(404, detail={"code": "CANDIDATE_NOT_FOUND"})
    return {**result, "canonical_graph_mutated": False}


@router.post("/review", status_code=201)
def review_semantic_candidates(payload: ReviewRequest, repository: SemanticReviewRepository = Depends(get_review_repository)) -> dict[str, Any]:
    try:
        return repository.record_review(payload.session_id, payload.candidate_ids, payload.decision, payload.actor, payload.notes)
    except LookupError as exc:
        raise HTTPException(404, detail={"code": str(exc)}) from exc
    except ValueError as exc:
        raise HTTPException(422, detail={"code": str(exc)}) from exc
