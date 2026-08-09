from typing import Annotated, Any
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.routers.health import add_mission_control_cors_headers
from app.security import verify_owner_or_api_key

from .dependencies import get_concept_service
from .glossary import (
    FigureRequestType,
    GlossaryResolutionState,
    PostgresGlossaryRepository,
    ScientificLanguageService,
)
from .services import ConceptRegistryService

router = APIRouter(
    prefix="/api/concepts",
    tags=["core-concept-registry"],
    dependencies=[
        Depends(verify_owner_or_api_key),
        Depends(add_mission_control_cors_headers),
    ],
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


def get_scientific_language_service(
    service: Annotated[ConceptRegistryService, Depends(get_concept_service)],
) -> ScientificLanguageService:
    return ScientificLanguageService(
        concept_service=service,
        repository=PostgresGlossaryRepository(),
    )


class GlossaryCandidateIn(BaseModel):
    term: str = Field(min_length=1, max_length=500)
    source_kind: str = Field(min_length=1, max_length=80)
    source_hash: str = Field(min_length=8, max_length=256)
    source_locator: dict[str, Any]
    language: str = Field(default="und", min_length=2, max_length=35)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)
    proposed_definition: str | None = Field(default=None, max_length=10000)
    provenance: dict[str, Any] = Field(default_factory=dict)


class FigureRequestIn(BaseModel):
    request_type: FigureRequestType
    title: str = Field(min_length=1, max_length=500)
    generation_prompt: str = Field(min_length=1, max_length=20000)
    caption: str | None = Field(default=None, max_length=5000)
    priority: int = Field(default=50, ge=0, le=100)
    provenance: dict[str, Any] = Field(default_factory=dict)


@router.post("/glossary/candidates")
def intake_glossary_candidate(
    payload: GlossaryCandidateIn,
    service: Annotated[ScientificLanguageService, Depends(get_scientific_language_service)],
) -> dict[str, Any]:
    try:
        return service.intake_candidate(**payload.model_dump())
    except Exception as exc:
        _translate_error(exc)
        raise


@router.get("/glossary/candidates")
def list_glossary_candidates(
    resolution_state: GlossaryResolutionState | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    service: Annotated[ScientificLanguageService, Depends(get_scientific_language_service)] = None,
) -> list[dict[str, Any]]:
    try:
        return service.list_candidates(
            resolution_state=resolution_state.value if resolution_state else None,
            limit=limit,
        )
    except Exception as exc:
        _translate_error(exc)
        raise


@router.get("/glossary/figures")
def list_glossary_figure_queue(
    concept_id: UUID | None = None,
    status: str | None = Query(default=None, max_length=80),
    limit: int = Query(default=100, ge=1, le=500),
    service: Annotated[ScientificLanguageService, Depends(get_scientific_language_service)] = None,
) -> list[dict[str, Any]]:
    try:
        return service.list_figure_requests(
            concept_id=concept_id, status=status, limit=limit
        )
    except Exception as exc:
        _translate_error(exc)
        raise


@router.get("/glossary/by-id/{concept_id}/entry")
def get_glossary_entry(
    concept_id: UUID,
    service: Annotated[ScientificLanguageService, Depends(get_scientific_language_service)],
) -> dict[str, Any]:
    try:
        return service.glossary_entry(concept_id)
    except Exception as exc:
        _translate_error(exc)
        raise


@router.post("/glossary/{concept_id}/figure-requests")
def create_glossary_figure_request(
    concept_id: UUID,
    payload: FigureRequestIn,
    service: Annotated[ScientificLanguageService, Depends(get_scientific_language_service)],
) -> dict[str, Any]:
    try:
        return service.request_figure(concept_id=concept_id, **payload.model_dump())
    except Exception as exc:
        _translate_error(exc)
        raise


@router.get("/search")
def search_concepts(
    q: str = Query(..., min_length=1, max_length=300),
    language: str | None = Query(default=None, min_length=2, max_length=35),
    limit: int = Query(default=25, ge=1, le=100),
    service: Annotated[ConceptRegistryService, Depends(get_concept_service)] = None,
) -> dict[str, Any]:
    try:
        return service.search_concepts(q, language=language, limit=limit)
    except Exception as exc:  # translated into stable API errors below
        _translate_error(exc)
        raise


@router.get("/{id_or_uri:path}/labels")
def list_concept_labels(
    id_or_uri: str,
    language: str | None = Query(default=None, min_length=2, max_length=35),
    service: Annotated[ConceptRegistryService, Depends(get_concept_service)] = None,
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
    service: Annotated[ConceptRegistryService, Depends(get_concept_service)] = None,
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
    service: Annotated[ConceptRegistryService, Depends(get_concept_service)],
) -> dict[str, Any]:
    try:
        return service.get_concept(id_or_uri)
    except Exception as exc:
        _translate_error(exc)
        raise
