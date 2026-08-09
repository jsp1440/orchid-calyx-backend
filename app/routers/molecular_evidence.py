from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.molecular_evidence import MolecularEvidenceService

router = APIRouter(
    prefix="/brain/mission-control/molecular",
    tags=["mission-control-molecular"],
)
Identity = Annotated[dict[str, object], Depends(verify_owner_or_api_key)]
_service_instance = MolecularEvidenceService()


def _service() -> MolecularEvidenceService:
    return _service_instance


def _owner(identity: dict[str, object]) -> str:
    actor = str(identity.get("actor") or identity.get("subject") or "").strip()
    if not actor:
        raise HTTPException(status_code=403, detail={"code": "MOLECULAR_OWNER_SCOPE_REQUIRED"})
    return actor


def _translate(exc: Exception) -> HTTPException:
    if isinstance(exc, FileNotFoundError):
        return HTTPException(status_code=404, detail={"code": "MOLECULAR_RECORD_NOT_FOUND"})
    return HTTPException(status_code=422, detail={"code": str(exc).split(":", 1)[0], "detail": str(exc)})


class SequenceEvidenceRequest(BaseModel):
    evidence_id: str
    accession: str
    marker: str
    source_database: str
    voucher: dict[str, Any] = Field(default_factory=dict)
    specimen_provenance: dict[str, Any]
    submitted_name: str | None = None
    canonical_taxon_id: str | None = None
    accepted_name: str | None = None
    evidence_span: dict[str, Any]
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    conflicts: list[str | dict[str, Any]] = Field(default_factory=list)


class AnalysisArtifactRequest(BaseModel):
    artifact_id: str
    analysis_type: str
    content: str
    media_type: str = "application/json"
    source_uri: str | None = None
    evidence_uris: list[str] = Field(default_factory=list)


class PhylogeneticClaimRequest(BaseModel):
    claim_id: str
    claim_type: str
    statement: str
    evidence_span: dict[str, Any] | None = None
    analysis_artifact_ids: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    conflicts: list[str | dict[str, Any]] = Field(default_factory=list)


class ReviewRequest(BaseModel):
    state: str
    rationale: str = Field(min_length=1, max_length=4000)


@router.post("/evidence")
def register_sequence_evidence(request: SequenceEvidenceRequest, identity: Identity) -> dict[str, Any]:
    try:
        owner = _owner(identity)
        return _service().register_sequence_evidence(owner, request.model_dump(), actor=owner)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/evidence/{evidence_id}")
def get_sequence_evidence(evidence_id: str, identity: Identity) -> dict[str, Any]:
    try:
        return _service().get_evidence(_owner(identity), evidence_id)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/evidence/{evidence_id}/analysis-artifacts")
def register_analysis_artifact(evidence_id: str, request: AnalysisArtifactRequest, identity: Identity) -> dict[str, Any]:
    try:
        return _service().register_analysis_artifact(_owner(identity), evidence_id, request.model_dump())
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/evidence/{evidence_id}/claims")
def record_phylogenetic_claim(evidence_id: str, request: PhylogeneticClaimRequest, identity: Identity) -> dict[str, Any]:
    try:
        owner = _owner(identity)
        payload = request.model_dump(exclude_none=True)
        return _service().record_phylogenetic_claim(owner, evidence_id, payload, actor=owner)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/evidence/{evidence_id}/review")
def review_evidence(evidence_id: str, request: ReviewRequest, identity: Identity) -> dict[str, Any]:
    try:
        owner = _owner(identity)
        return _service().review_evidence(owner, evidence_id, state=request.state, reviewer=owner, rationale=request.rationale)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.post("/claims/{claim_id}/review")
def review_claim(claim_id: str, request: ReviewRequest, identity: Identity) -> dict[str, Any]:
    try:
        owner = _owner(identity)
        return _service().review_claim(owner, claim_id, state=request.state, reviewer=owner, rationale=request.rationale)
    except (FileNotFoundError, TypeError, ValueError) as exc:
        raise _translate(exc) from exc


@router.get("/ambiguity-queue")
def ambiguity_queue(identity: Identity) -> dict[str, Any]:
    return _service().ambiguity_queue(_owner(identity))


@router.get("/readiness")
def readiness(identity: Identity) -> dict[str, Any]:
    return _service().readiness(_owner(identity))
