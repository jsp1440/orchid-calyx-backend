"""Protected Mission Control routes for orchid-fungus evidence."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.mycorrhizal_evidence import MycorrhizalEvidenceService

router = APIRouter(prefix="/brain/mission-control/mycorrhiza", tags=["mission-control-mycorrhiza"])
_service_instance = MycorrhizalEvidenceService()
Identity = Annotated[dict[str, object], Depends(verify_owner_or_api_key)]


def _service() -> MycorrhizalEvidenceService:
    return _service_instance


def _owner(identity: dict[str, object]) -> str:
    actor = str(identity.get("actor") or "").strip()
    if not actor:
        raise HTTPException(status_code=403, detail={"code": "MYCORRHIZA_OWNER_SCOPE_REQUIRED"})
    return actor


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail={"code": "MYCORRHIZA_RECORD_NOT_FOUND", "detail": str(exc)})
    return HTTPException(status_code=422, detail={"code": str(exc).split(":", 1)[0], "detail": str(exc)})


class EvidenceReference(BaseModel):
    literature_run_id: str
    span_id: int = Field(ge=1)


class AssociationRequest(BaseModel):
    association_id: str
    association_type: str
    association_documented: bool = False
    orchid_taxon: dict[str, str]
    fungal_identity: str
    fungal_candidates: list[dict[str, str]] = Field(default_factory=list, max_length=20)
    tissue: str
    life_stage: str
    locality: str = ""
    method: str
    evidence: EvidenceReference
    confidence: float = Field(ge=0, le=1)
    contradiction: bool = False


@router.put("/{association_id}")
def record_association(association_id: str, request: AssociationRequest, identity: Identity) -> dict[str, Any]:
    try:
        payload = request.model_dump()
        payload["association_id"] = association_id
        return _service().record(_owner(identity), payload)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/{association_id}")
def get_association(association_id: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().get(_owner(identity), association_id)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("")
def unresolved_queue(identity: Identity) -> dict[str, Any]:
    return _service().unresolved_queue(_owner(identity))


@router.get("/{association_id}/provenance")
def provenance(association_id: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().provenance(_owner(identity), association_id)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/stage")
def stage(identity: Identity, limit: int = Query(default=100, ge=1, le=5000)) -> dict[str, Any]:
    try:
        return _service().stage(_owner(identity), limit=limit)
    except (TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/status/readiness")
def readiness(identity: Identity) -> dict[str, Any]:
    return _service().readiness(_owner(identity))
