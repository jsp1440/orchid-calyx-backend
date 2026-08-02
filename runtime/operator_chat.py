"""Governed operator-to-Calyx conversation contract for Mission Control."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any, ClassVar


@dataclass(frozen=True)
class OperatorMessage:
    message_id: str
    role: str
    content: str
    created_at: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CalyxReply:
    message_id: str
    content: str
    created_at: str
    requires_approval: bool
    proposed_action: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class GovernedOperatorChat:
    """Store an auditable chat transcript and fail closed on action requests."""

    prohibited_actions: ClassVar[set[str]] = {
        "merge",
        "deploy",
        "publish",
        "delete-production-data",
        "send-external-message",
        "change-permissions",
        "change-governance",
    }

    def __init__(self) -> None:
        self._messages: list[OperatorMessage | CalyxReply] = []

    def receive(self, content: str, *, created_at: str | None = None) -> OperatorMessage:
        text = content.strip()
        if not text:
            raise ValueError("message content is required")
        timestamp = created_at or datetime.now(timezone.utc).isoformat()
        message = OperatorMessage(
            message_id=self._identifier("operator", text, timestamp),
            role="operator",
            content=text,
            created_at=timestamp,
        )
        self._messages.append(message)
        return message

    def reply(
        self,
        content: str,
        *,
        proposed_action: str | None = None,
        created_at: str | None = None,
    ) -> CalyxReply:
        text = content.strip()
        if not text:
            raise ValueError("reply content is required")
        timestamp = created_at or datetime.now(timezone.utc).isoformat()
        requires_approval = proposed_action is not None
        if proposed_action in self.prohibited_actions:
            requires_approval = True
        message = CalyxReply(
            message_id=self._identifier("calyx", text, timestamp),
            content=text,
            created_at=timestamp,
            requires_approval=requires_approval,
            proposed_action=proposed_action,
        )
        self._messages.append(message)
        return message

    def transcript(self) -> tuple[OperatorMessage | CalyxReply, ...]:
        return tuple(self._messages)

    def status(self) -> dict[str, Any]:
        return {
            "message_count": len(self._messages),
            "auditable": True,
            "automatic_merge": False,
            "automatic_deploy": False,
            "automatic_publication": False,
            "external_communication": False,
        }

    @staticmethod
    def _identifier(role: str, content: str, created_at: str) -> str:
        payload = f"{role}|{created_at}|{content}"
        return f"chat-{sha256(payload.encode('utf-8')).hexdigest()[:20]}"
