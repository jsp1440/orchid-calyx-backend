from __future__ import annotations

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.security import verify_owner_or_api_key

from .schemas import CaptureCreate, DecisionCreate
from .service import ScientificMemoryError, ScientificMemoryService

router = APIRouter(tags=["scientific-memory"])

Db = Annotated[Session, Depends(get_db)]
Auth = Annotated[dict[str, Any], Depends(verify_owner_or_api_key)]


def _subject(auth: dict[str, Any]) -> str:
    actor = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not actor:
        raise HTTPException(401, detail={"code": "AUTHENTICATED_SUBJECT_REQUIRED"})
    return actor


def _invoke(db: Session, operation: Callable[[], object]):
    try:
        result = operation()
        db.commit()
        return result
    except ScientificMemoryError as exc:
        db.rollback()
        raise HTTPException(exc.status, detail={"code": exc.code}) from exc


@router.post("/{project_id}/scientific-memory/captures", status_code=201)
def create_capture(project_id: str, payload: CaptureCreate, auth: Auth, db: Db):
    actor = _subject(auth)
    return _invoke(
        db,
        lambda: ScientificMemoryService().create_capture(
            db, project_id, actor, payload
        ),
    )


@router.get("/{project_id}/scientific-memory")
def recall_memory(
    project_id: str,
    auth: Auth,
    db: Db,
    query: str | None = Query(default=None, max_length=500),
    limit: int = Query(default=100, ge=1, le=500),
):
    actor = _subject(auth)
    return _invoke(
        db,
        lambda: ScientificMemoryService().recall(
            db, project_id, actor, query=query, limit=limit
        ),
    )


@router.post(
    "/{project_id}/scientific-memory/items/{item_id}/decisions", status_code=201
)
def record_decision(
    project_id: str, item_id: str, payload: DecisionCreate, auth: Auth, db: Db
):
    actor = _subject(auth)
    return _invoke(
        db,
        lambda: ScientificMemoryService().record_decision(
            db, project_id, actor, item_id, payload
        ),
    )
