from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class ActionClass(StrEnum):
    READ_ONLY = "read_only"
    PREPARE_ONLY = "prepare_only"
    OWNER_APPROVAL = "owner_approval"
    SCIENTIFIC_APPROVAL = "scientific_approval"


class RequestIntent(StrEnum):
    INSPECT = "inspect"
    AUDIT = "audit"
    PLAN_BUILD = "plan_build"
    MONITOR = "monitor"
    MUTATE = "mutate"
    SCIENTIFIC_PUBLICATION = "scientific_publication"
    GENERAL = "general"


@dataclass(frozen=True)
class ToolDescriptor:
    tool_id: str
    title: str
    action_class: ActionClass
    description: str
    timeout_seconds: int = 30
    writes_production: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ToolResult:
    tool_id: str
    status: str
    data: dict[str, Any]
    sources: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "status": self.status,
            "data": self.data,
            "sources": list(self.sources),
            "warnings": list(self.warnings),
        }


@dataclass(frozen=True)
class AgentStep:
    step_id: str
    title: str
    tool_id: str | None
    action_class: ActionClass
    rationale: str
    dependencies: tuple[str, ...] = ()
    status: str = "proposed"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["dependencies"] = list(self.dependencies)
        return payload


@dataclass
class AgentResponse:
    request_id: str
    actor: str
    intent: RequestIntent
    summary: str
    steps: list[AgentStep] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    approval_required: bool = False
    approval_reason: str | None = None
    provider_status: str = "not_configured"
    answer: str | None = None
    provider: str | None = None
    provider_model: str | None = None
    provider_response_id: str | None = None
    uncertainties: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "actor": self.actor,
            "intent": self.intent.value,
            "summary": self.summary,
            "answer": self.answer,
            "steps": [step.to_dict() for step in self.steps],
            "tool_results": [result.to_dict() for result in self.tool_results],
            "approval_required": self.approval_required,
            "approval_reason": self.approval_reason,
            "provider_status": self.provider_status,
            "provider": self.provider,
            "provider_model": self.provider_model,
            "provider_response_id": self.provider_response_id,
            "uncertainties": self.uncertainties,
            "private_reasoning_stored": False,
        }
