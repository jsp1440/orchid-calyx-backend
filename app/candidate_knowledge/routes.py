from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key

from .dependencies import _REPOSITORY, _REPOSITORY_ERROR, _SERVICE
from .models import EvidenceInput, SourceAnchor

router = APIRouter(prefix="/api/candidate-knowledge", tags=["candidate-knowledge"], dependencies=[Depends(verify_owner_or_api_key)])
REPOSITORY = _REPOSITORY
REPOSITORY_ERROR = _REPOSITORY_ERROR
SERVICE = _SERVICE
def _available():
    if REPOSITORY is None or SERVICE is None:
        raise HTTPException(503, detail={"code": REPOSITORY_ERROR or "CANDIDATE_DATABASE_UNAVAILABLE"})
    return REPOSITORY, SERVICE
def _write(operation):
    repository, _ = _available()
    try: return repository.atomic(operation) if hasattr(repository, "atomic") else operation()
    except HTTPException: raise
    except Exception as exc: raise HTTPException(503, detail={"code":"CANDIDATE_DATABASE_UNAVAILABLE"}) from exc
def _read():
    repository, _ = _available()
    try:
        if hasattr(repository, "refresh"): repository.refresh()
        return repository
    except Exception as exc: raise HTTPException(503, detail={"code":"CANDIDATE_DATABASE_UNAVAILABLE"}) from exc


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
        _, service = _available()
        return _write(lambda: service.preview([_evidence(item) for item in payload.evidence], payload.configuration))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/runs/{run_id}/execute")
def execute(run_id: int):
    _, service = _available()
    try: return _write(lambda: service.execute(run_id))
    except KeyError as exc: raise HTTPException(404, detail={"code":"CANDIDATE_RUN_NOT_FOUND"}) from exc


@router.get("/runs/{run_id}")
def status(run_id: int):
    try: return _read().status(run_id)
    except KeyError as exc: raise HTTPException(404, detail={"code":"CANDIDATE_RUN_NOT_FOUND"}) from exc

@router.get("/runs")
def history(limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0,le=10000)):
    values=sorted(_read().runs.values(),key=lambda x:x["candidate_run_id"])
    return {"items":values[offset:offset+limit],"total":len(values),"limit":limit,"offset":offset}


@router.get("/runs/{run_id}/items")
def items(run_id: int):
    repository=_read()
    if run_id not in repository.items: raise HTTPException(404, detail={"code":"CANDIDATE_RUN_NOT_FOUND"})
    return {"items": sorted(repository.items[run_id],key=lambda x:x["item_id"])}


@router.post("/runs/{run_id}/cancel")
def cancel(run_id: int):
    _, service = _available()
    try:return _write(lambda:service.cancel(run_id))
    except KeyError as exc:raise HTTPException(404,detail={"code":"CANDIDATE_RUN_NOT_FOUND"}) from exc


@router.post("/runs/{run_id}/resume")
def resume(run_id: int):
    _, service = _available()
    try:return _write(lambda:service.resume(run_id))
    except KeyError as exc:raise HTTPException(404,detail={"code":"CANDIDATE_RUN_NOT_FOUND"}) from exc


@router.get("/candidates")
def candidates(kind: str | None = None, review_state: str | None = None, active: bool = True, limit:int=Query(50,ge=1,le=200), offset:int=Query(0,ge=0,le=10000)):
    values = [x for x in _read().candidates if x["active"] == active]
    if kind:
        values = [x for x in values if x["kind"] == kind]
    if review_state:
        values = [x for x in values if x["review_state"] == review_state]
    values=sorted(values,key=lambda x:(x["candidate_id"],x["version"]))
    return {"items": values[offset:offset+limit],"total":len(values),"limit":limit,"offset":offset}


@router.get("/candidates/{candidate_id}")
def candidate(candidate_id: int):
    repository=_read(); value = next((x for x in repository.candidates if x["candidate_id"] == candidate_id), None)
    if value is None:
        raise HTTPException(404, "CANDIDATE_NOT_FOUND")
    return {**value, "evidence": sorted([x for x in repository.evidence_links if x["candidate_id"] == candidate_id],key=lambda x:x["evidence_link_id"])}


@router.get("/reviews")
def reviews(state: str = "OPEN",limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0,le=10000)):
    values=sorted([x for x in _read().reviews.values() if x["state"] == state],key=lambda x:x["review_id"]);return {"items":values[offset:offset+limit],"total":len(values),"limit":limit,"offset":offset}


@router.post("/reviews/{review_id}/resolve")
def resolve(review_id: int, payload: ReviewDecision, auth: Annotated[dict, Depends(verify_owner_or_api_key)]):
    actor = str(auth.get("actor") or auth.get("subject") or "operator")
    try:
        repository,_=_available()
        if review_id not in repository.reviews: raise HTTPException(404,detail={"code":"CANDIDATE_REVIEW_NOT_FOUND"})
        return _write(lambda:repository.resolve_review(review_id, payload.decision, payload.rationale, actor))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get("/duplicates")
def duplicates(limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0,le=10000)):
    values=sorted(_read().duplicate_groups.values(),key=lambda x:x["duplicate_group_id"]);return {"items":values[offset:offset+limit],"total":len(values),"limit":limit,"offset":offset}


@router.get("/conflicts")
def conflicts(limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0,le=10000)):
    values=sorted(_read().conflicts.values(),key=lambda x:x["conflict_id"]);return {"items":values[offset:offset+limit],"total":len(values),"limit":limit,"offset":offset}

@router.get("/tombstones")
def tombstones(limit:int=Query(50,ge=1,le=200),offset:int=Query(0,ge=0,le=10000)):
    values=sorted(getattr(_read(),"tombstones",[]),key=lambda x:x.get("tombstone_id",0))
    return {"items":values[offset:offset+limit],"total":len(values),"limit":limit,"offset":offset}


@router.get("/health")
def health():
    _,service=_available();return {"status": "ok", "candidate_only": True, "publishes_graph": False, "persistent":hasattr(REPOSITORY,"atomic"),"extractor_version": service.extractor_version, "ruleset_version": service.ruleset_version}
