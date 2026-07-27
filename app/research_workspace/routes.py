from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers.health import add_mission_control_cors_headers
from app.security import verify_owner_or_api_key

from .models import ProjectDocument, ProjectEvidence, ProjectTaxon
from .schemas import (
    DocumentLinkCreate,
    EvidenceLinkCreate,
    NoteCreate,
    ProjectCreate,
    ProjectPatch,
    SavedSearchCreate,
    TaxonLinkCreate,
)
from .service import ResearchWorkspaceError, ResearchWorkspaceService

router = APIRouter(
    prefix="/api/research/projects",
    tags=["research-workspace"],
    dependencies=[Depends(add_mission_control_cors_headers)],
)

Auth = Annotated[dict, Depends(verify_owner_or_api_key)]
Db = Annotated[Session, Depends(get_db)]


def identity(auth: dict) -> tuple[str, bool]:
    actor = str(auth.get("subject") or auth.get("actor") or "").strip()
    if not actor:
        raise HTTPException(401, detail={"code": "AUTHENTICATED_SUBJECT_REQUIRED"})
    return actor, auth.get("auth_type") == "api_key"


def invoke(db: Session, request: Request, operation: Callable[[], object]):
    try:
        return operation()
    except ResearchWorkspaceError as exc:
        db.rollback()
        detail = {
            "code": exc.code,
            "request_id": request.headers.get("x-request-id"),
            **(exc.extra or {}),
        }
        raise HTTPException(exc.status, detail=detail) from exc


@router.get("")
def list_projects(
    request: Request,
    auth: Auth,
    db: Db,
    status: str | None = Query(default=None, pattern="^(ACTIVE|PAUSED|COMPLETED)$"),
    archived: bool = False,
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0, le=100_000),
):
    actor, privileged = identity(auth)
    return invoke(
        db,
        request,
        lambda: ResearchWorkspaceService(db).list_projects(
            actor, status, archived, limit, offset, privileged
        ),
    )


@router.post("", status_code=201)
def create_project(payload: ProjectCreate, request: Request, auth: Auth, db: Db):
    actor, _ = identity(auth)
    return invoke(
        db, request, lambda: ResearchWorkspaceService(db).create_project(actor, payload)
    )


@router.get("/{project_id}")
def get_project(project_id: str, request: Request, auth: Auth, db: Db):
    actor, privileged = identity(auth)
    return invoke(
        db,
        request,
        lambda: ResearchWorkspaceService(db).get_project(project_id, actor, privileged),
    )


@router.patch("/{project_id}")
def update_project(
    project_id: str, payload: ProjectPatch, request: Request, auth: Auth, db: Db
):
    actor, privileged = identity(auth)
    return invoke(
        db,
        request,
        lambda: ResearchWorkspaceService(db).update_project(
            project_id, actor, payload, privileged
        ),
    )


@router.post("/{project_id}/archive")
def archive_project(project_id: str, request: Request, auth: Auth, db: Db):
    actor, privileged = identity(auth)
    return invoke(
        db,
        request,
        lambda: ResearchWorkspaceService(db).set_archive(
            project_id, actor, True, privileged
        ),
    )


@router.post("/{project_id}/restore")
def restore_project(project_id: str, request: Request, auth: Auth, db: Db):
    actor, privileged = identity(auth)
    return invoke(
        db,
        request,
        lambda: ResearchWorkspaceService(db).set_archive(
            project_id, actor, False, privileged
        ),
    )


@router.get("/{project_id}/saved-searches")
def saved_searches(project_id: str, request: Request, auth: Auth, db: Db):
    actor, privileged = identity(auth)
    return invoke(
        db,
        request,
        lambda: ResearchWorkspaceService(db).list_saved_searches(
            project_id, actor, privileged
        ),
    )


@router.post("/{project_id}/saved-searches", status_code=201)
def create_saved_search(
    project_id: str, payload: SavedSearchCreate, request: Request, auth: Auth, db: Db
):
    actor, privileged = identity(auth)
    return invoke(
        db,
        request,
        lambda: ResearchWorkspaceService(db).create_saved_search(
            project_id, actor, payload, privileged
        ),
    )


@router.get("/{project_id}/notes")
def notes(project_id: str, request: Request, auth: Auth, db: Db):
    actor, privileged = identity(auth)
    return invoke(
        db,
        request,
        lambda: ResearchWorkspaceService(db).list_notes(project_id, actor, privileged),
    )


@router.post("/{project_id}/notes", status_code=201)
def create_note(
    project_id: str, payload: NoteCreate, request: Request, auth: Auth, db: Db
):
    actor, privileged = identity(auth)
    return invoke(
        db,
        request,
        lambda: ResearchWorkspaceService(db).create_note(
            project_id, actor, payload, privileged
        ),
    )


@router.get("/{project_id}/taxa")
def taxa(project_id: str, request: Request, auth: Auth, db: Db):
    actor, privileged = identity(auth)
    return invoke(
        db,
        request,
        lambda: ResearchWorkspaceService(db).list_links(
            project_id, actor, ProjectTaxon, privileged
        ),
    )


@router.post("/{project_id}/taxa", status_code=201)
def add_taxon(
    project_id: str, payload: TaxonLinkCreate, request: Request, auth: Auth, db: Db
):
    actor, privileged = identity(auth)
    return invoke(
        db,
        request,
        lambda: ResearchWorkspaceService(db).add_taxon(
            project_id, actor, payload, privileged
        ),
    )


@router.delete("/{project_id}/taxa/{taxon_id}")
def remove_taxon(project_id: str, taxon_id: str, request: Request, auth: Auth, db: Db):
    actor, privileged = identity(auth)
    return invoke(
        db,
        request,
        lambda: ResearchWorkspaceService(db).remove_link(
            project_id, actor, ProjectTaxon, {"taxon_id": taxon_id}, "TAXON", privileged
        ),
    )


@router.get("/{project_id}/documents")
def documents(project_id: str, request: Request, auth: Auth, db: Db):
    actor, privileged = identity(auth)
    return invoke(
        db,
        request,
        lambda: ResearchWorkspaceService(db).list_links(
            project_id, actor, ProjectDocument, privileged
        ),
    )


@router.post("/{project_id}/documents", status_code=201)
def add_document(
    project_id: str, payload: DocumentLinkCreate, request: Request, auth: Auth, db: Db
):
    actor, privileged = identity(auth)
    return invoke(
        db,
        request,
        lambda: ResearchWorkspaceService(db).add_document(
            project_id, actor, payload, privileged
        ),
    )


@router.delete("/{project_id}/documents/{document_id}")
def remove_document(
    project_id: str, document_id: str, request: Request, auth: Auth, db: Db
):
    actor, privileged = identity(auth)
    return invoke(
        db,
        request,
        lambda: ResearchWorkspaceService(db).remove_link(
            project_id,
            actor,
            ProjectDocument,
            {"document_id": document_id},
            "DOCUMENT",
            privileged,
        ),
    )


@router.get("/{project_id}/evidence")
def evidence(project_id: str, request: Request, auth: Auth, db: Db):
    actor, privileged = identity(auth)
    return invoke(
        db,
        request,
        lambda: ResearchWorkspaceService(db).list_links(
            project_id, actor, ProjectEvidence, privileged
        ),
    )


@router.post("/{project_id}/evidence", status_code=201)
def add_evidence(
    project_id: str, payload: EvidenceLinkCreate, request: Request, auth: Auth, db: Db
):
    actor, privileged = identity(auth)
    return invoke(
        db,
        request,
        lambda: ResearchWorkspaceService(db).add_evidence(
            project_id, actor, payload, privileged
        ),
    )


@router.delete("/{project_id}/evidence/{evidence_kind}/{evidence_id}")
def remove_evidence(
    project_id: str,
    evidence_kind: str,
    evidence_id: str,
    request: Request,
    auth: Auth,
    db: Db,
):
    actor, privileged = identity(auth)
    return invoke(
        db,
        request,
        lambda: ResearchWorkspaceService(db).remove_link(
            project_id,
            actor,
            ProjectEvidence,
            {"evidence_kind": evidence_kind.upper(), "evidence_id": evidence_id},
            "EVIDENCE",
            privileged,
        ),
    )


@router.get("/{project_id}/activity")
def activity(
    project_id: str,
    request: Request,
    auth: Auth,
    db: Db,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=100_000),
):
    actor, privileged = identity(auth)
    return invoke(
        db,
        request,
        lambda: ResearchWorkspaceService(db).activity(
            project_id, actor, limit, offset, privileged
        ),
    )
