"""Governed project-link actions for sources persisted in Calyx conversations."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.conversation_memory.service import (
    ConversationMemoryError,
    ConversationMemoryService,
)
from app.database import get_db
from app.research_workspace.schemas import DocumentLinkCreate
from app.research_workspace.service import (
    ResearchWorkspaceError,
    ResearchWorkspaceService,
)
from app.security import verify_owner_or_api_key

router = APIRouter(prefix="/brain/mission-control/chat", tags=["mission-control-chat"])
OwnerIdentity = Annotated[dict[str, object], Depends(verify_owner_or_api_key)]
Db = Annotated[Session, Depends(get_db)]


class ConversationSourceLinkRequest(BaseModel):
    relationship: Literal["SOURCE", "BACKGROUND", "METHOD", "CONTRADICTS"] = "SOURCE"


def _owner(identity: dict[str, object]) -> str:
    actor = str(identity.get("subject") or identity.get("actor") or "").strip()
    if not actor:
        raise HTTPException(
            status_code=403, detail="Calyx conversation owner scope unavailable"
        )
    return actor


def _source_ref(conversation: dict[str, Any], result_id: str) -> dict[str, Any]:
    target = result_id.strip()
    for message in conversation.get("messages") or []:
        for source in message.get("source_refs") or []:
            if str(source.get("result_id") or "").strip() == target:
                return dict(source)
    raise HTTPException(
        status_code=404, detail={"code": "CONVERSATION_SOURCE_NOT_FOUND"}
    )


def _document_identity(source: dict[str, Any]) -> tuple[str, str | None]:
    citation = dict(source.get("citation") or {})
    document_id = str(citation.get("document_id") or "").strip()
    if not document_id:
        raise HTTPException(
            status_code=422,
            detail={"code": "CONVERSATION_SOURCE_DOCUMENT_ID_UNAVAILABLE"},
        )
    revision_id = str(citation.get("revision_id") or "").strip() or None
    return document_id, revision_id


@router.post(
    "/conversations/{conversation_id}/sources/{result_id}/project-link",
    status_code=201,
)
def link_conversation_source_to_project(
    conversation_id: str,
    result_id: str,
    payload: ConversationSourceLinkRequest,
    identity: OwnerIdentity,
    db: Db,
) -> dict[str, Any]:
    """Save an exact persisted Calyx source identity to its conversation project."""
    owner = _owner(identity)
    try:
        conversation = ConversationMemoryService(db).get_session(conversation_id, owner)
    except ConversationMemoryError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail={"code": exc.code}) from exc

    project_id = str(conversation.get("project_id") or "").strip()
    if not project_id:
        raise HTTPException(
            status_code=409,
            detail={"code": "CONVERSATION_PROJECT_REQUIRED_FOR_SOURCE_LINK"},
        )

    source = _source_ref(conversation, result_id)
    document_id, revision_id = _document_identity(source)
    try:
        link = ResearchWorkspaceService(db).add_document(
            project_id,
            owner,
            DocumentLinkCreate(
                document_id=document_id,
                revision_id=revision_id,
                relationship=payload.relationship,
            ),
            False,
        )
    except ResearchWorkspaceError as exc:
        db.rollback()
        raise HTTPException(
            status_code=exc.status,
            detail={"code": exc.code, **(exc.extra or {})},
        ) from exc

    return {
        "conversation_id": conversation_id,
        "project_id": project_id,
        "result_id": result_id,
        "document_id": document_id,
        "revision_id": revision_id,
        "relationship": payload.relationship,
        "project_link": link,
        "conversation_history_is_evidence": False,
        "scientific_publication_authorized": False,
        "knowledge_graph_mutation_authorized": False,
    }
