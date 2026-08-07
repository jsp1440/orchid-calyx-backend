from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from .durable_repository import DurableUniversityError
from .learner_auth import verify_university_actor
from .session_discovery import list_owned_session_summaries

router = APIRouter(tags=["orchid-continuum-university"])
LearnerAuth = Annotated[dict, Depends(verify_university_actor)]


@router.get("/sessions")
def list_my_sessions(
    request: Request,
    auth: LearnerAuth,
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=512),
):
    actor = str(auth.get("subject") or auth.get("actor") or "").strip()
    if auth.get("auth_type") != "university_learner" or not actor.startswith("supabase:"):
        raise HTTPException(
            status_code=401,
            detail={
                "code": "LEARNER_SESSION_REQUIRED",
                "message": "A verified learner session is required for session discovery",
            },
        )
    try:
        return list_owned_session_summaries(actor=actor, limit=limit, cursor=cursor)
    except DurableUniversityError as exc:
        status = 422 if exc.code in {"INVALID_SESSION_CURSOR", "INVALID_SESSION_LIST_LIMIT"} else 403
        raise HTTPException(
            status_code=status,
            detail={
                "code": exc.code,
                "message": exc.message,
                "request_id": request.headers.get("x-request-id"),
            },
        ) from exc
