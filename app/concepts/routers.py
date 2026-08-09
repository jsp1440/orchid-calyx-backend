from typing import Annotated, Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.routers.health import add_mission_control_cors_headers
from app.security import verify_owner_or_api_key

from .dependencies import get_concept_service
from .glossary import (
    CandidateState,
    FigureRequestType,
    GlossaryCandidateInput,
    GlossaryService,
)
from .glossary_dependencies import get_glossary_service
from .services import ConceptRegistryService

router = APIRouter(
    prefix="/api/concepts",
    tags=["core-concept-registry"],
    dependencies=[
        Depends(verify_owner_or_api_key),
        Depends(add_mission_control_cors_headers),
    ],
)


class GlossaryCandidateRequest(BaseModel):
    term: str = Field(min_length=1, max_length=300)
    source_uri: str = Field(min_length=1, max_length=2000)
    source_revision_id: str = Field(min_length=1, max_length=300)
    source_checksum: str = Field(min_length=64, max_length=64)
    evidence_span_id: str = Field(min_length=1, max_length=300)
    language: str = Field(default="en", min_length=2, max_length=35)


class GlossaryReviewRequest(BaseModel):
    state: CandidateState
    rationale: str = Field(min_length=1, max_length=4000)
    concept_id: UUID | None = None


class FigureRequestBody(BaseModel):
    concept_id: UUID
    request_type: FigureRequestType
    audience: str = Field(min_length=1, max_length=300)
    purpose: str = Field(min_length=1, max_length=4000)
    source_candidate_id: str | None = Field(
        default=None,
        min_length=64,
        max_length=64,
    )


def _translate_error(exc: Exception) -> None:
    if isinstance(exc, LookupError):
        raise HTTPException(404, detail={"code": str(exc)}) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(422, detail={"code": str(exc)}) from exc
    if isinstance(exc, (RuntimeError, psycopg.Error)):
        raise HTTPException(
            503,
            detail={"code": "CONCEPT_DATABASE_UNAVAILABLE"},
        ) from exc
    raise exc


@router.get("/search")
def search_concepts(
    q: str = Query(..., min_length=1, max_length=300),
    language: str | None = Query(default=None, min_length=2, max_length=35),
    limit: int = Query(default=25, ge=1, le=100),
    service: Annotated[
        ConceptRegistryService,
        Depends(get_concept_service),
    ] = None,
) -> dict[str, Any]:
    try:
        return service.search_concepts(q, language=language, limit=limit)
    except Exception as exc:
        _translate_error(exc)
        raise


@router.post("/glossary/candidates")
def intake_glossary_candidate(
    body: GlossaryCandidateRequest,
    service: Annotated[
        GlossaryService,
        Depends(get_glossary_service),
    ] = None,
) -> dict[str, Any]:
    try:
        return service.intake(GlossaryCandidateInput(**body.model_dump()))
    except Exception as exc:
        _translate_error(exc)
        raise


@router.get("/glossary/candidates")
def list_glossary_candidates(
    state: CandidateState | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    service: Annotated[
        GlossaryService,
        Depends(get_glossary_service),
    ] = None,
) -> list[dict[str, Any]]:
    try:
        return service.list_candidates(state=state, limit=limit)
    except Exception as exc:
        _translate_error(exc)
        raise


@router.post("/glossary/candidates/{candidate_id}/review")
def review_glossary_candidate(
    candidate_id: str,
    body: GlossaryReviewRequest,
    auth: Annotated[dict[str, object], Depends(verify_owner_or_api_key)],
    service: Annotated[
        GlossaryService,
        Depends(get_glossary_service),
    ] = None,
) -> dict[str, Any]:
    try:
        actor = str(auth.get("actor") or "").strip()
        if not actor:
            raise ValueError("GLOSSARY_AUTHENTICATED_REVIEWER_REQUIRED")
        return service.review_candidate(
            candidate_id,
            state=body.state,
            actor=actor,
            rationale=body.rationale,
            concept_id=body.concept_id,
        )
    except Exception as exc:
        _translate_error(exc)
        raise


@router.get("/glossary/entries/{concept_id}")
def canonical_glossary_entry(
    concept_id: UUID,
    service: Annotated[
        GlossaryService,
        Depends(get_glossary_service),
    ] = None,
) -> dict[str, Any]:
    try:
        return service.glossary_entry(concept_id)
    except Exception as exc:
        _translate_error(exc)
        raise


@router.post("/glossary/figure-requests")
def create_glossary_figure_request(
    body: FigureRequestBody,
    service: Annotated[
        GlossaryService,
        Depends(get_glossary_service),
    ] = None,
) -> dict[str, Any]:
    try:
        return service.create_figure_request(**body.model_dump())
    except Exception as exc:
        _translate_error(exc)
        raise


@router.get("/glossary/figure-requests")
def list_glossary_figure_requests(
    concept_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    service: Annotated[
        GlossaryService,
        Depends(get_glossary_service),
    ] = None,
) -> list[dict[str, Any]]:
    try:
        return service.list_figure_requests(
            concept_id=concept_id,
            limit=limit,
        )
    except Exception as exc:
        _translate_error(exc)
        raise


@router.get("/{id_or_uri:path}/labels")
def list_concept_labels(
    id_or_uri: str,
    language: str | None = Query(default=None, min_length=2, max_length=35),
    service: Annotated[
        ConceptRegistryService,
        Depends(get_concept_service),
    ] = None,
) -> list[dict[str, Any]]:
    try:
        labels = service.list_labels(id_or_uri)
        if language is None:
            return labels
        return [row for row in labels if row.get("language") == language]
    except Exception as exc:
        _translate_error(exc)
        raise


@router.get("/{id_or_uri:path}/definitions")
def list_concept_definitions(
    id_or_uri: str,
    language: str | None = Query(default=None, min_length=2, max_length=35),
    service: Annotated[
        ConceptRegistryService,
        Depends(get_concept_service),
    ] = None,
) -> list[dict[str, Any]]:
    try:
        definitions = service.list_definitions(id_or_uri)
        if language is None:
            return definitions
        return [row for row in definitions if row.get("language") == language]
    except Exception as exc:
        _translate_error(exc)
        raise


@router.get("/{id_or_uri:path}")
def get_concept(
    id_or_uri: str,
    service: Annotated[
        ConceptRegistryService,
        Depends(get_concept_service),
    ],
) -> dict[str, Any]:
    try:
        return service.get_concept(id_or_uri)
    except Exception as exc:
        _translate_error(exc)
        raise
