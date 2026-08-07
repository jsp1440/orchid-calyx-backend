from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.mission_control_access import AccessPrincipal
from app.review_api.dependencies import authenticated_principal

from .durable_repository import DurableUniversityError
from .reviewer_workspace import (
    list_reviewable_session_summaries,
    reviewer_context,
    reviewer_session_detail,
)
from .service import UniversityServiceError

router = APIRouter(tags=["orchid-continuum-university-reviewer"])
ReviewerPrincipal = Annotated[AccessPrincipal, Depends(authenticated_principal)]


def _translate(request: Request, exc: Exception) -> HTTPException:
    if isinstance(exc, UniversityServiceError):
        return HTTPException(
            status_code=exc.status,
            detail={
                "code": exc.code,
                "message": exc.message,
                "request_id": request.headers.get("x-request-id"),
            },
        )
    if isinstance(exc, DurableUniversityError):
        status = 404 if exc.code == "SESSION_NOT_FOUND" else 409 if exc.code == "INVALID_REVIEW_STATE" else 422 if exc.code in {"INVALID_SESSION_CURSOR", "INVALID_REVIEW_QUEUE_LIMIT"} else 403
        return HTTPException(
            status_code=status,
            detail={
                "code": exc.code,
                "message": exc.message,
                "request_id": request.headers.get("x-request-id"),
            },
        )
    return HTTPException(status_code=500, detail={"code": "UNIVERSITY_REVIEWER_ERROR"})


@router.get("/reviewer/context")
def university_reviewer_context(principal: ReviewerPrincipal):
    return reviewer_context(principal)


@router.get("/reviewer/sessions")
def university_review_queue(
    request: Request,
    principal: ReviewerPrincipal,
    limit: int = Query(default=20, ge=1, le=50),
    cursor: str | None = Query(default=None, max_length=512),
):
    try:
        return list_reviewable_session_summaries(
            principal=principal,
            limit=limit,
            cursor=cursor,
        )
    except (UniversityServiceError, DurableUniversityError) as exc:
        raise _translate(request, exc) from exc


@router.get("/reviewer/sessions/{session_id}")
def university_reviewer_session_detail(
    session_id: str,
    request: Request,
    principal: ReviewerPrincipal,
):
    try:
        return reviewer_session_detail(principal=principal, session_id=session_id)
    except (UniversityServiceError, DurableUniversityError) as exc:
        raise _translate(request, exc) from exc
