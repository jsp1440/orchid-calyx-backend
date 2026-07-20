from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key

from .models import EvidenceInput, SourceAnchor
from .repository import MemoryCandidateRepository
from .service import CandidateExtractionService

router = APIRouter(prefix="/api/candidate-knowledge", tags=["candidate-knowledge"], dependencies=[Depends(verify_owner_or_api_key)])
REPOSITORY = MemoryCandidateRepository()
SERVICE = CandidateExtractionService(REPOSITORY)


class AnchorIn(BaseModel):
    anchor_id: int = Field(gt=0)
    ordered_span: int = Field(0, ge=0)
    page_number: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    block_id: str | None = None
    logical_unit: str | None = None
    bounding_region: dict[str, Any] | None = None
    locator: dict[str, Any] = {}


class EvidenceIn(BaseModel):
    source_object_type: str
    source_object_id: int = Field(gt=0)
    revision_id: int = Field(gt=0)
    extraction_run_id: int = Field(gt=0)
    text: str = Field(min_length=1)
    source_anchors: list[AnchorIn] = Field(min_length=1)
    display_policy: str = "UNKNOWN_REQUIRES_REVIEW"
    internal_use_permission: bool = False
    language: str = "en"
    metadata: dict[str, Any] = {}


class PreviewIn(BaseModel):
    evidence: list[EvidenceIn] = Field(min_length=1, max_length=500)
    configuration: dict[str, Any] = {}


class ReviewDecision(BaseModel):
    decision: str
    rationale: str = Field(min_length=1)


def _evidence(value: EvidenceIn) -> EvidenceInput:
    data = value.model_dump()
    data["source_anchors"] = tuple(SourceAnchor(**anchor) for anchor in data["source_anchors"])
    return EvidenceInput(**data)


@router.post("/preview", status_code=201)
def preview(payload: PreviewIn):
    try:
        return SERVICE.preview([_evidence(item) for item in payload.evidence], payload.configuration)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/runs/{run_id}/execute")
def execute(run_id: int):
    return SERVICE.execute(run_id)


@router.get("/runs/{run_id}")
def status(run_id: int):
    return REPOSITORY.status(run_id)


@router.get("/runs/{run_id}/items")
def items(run_id: int):
    return {"items": REPOSITORY.items[run_id]}


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: int):
    return SERVICE.cancel(run_id)


@router.post("/runs/{run_id}/resume")
def resume(run_id: int):
    return SERVICE.resume(run_id)


@router.get("/candidates")
def candidates(kind: str | None = None, review_state: str | None = None, active: bool = True):
    values = [x for x in REPOSITORY.candidates if x["active"] == active]
    if kind:
        values = [x for x in values if x["kind"] == kind]
    if review_state:
        values = [x for x in values if x["review_state"] == review_state]
    return {"items": values}


@router.get("/candidates/{candidate_id}")
def candidate(candidate_id: int):
    value = next((x for x in REPOSITORY.candidates if x["candidate_id"] == candidate_id), None)
    if value is None:
        raise HTTPException(404, "CANDIDATE_NOT_FOUND")
    return {**value, "evidence": [x for x in REPOSITORY.evidence_links if x["candidate_id"] == candidate_id]}


@router.get("/reviews")
def reviews(state: str = "OPEN"):
    return {"items": [x for x in REPOSITORY.reviews.values() if x["state"] == state]}


@router.post("/reviews/{review_id}/resolve")
def resolve(review_id: int, payload: ReviewDecision, auth: Annotated[dict, Depends(verify_owner_or_api_key)]):
    actor = str(auth.get("actor") or auth.get("subject") or "operator")
    try:
        return REPOSITORY.resolve_review(review_id, payload.decision, payload.rationale, actor)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/duplicates")
def duplicates():
    return {"items": list(REPOSITORY.duplicate_groups.values())}


@router.get("/conflicts")
def conflicts():
    return {"items": list(REPOSITORY.conflicts.values())}


@router.get("/health")
def health():
    return {"status": "ok", "candidate_only": True, "publishes_graph": False, "extractor_version": SERVICE.extractor_version, "ruleset_version": SERVICE.ruleset_version}
