"""Mission Control API for governed operator-to-Calyx conversation."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from runtime.operator_chat import GovernedOperatorChat

router = APIRouter(prefix="/brain/mission-control/chat", tags=["mission-control-chat"])
_chat = GovernedOperatorChat()


class OperatorMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=8000)


class CalyxReplyRequest(BaseModel):
    content: str = Field(min_length=1, max_length=12000)
    proposed_action: str | None = Field(default=None, max_length=200)


@router.get("/status")
def chat_status() -> dict[str, Any]:
    return _chat.status()


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


def reset_chat_for_tests() -> None:
    global _chat
    _chat = GovernedOperatorChat()
