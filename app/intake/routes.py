import os
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import Response
from app.security import verify_owner_or_api_key
from app.routers.health import add_mission_control_cors_headers
from .extractor import content_hash, extract
from app.storage import LocalImmutableStorage
from .repository import (add_document, create_batch, create_source, decide, finalize_batch,
                         get_batch, get_source, list_batches, list_review, mark_published, review_document)
from .schemas import DocumentReview, ReviewDecision, TextIntakeRequest, UrlIntakeRequest
from .universal import CLASSIFICATIONS, classify, extract_safe_text, validate_file

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


@router.post("/batches", status_code=207)
async def upload_batch(display_name: str = Form(...), source_label: str | None = Form(None),
                       notes: str | None = Form(None), uploader: str | None = Form(None),
                       files: list[UploadFile] = File(...)):
    if not files: raise HTTPException(400, detail={"code": "NO_FILES"})
    batch = create_batch(display_name[:500], source_label, notes, uploader)
    storage = LocalImmutableStorage()
    results, accepted, duplicates, failed, review_required = [], 0, 0, 0, 0
    max_bytes = int(os.getenv("INTAKE_MAX_FILE_BYTES", str(50 * 1024 * 1024)))
    for upload in files:
        try:
            data = await upload.read(max_bytes + 1)
            extension = validate_file(upload.filename or "unnamed", data, max_bytes)
            stored = storage.preserve(data, upload.filename or "unnamed")
            text, _ = extract_safe_text(extension, data)
            analysis = classify(stored.display_filename, text)
            document = add_document(batch_id=batch["id"], filename=upload.filename or "unnamed",
                                    media_type=upload.content_type, extension=extension, stored=stored,
                                    analysis=analysis, uploader=uploader)
            is_duplicate = document["duplicate_of_id"] is not None
            duplicates += int(is_duplicate); accepted += int(not is_duplicate); review_required += int(not is_duplicate)
            results.append({"filename": stored.display_filename, "status": "DUPLICATE" if is_duplicate else "PRESERVED", "document": document})
        except ValueError as exc:
            failed += 1; results.append({"filename": upload.filename, "status": "FAILED", "error": str(exc)})
        except Exception:
            failed += 1; results.append({"filename": upload.filename, "status": "FAILED", "error": "INGESTION_FAILED"})
        finally:
            await upload.close()
    batch = finalize_batch(batch["id"], accepted, duplicates, failed, review_required)
    return {"batch": batch, "files": results, "partial_success": failed > 0 and accepted + duplicates > 0, "canonical_graph_mutated": False}


@router.get("/batches")
def batches(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    return {"items": list_batches(limit, offset)}


@router.get("/batches/{batch_id}")
def batch_detail(batch_id: int):
    batch = get_batch(batch_id)
    if not batch: raise HTTPException(404, detail={"code": "BATCH_NOT_FOUND"})
    return batch


@router.patch("/documents/{document_id}/review")
def document_review(document_id: int, decision: DocumentReview):
    if decision.classification and decision.classification not in CLASSIFICATIONS:
        raise HTTPException(422, detail={"code": "INVALID_CLASSIFICATION"})
    try:
        result = review_document(document_id, decision.action, decision.actor, decision.note, decision.classification)
    except ValueError as exc:
        raise HTTPException(422, detail={"code": str(exc)}) from exc
    if not result: raise HTTPException(404, detail={"code": "DOCUMENT_NOT_FOUND"})
    return result


@router.get("/documents/{document_id}/original")
def original(document_id: int):
    import psycopg
    from psycopg.rows import dict_row
    from .repository import database_url
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT storage_key, display_title, media_type FROM oc_intake.documents WHERE id=%s", (document_id,))
            document = cur.fetchone()
    if not document: raise HTTPException(404, detail={"code": "DOCUMENT_NOT_FOUND"})
    data = LocalImmutableStorage().read(document["storage_key"])
    return Response(data, media_type=document["media_type"] or "application/octet-stream",
                    headers={"Content-Disposition": f'attachment; filename="{document["display_title"]}"', "Cache-Control": "private, no-store"})


# Keep this legacy dynamic route after every static GET route. Otherwise paths such
# as /batches are captured as source IDs and fail integer validation.
@router.get("/{source_id}")
def source_detail(source_id: int):
    result = get_source(source_id)
    if not result:
        raise HTTPException(status_code=404, detail="Intake source not found")
    return result
