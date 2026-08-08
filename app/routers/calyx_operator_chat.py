"""Mission Control API for governed operator-to-Calyx conversation."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.security import verify_owner_or_api_key
from runtime.continuum_conversation import ContinuumConversationService
from runtime.operator_chat import GovernedOperatorChat

router = APIRouter(prefix="/brain/mission-control/chat", tags=["mission-control-chat"])
_chat = GovernedOperatorChat()
_continuum = ContinuumConversationService()
OwnerIdentity = Annotated[dict[str, object], Depends(verify_owner_or_api_key)]


class OperatorMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class CalyxReplyRequest(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    proposed_action: str | None = Field(default=None, max_length=200)


class AskContinuumRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    context: dict[str, Any] = Field(default_factory=dict)
    limit: int = Field(default=6, ge=1, le=12)


def _owner(identity: dict[str, object]) -> str:
    actor = str(identity.get("actor") or "").strip()
    if not actor:
        raise HTTPException(
            status_code=403, detail="Calyx conversation owner scope unavailable"
        )
    return actor


@router.get("/status")
def chat_status() -> dict[str, Any]:
    return {
        **_chat.status(),
        "ask_the_continuum_enabled": True,
        "ask_the_continuum_requires_authentication": True,
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
    }


def reset_chat_for_tests() -> None:
    global _chat
    _chat = GovernedOperatorChat()
