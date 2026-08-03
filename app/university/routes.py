from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.routers.health import add_mission_control_cors_headers
from app.security import verify_owner_or_api_key

from .config import session_writes_enabled, university_enabled
from .fixtures import CHAPTER, LABORATORY
from .schemas import (
    CatalogItem,
    CatalogResponse,
    InvestigationEventCreate,
    LabSession,
    SessionCreate,
    UniversityCapability,
)
from .service import UniversityServiceError, UniversitySessionService

router = APIRouter(
    prefix="/learning",
    tags=["orchid-continuum-university"],
    dependencies=[Depends(add_mission_control_cors_headers)],
)
Auth = Annotated[dict, Depends(verify_owner_or_api_key)]


def capability() -> UniversityCapability:
    return UniversityCapability(
        enabled=university_enabled(),
        session_writes_enabled=session_writes_enabled(),
    )


def require_university() -> None:
    if not university_enabled():
        raise HTTPException(
            status_code=404,
            detail={
                "code": "UNIVERSITY_DISABLED",
                "message": "Orchid Continuum University prototype is disabled",
            },
        )


def require_session_writes() -> None:
    require_university()
    if not session_writes_enabled():
        raise HTTPException(
            status_code=403,
            detail={
                "code": "UNIVERSITY_SESSION_WRITES_DISABLED",
                "message": "Prototype session writes are disabled",
            },
        )


def actor_identity(auth: dict) -> tuple[str, bool]:
    actor = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not actor:
        raise HTTPException(401, detail={"code": "AUTHENTICATED_SUBJECT_REQUIRED"})
    return actor, auth.get("auth_type") == "api_key"


def invoke(request: Request, operation):
    try:
        return operation()
    except UniversityServiceError as exc:
        raise HTTPException(
            status_code=exc.status,
            detail={
                "code": exc.code,
                "message": exc.message,
                "request_id": request.headers.get("x-request-id"),
            },
        ) from exc


@router.get("/capabilities", response_model=UniversityCapability)
def capabilities() -> UniversityCapability:
    return capability()


@router.get("/catalog", response_model=CatalogResponse)
def catalog() -> CatalogResponse:
    require_university()
    return CatalogResponse(
        chapter=CatalogItem(
            id=CHAPTER["chapter_id"],
            title=CHAPTER["title"],
            summary=CHAPTER["summary"],
            status=CHAPTER["status"],
        ),
        laboratory=CatalogItem(
            id=LABORATORY["laboratory_id"],
            title=LABORATORY["title"],
            summary=LABORATORY["summary"],
            status=LABORATORY["status"],
        ),
        capability=capability(),
    )


@router.get("/chapters/{chapter_id}")
def chapter(chapter_id: str, request: Request):
    require_university()
    return invoke(request, lambda: UniversitySessionService.get_chapter(chapter_id))


@router.get("/laboratories/{laboratory_id}")
def laboratory(laboratory_id: str, request: Request):
    require_university()
    return invoke(request, lambda: UniversitySessionService.get_laboratory(laboratory_id))


@router.post("/sessions", status_code=201, response_model=LabSession)
def create_session(payload: SessionCreate, request: Request, auth: Auth):
    require_session_writes()
    actor, _ = actor_identity(auth)
    return invoke(request, lambda: UniversitySessionService.create_session(actor, payload))


@router.get("/sessions/{session_id}", response_model=LabSession)
def get_session(session_id: str, request: Request, auth: Auth):
    require_session_writes()
    actor, privileged = actor_identity(auth)
    return invoke(
        request,
        lambda: UniversitySessionService.get_session(session_id, actor, privileged),
    )


@router.post("/sessions/{session_id}/events", response_model=LabSession)
def append_event(
    session_id: str,
    payload: InvestigationEventCreate,
    request: Request,
    auth: Auth,
):
    require_session_writes()
    actor, privileged = actor_identity(auth)
    return invoke(
        request,
        lambda: UniversitySessionService.append_event(
            session_id, actor, privileged, payload
        ),
    )
