"""Mission Control API for governed operator-to-Calyx conversation."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.conversation_memory.service import (
    ConversationMemoryError,
    ConversationMemoryService,
)
from app.database import get_db
from app.security import verify_owner_or_api_key
from runtime.continuum_conversation import ContinuumConversationService
from runtime.operator_chat import GovernedOperatorChat

router = APIRouter(prefix="/brain/mission-control/chat", tags=["mission-control-chat"])
_chat = GovernedOperatorChat()
_continuum = ContinuumConversationService()
OwnerIdentity = Annotated[dict[str, object], Depends(verify_owner_or_api_key)]
Db = Annotated[Session, Depends(get_db)]


class OperatorMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class CalyxReplyRequest(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    proposed_action: str | None = Field(default=None, max_length=200)


class AskContinuumRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    context: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=6, ge=1, le=12)


class ConversationCreateRequest(BaseModel):
    project_id: str | None = None
    title: str = Field(default="Calyx conversation", min_length=1, max_length=160)
    active_taxon_id: str | None = Field(default=None, max_length=500)
    active_document_id: str | None = Field(default=None, max_length=500)


def _owner(identity: dict[str, object]) -> str:
    actor = str(identity.get("subject") or identity.get("actor") or "").strip()
    if not actor:
        raise HTTPException(
            status_code=403, detail="Calyx conversation owner scope unavailable"
        )
    return actor


def _memory_call(db: Session, operation):
    try:
        return operation()
    except ConversationMemoryError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status, detail={"code": exc.code}) from exc


def _resolved_context(
    stored: dict[str, Any], requested: dict[str, Any]
) -> dict[str, Any]:
    def value(key: str, fallback: Any) -> Any:
        return requested.get(key, fallback)

    return {
        "active_project_id": value("active_project_id", stored.get("project_id")),
        "active_taxon_id": value("active_taxon_id", stored.get("active_taxon_id")),
        "active_document_id": value(
            "active_document_id", stored.get("active_document_id")
        ),
    }


@router.get("/status")
def chat_status() -> dict[str, Any]:
    return {
        **_chat.status(),
        "ask_the_continuum_enabled": True,
        "ask_the_continuum_requires_authentication": True,
        "persistent_conversations_enabled": True,
        "conversation_history_is_evidence": False,
        "model_knowledge_fallback_enabled": False,
        "scientific_publication_authorized": False,
        "knowledge_graph_mutation_authorized": False,
    }


@router.get("/transcript")
def chat_transcript() -> dict[str, Any]:
    return {"messages": [message.as_dict() for message in _chat.transcript()]}


@router.post("/messages")
def post_operator_message(request: OperatorMessageRequest) -> dict[str, Any]:
    return _chat.receive(request.content).as_dict()


@router.post("/replies")
def post_calyx_reply(request: CalyxReplyRequest) -> dict[str, Any]:
    return _chat.reply(
        request.content,
        proposed_action=request.proposed_action,
    ).as_dict()


@router.post("/ask")
def ask_the_continuum(
    request: AskContinuumRequest, identity: OwnerIdentity
) -> dict[str, Any]:
    owner = _owner(identity)
    operator_message = _chat.receive(request.question)
    try:
        result = _continuum.ask(
            request.question,
            context=request.context,
            limit=request.limit,
            internal_access=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    calyx_message = _chat.reply(result["answer"])
    return {
        **result,
        "owner": owner,
        "operator_message_id": operator_message.message_id,
        "calyx_message_id": calyx_message.message_id,
        "requires_approval": calyx_message.requires_approval,
        "persistent": False,
    }


@router.post("/conversations", status_code=201)
def create_conversation(
    request: ConversationCreateRequest,
    identity: OwnerIdentity,
    db: Db,
) -> dict[str, Any]:
    owner = _owner(identity)
    return _memory_call(
        db,
        lambda: ConversationMemoryService(db).create_session(
            owner,
            project_id=request.project_id,
            title=request.title,
            active_taxon_id=request.active_taxon_id,
            active_document_id=request.active_document_id,
        ),
    )


@router.get("/conversations")
def list_conversations(
    identity: OwnerIdentity,
    db: Db,
    project_id: str | None = None,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
) -> dict[str, Any]:
    owner = _owner(identity)
    return _memory_call(
        db,
        lambda: ConversationMemoryService(db).list_sessions(
            owner,
            project_id=project_id,
            limit=limit,
            offset=offset,
        ),
    )


@router.get("/conversations/{conversation_id}")
def get_conversation(
    conversation_id: str,
    identity: OwnerIdentity,
    db: Db,
) -> dict[str, Any]:
    owner = _owner(identity)
    return _memory_call(
        db,
        lambda: ConversationMemoryService(db).get_session(conversation_id, owner),
    )


@router.post("/conversations/{conversation_id}/ask")
def ask_persistent_conversation(
    conversation_id: str,
    request: AskContinuumRequest,
    identity: OwnerIdentity,
    db: Db,
) -> dict[str, Any]:
    owner = _owner(identity)
    memory = ConversationMemoryService(db)
    stored = _memory_call(db, lambda: memory.get_session(conversation_id, owner))
    context = _resolved_context(stored, request.context)
    try:
        result = _continuum.ask(
            request.question,
            context=context,
            limit=request.limit,
            internal_access=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    persisted = _memory_call(
        db,
        lambda: memory.append_exchange(
            conversation_id,
            owner,
            question=request.question,
            answer=result["answer"],
            epistemic_status=result["epistemic_status"],
            context=result["context"],
            evidence=result["evidence"],
            tool_trace=result["tool_trace"],
        ),
    )
    _chat.receive(request.question)
    calyx_message = _chat.reply(result["answer"])
    return {
        **result,
        "owner": owner,
        "conversation_id": conversation_id,
        "persistent": True,
        "conversation_context_data_status": "CONVERSATION_CONTEXT",
        "conversation_history_is_evidence": False,
        "persisted_messages": persisted["messages"],
        "conversation": persisted["conversation"],
        "requires_approval": calyx_message.requires_approval,
    }


def reset_chat_for_tests() -> None:
    global _chat
    _chat = GovernedOperatorChat()
