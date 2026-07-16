from fastapi import APIRouter, Depends, HTTPException, Query
from app.security import verify_owner_or_api_key
from app.routers.health import add_mission_control_cors_headers
from .extractor import content_hash, extract
from .repository import create_source, decide, get_source, list_review, mark_published
from .schemas import ReviewDecision, TextIntakeRequest, UrlIntakeRequest

router = APIRouter(
    prefix="/api/intake",
    tags=["knowledge-intake"],
    dependencies=[Depends(verify_owner_or_api_key), Depends(add_mission_control_cors_headers)],
)


@router.post("/text", status_code=201)
def ingest_text(payload: TextIntakeRequest):
    result = extract(payload.content)
    return create_source(
        source_type="text",
        title=payload.title,
        content=payload.content,
        content_hash=content_hash(payload.content),
        source_url=str(payload.source_url) if payload.source_url else None,
        imported_by=payload.imported_by,
        extraction=result,
    )


@router.post("/url", status_code=201)
def ingest_url(payload: UrlIntakeRequest):
    result = extract(payload.content)
    return create_source(
        source_type="url",
        title=payload.title,
        content=payload.content,
        content_hash=content_hash(payload.content),
        source_url=str(payload.source_url),
        imported_by=payload.imported_by,
        extraction=result,
    )


@router.get("/review")
def review_queue(limit: int = Query(default=100, ge=1, le=500)):
    return {"items": list_review(limit)}


@router.get("/{source_id}")
def source_detail(source_id: int):
    result = get_source(source_id)
    if not result:
        raise HTTPException(status_code=404, detail="Intake source not found")
    return result


@router.post("/{source_id}/approve")
def approve(source_id: int, decision: ReviewDecision):
    result = decide(source_id, "APPROVED", decision.notes)
    if not result:
        raise HTTPException(status_code=404, detail="Intake source not found")
    return result


@router.post("/{source_id}/reject")
def reject(source_id: int, decision: ReviewDecision):
    result = decide(source_id, "REJECTED", decision.notes)
    if not result:
        raise HTTPException(status_code=404, detail="Intake source not found")
    return result


@router.post("/{source_id}/publish")
def publish(source_id: int):
    result = mark_published(source_id)
    if not result:
        raise HTTPException(status_code=409, detail="Source must exist and be APPROVED before publication")
    return {**result, "graph_mutated": False, "message": "Approved intake package published to the intake registry; canonical graph mutation remains disabled."}
