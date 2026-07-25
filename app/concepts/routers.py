from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query

from app.routers.health import add_mission_control_cors_headers
from app.security import verify_owner_or_api_key

from .dependencies import get_concept_service
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


@router.get("/search")
def search_concepts(
    q: str = Query(..., min_length=1, max_length=300),
    language: str | None = Query(default=None, min_length=2, max_length=35),
    limit: int = Query(default=25, ge=1, le=100),
    service: Annotated[ConceptRegistryService, Depends(get_concept_service)] = None,
) -> dict[str, Any]:
    try:
        return service.search(q, language=language, limit=limit)
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
        return service.list_labels(id_or_uri, language=language)
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
        return service.list_definitions(id_or_uri, language=language)
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
