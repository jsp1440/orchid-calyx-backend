"""Protected Mission Control routes for ecological interaction evidence."""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.ecological_interactions import EcologicalInteractionService

router = APIRouter(prefix="/brain/mission-control/interactions", tags=["mission-control-interactions"])
_service_instance = EcologicalInteractionService()
Identity = Annotated[dict[str, object], Depends(verify_owner_or_api_key)]


def _service() -> EcologicalInteractionService:
    return _service_instance


def _owner(identity: dict[str, object]) -> str:
    actor = str(identity.get("actor") or "").strip()
    if not actor:
        raise HTTPException(status_code=403, detail={"code": "INTERACTION_OWNER_SCOPE_REQUIRED"})
    return actor


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail={"code": "INTERACTION_NOT_FOUND", "detail": str(exc)})
    return HTTPException(status_code=422, detail={"code": str(exc).split(":", 1)[0], "detail": str(exc)})


class EvidenceRequest(BaseModel):
    evidence_id: str
    source_id: str
    source_url: str
    exact_text: str
    locator: str
    retrieved_at: str


class InteractionRequest(BaseModel):
    interaction_id: str
    subject_taxon: dict[str, str]
    interaction_type: str
    organism_identity: str
    organism_taxon_candidates: list[dict[str, str]] = Field(default_factory=list, max_length=20)
    locality: str | None = None
    observed_at: str | None = None
    evidence: EvidenceRequest
    confidence: float = Field(ge=0, le=1)
    contradiction: bool = False
    pollination_documented: bool = False


@router.put("/{interaction_id}")
def record_interaction(interaction_id: str, request: InteractionRequest, identity: Identity) -> dict[str, Any]:
    try:
        payload = request.model_dump()
        payload["interaction_id"] = interaction_id
        return _service().record(_owner(identity), payload)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/{interaction_id}")
def get_interaction(interaction_id: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().get(_owner(identity), interaction_id)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("")
def review_queue(identity: Identity) -> dict[str, Any]:
    return _service().review_queue(_owner(identity))


@router.post("/stage")
def stage(identity: Identity, limit: int = Query(default=100, ge=1, le=5000)) -> dict[str, Any]:
    try:
        return _service().stage(_owner(identity), limit=limit)
    except (TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/status/readiness")
def readiness(identity: Identity) -> dict[str, Any]:
    return _service().readiness(_owner(identity))
