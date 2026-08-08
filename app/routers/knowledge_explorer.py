"""Protected governed Knowledge Explorer routes for CALYX issue #444."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.knowledge_explorer import KnowledgeExplorerService

router = APIRouter(prefix="/brain/mission-control/knowledge-explorer", tags=["knowledge-explorer"])
_service_instance = KnowledgeExplorerService()
OwnerIdentity = Annotated[dict[str, object], Depends(verify_owner_or_api_key)]


def _service() -> KnowledgeExplorerService:
    return _service_instance


def _translate(call):
    try:
        return call()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class CandidateConceptRequest(BaseModel):
    concept_id: str
    preferred_term: str
    synonyms: list[str] = Field(default_factory=list, max_length=100)
    definitions: dict[str, str]
    evidence_spans: list[dict[str, Any]] = Field(min_length=1, max_length=100)
    images: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    figures: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    relationships: list[dict[str, Any]] = Field(default_factory=list, max_length=100)


@router.post("/candidates")
def register_candidate(request: CandidateConceptRequest, _identity: OwnerIdentity) -> dict:
    return _translate(lambda: _service().register_candidate(request.model_dump()))


@router.get("/resolve/{term}")
def resolve(term: str, _identity: OwnerIdentity) -> dict:
    return _translate(lambda: _service().resolve(term))


@router.get("/popover/{term}")
def popover(
    term: str,
    _identity: OwnerIdentity,
    level: str = Query(default="plain"),
) -> dict:
    return _translate(lambda: _service().popover(term, level=level))


@router.get("/concepts/{concept_id}")
def expanded(concept_id: str, _identity: OwnerIdentity) -> dict:
    return _translate(lambda: _service().expanded(concept_id))


@router.get("/readiness")
def readiness(_identity: OwnerIdentity) -> dict:
    return _service().readiness()
