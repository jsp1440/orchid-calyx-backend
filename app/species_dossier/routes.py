"""Journey 2 — canonical species dossier and federation resolve routes.

Serves the contract the public species page already consumes
(``/api/platform/species/{taxon_id}/dossier``, ``/atlas`` and
``/api/platform/federation/resolve-species``) from Calyx's own tables through
:class:`PostgresSpeciesRepository`. Read-only; nothing here activates
taxonomy or publishes scientific claims, and no locality is emitted.
"""

from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError

from .models import (
    FederationResolveRequest,
    FederationResolveResult,
    SpeciesAtlasEnvelope,
    SpeciesDossierEnvelope,
)
from .repository import PostgresSpeciesRepository
from .service import SpeciesDossierService

router = APIRouter(prefix="/api/platform", tags=["species-dossier"])

DATABASE_UNCONFIGURED = "Species dossier database is not configured."
SERVICE_UNAVAILABLE = "Species dossier service is unavailable."


def public_base_url() -> str:
    return os.getenv("PUBLIC_SITE_BASE_URL", "https://orchidcontinuum.org")


def get_service() -> SpeciesDossierService:
    if not os.getenv("DATABASE_URL", "").strip():
        raise HTTPException(status_code=503, detail=DATABASE_UNCONFIGURED)
    from app.routers.owner_operations import db_execute

    return SpeciesDossierService(
        PostgresSpeciesRepository(db_execute), public_base_url=public_base_url()
    )


Service = Annotated[SpeciesDossierService, Depends(get_service)]


def _guard(call: Any) -> Any:
    try:
        return call()
    except HTTPException:
        raise
    except (
        Exception
    ) as exc:  # database or driver failure: say unavailable, never fabricate
        raise HTTPException(status_code=503, detail=SERVICE_UNAVAILABLE) from exc


@router.get("/species/{taxon_id}/dossier", response_model=SpeciesDossierEnvelope)
def species_dossier(taxon_id: str, service: Service) -> SpeciesDossierEnvelope:
    dossier = _guard(lambda: service.dossier(taxon_id))
    if dossier is None:
        raise HTTPException(
            status_code=404,
            detail="No canonical taxon record exists for this identifier.",
        )
    return dossier


@router.get("/species/{taxon_id}/atlas", response_model=SpeciesAtlasEnvelope)
def species_atlas(taxon_id: str, service: Service) -> SpeciesAtlasEnvelope:
    atlas = _guard(lambda: service.atlas(taxon_id))
    if atlas is None:
        raise HTTPException(
            status_code=404,
            detail="No canonical taxon record exists for this identifier.",
        )
    return atlas


@router.get("/federation/resolve-species", response_model=FederationResolveResult)
def resolve_species(
    service: Service,
    name: Annotated[str | None, Query(max_length=300)] = None,
    taxon_id: Annotated[str | None, Query(max_length=200)] = None,
    source_url: Annotated[str | None, Query(max_length=2000)] = None,
    partner_slug: Annotated[str | None, Query(max_length=100)] = None,
    partner_species_slug: Annotated[str | None, Query(max_length=300)] = None,
) -> FederationResolveResult:
    try:
        request = FederationResolveRequest(
            name=name,
            taxon_id=taxon_id,
            source_url=source_url,  # type: ignore[arg-type]
            partner_slug=partner_slug,
            partner_species_slug=partner_species_slug,
        )
    except ValidationError as exc:
        detail = [
            {
                "loc": [str(part) for part in err.get("loc", ())],
                "msg": str(err.get("msg", "")),
                "type": str(err.get("type", "")),
            }
            for err in exc.errors(include_url=False)
        ]
        raise HTTPException(status_code=422, detail=detail) from exc
    return _guard(lambda: service.resolve(request))
