"""FastAPI routes for Continuum Engineering Memory v1.

All routes require the repository's existing privileged/operator authorization
(:func:`app.security.verify_owner_or_api_key`).  There is no public scientific
endpoint here; this material is internal engineering memory only.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import verify_owner_or_api_key

from .redaction import ProtectedLocalityError
from .schemas import (
    FeedbackIn,
    LessonCreateIn,
    LessonInvalidateIn,
    LessonVerifyIn,
    RetrieveIn,
    RunCreateIn,
)
from .service import (
    NON_SCIENTIFIC_DISCLAIMER,
    EngineeringMemoryService,
    MemoryNotFoundError,
    MemoryValidationError,
    ScopeViolationError,
    lesson_to_public_dict,
)

router = APIRouter(prefix="/api/engineering-memory", tags=["engineering-memory"])

Db = Annotated[Session, Depends(get_db)]
Auth = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]

_service = EngineeringMemoryService()


def _guard(db: Session, fn):
    """Translate service errors into HTTP responses and commit on success."""

    try:
        result = fn()
        db.commit()
        return result
    except (MemoryValidationError, ProtectedLocalityError) as exc:
        db.rollback()
        raise HTTPException(
            status_code=422, detail={"code": "INVALID", "message": str(exc)}
        )
    except ScopeViolationError as exc:
        db.rollback()
        raise HTTPException(
            status_code=403, detail={"code": "SCOPE_VIOLATION", "message": str(exc)}
        )
    except MemoryNotFoundError as exc:
        db.rollback()
        raise HTTPException(
            status_code=404, detail={"code": "NOT_FOUND", "message": str(exc)}
        )


@router.post("/runs", status_code=201)
def create_run(body: RunCreateIn, db: Db, _auth: Auth):
    run = _guard(db, lambda: _service.capture_run(db, body.model_dump()))
    return {
        "run_id": run.run_id,
        "redaction_status": run.redaction_status,
        "evidence_class": run.evidence_class,
    }


@router.post("/lessons", status_code=201)
def create_lesson(body: LessonCreateIn, db: Db, _auth: Auth):
    lesson = _guard(db, lambda: _service.create_lesson(db, body.model_dump()))
    return lesson_to_public_dict(lesson)


@router.post("/lessons/{lesson_id}/verify")
def verify_lesson(lesson_id: str, body: LessonVerifyIn, db: Db, _auth: Auth):
    lesson = _guard(
        db,
        lambda: _service.verify_lesson(
            db, lesson_id, body.workspace_scope, body.evidence
        ),
    )
    return lesson_to_public_dict(lesson)


@router.post("/lessons/{lesson_id}/invalidate")
def invalidate_lesson(lesson_id: str, body: LessonInvalidateIn, db: Db, _auth: Auth):
    lesson = _guard(
        db,
        lambda: _service.invalidate_lesson(
            db, lesson_id, body.workspace_scope, body.reason
        ),
    )
    return lesson_to_public_dict(lesson)


@router.post("/retrieve")
def retrieve(body: RetrieveIn, db: Db, _auth: Auth):
    result = _guard(db, lambda: _service.retrieve(db, body.model_dump()))
    return {
        "retrieval_id": result.retrieval.retrieval_id,
        "injected_chars": result.injected_chars,
        "injected_char_budget": result.retrieval.injected_char_budget,
        "latency_ms": result.retrieval.latency_ms,
        "evidence_class": "non_scientific_evidence",
        "disclaimer": NON_SCIENTIFIC_DISCLAIMER,
        "lessons": [
            {
                **lesson_to_public_dict(s.lesson),
                "rank": s.rank,
                "score": round(s.score, 6),
            }
            for s in result.scored
        ],
    }


@router.post("/retrievals/{retrieval_id}/feedback")
def record_feedback(retrieval_id: str, body: FeedbackIn, db: Db, _auth: Auth):
    retrieval = _guard(
        db,
        lambda: _service.record_feedback(
            db, retrieval_id, body.workspace_scope, body.model_dump()
        ),
    )
    return {
        "retrieval_id": retrieval.retrieval_id,
        "feedback": retrieval.feedback,
        "estimated_tokens_saved": retrieval.estimated_tokens_saved,
    }


@router.get("/metrics")
def metrics(workspace_scope: str, db: Db, _auth: Auth):
    try:
        return _service.metrics(db, workspace_scope)
    except MemoryValidationError as exc:
        raise HTTPException(
            status_code=422, detail={"code": "INVALID", "message": str(exc)}
        )
