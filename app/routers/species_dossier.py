"""Protected Mission Control routes for canonical CALYX species dossiers."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.species_dossier import SpeciesDossierService

router = APIRouter(prefix="/brain/mission-control/species-dossiers", tags=["mission-control-species-dossiers"])
_service_instance = SpeciesDossierService()
Identity = Annotated[dict[str, object], Depends(verify_owner_or_api_key)]


def _service() -> SpeciesDossierService:
    return _service_instance


def _owner(identity: dict[str, object]) -> str:
    actor = str(identity.get("actor") or "").strip()
    if not actor:
        raise HTTPException(status_code=403, detail={"code": "DOSSIER_OWNER_SCOPE_REQUIRED"})
    return actor


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail={"code": "DOSSIER_NOT_FOUND", "detail": str(exc)})
    return HTTPException(status_code=422, detail={"code": str(exc).split(":", 1)[0], "detail": str(exc)})


class DossierRequest(BaseModel):
    stable_taxon_id: str
    identity: dict[str, Any]
    domains: dict[str, Any] = Field(default_factory=dict)
    partner_links: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    provenance: list[dict[str, Any] | str] = Field(min_length=1, max_length=1000)


@router.put("/{stable_taxon_id}")
def assemble_dossier(stable_taxon_id: str, request: DossierRequest, identity: Identity) -> dict[str, Any]:
    try:
        payload = request.model_dump()
        payload["stable_taxon_id"] = stable_taxon_id
        return _service().assemble(_owner(identity), payload)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/{stable_taxon_id}")
def get_dossier(stable_taxon_id: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().get(_owner(identity), stable_taxon_id)
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/{stable_taxon_id}/readiness")
def dossier_readiness(stable_taxon_id: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().readiness(_owner(identity), stable_taxon_id)
    except (FileNotFoundError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("")
def resolve_dossier(
    identity: Identity,
    q: Annotated[str, Query(min_length=1, max_length=300)],
) -> dict[str, Any]:
    try:
        return _service().resolve(_owner(identity), q)
    except ValueError as exc:
        raise _translate(exc) from exc
