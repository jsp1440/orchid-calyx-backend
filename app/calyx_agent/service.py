from __future__ import annotations

import re
from uuid import uuid4

from psycopg import Error as PsycopgError

from .models import ActionClass, AgentResponse, AgentStep, RequestIntent, ToolResult
from .policy import approval_reason, classify_intent, required_action_class
from .providers import (
    AgentProvider,
    ProviderError,
    ProviderRequest,
    provider_from_environment,
)
from .tools import AgentToolRegistry, default_tool_registry

_JOURNALISM_TERMS = (
    "article",
    "report",
    "journalism",
    "newsletter",
    "write about",
    "generate a story",
)
_DESIGN_TERMS = (
    "website",
    "web page",
    "frontend",
    "design",
    "accessibility",
    "user experience",
    "ux",
    "user interface",
    "ui",
    "navigation",
    "information architecture",
    "visualization",
)
_EDUCATION_TERMS = (
    "education",
    "university",
    "course",
    "lesson",
    "curriculum",
    "student",
    "assessment",
    "learning",
    "virtual lab",
    "workshop",
)


class CalyxAgentService:
    """Structured Calyx planning with optional governed external synthesis."""

    def __init__(self, registry: AgentToolRegistry | None = None, provider: AgentProvider | None = None) -> None:
        self.registry = registry or default_tool_registry()
        self.provider = provider
        self._provider_configuration_error: str | None = None
        if provider is None:
            try:
                self.provider = provider_from_environment()
            except (ProviderError, ValueError) as exc:
                self._provider_configuration_error = str(exc)

    def provider_status(self) -> str:
        if self._provider_configuration_error:
            return "configuration_error"
        return "configured" if self.provider is not None else "not_configured"

    def handle(self, *, actor: str, request_text: str, use_provider: bool = True) -> AgentResponse:
        text = request_text.strip()
        if not text:
            raise ValueError("REQUEST_TEXT_REQUIRED")
        intent = classify_intent(text)
        action_class = required_action_class(intent)
        response = AgentResponse(request_id=str(uuid4()), actor=actor, intent=intent, summary=self._summary(intent, text), provider_status=self.provider_status())
        if action_class in {ActionClass.OWNER_APPROVAL, ActionClass.SCIENTIFIC_APPROVAL}:
            response.approval_required = True
            response.approval_reason = approval_reason(intent)
            response.steps.append(AgentStep(step_id="approval-1", title="Request explicit governed approval", tool_id=None, action_class=action_class, rationale=response.approval_reason or "Approval is required.", status="blocked_pending_approval"))
            response.uncertainties.append("No consequential action was executed; request content cannot grant its own approval.")
            return response
        tool_ids = self._select_tools(intent, text)
        previous: str | None = None
        for index, tool_id in enumerate(tool_ids, start=1):
            step_id = f"inspect-{index}"
            response.steps.append(AgentStep(step_id=step_id, title=f"Inspect {tool_id.replace('.', ' ')}", tool_id=tool_id, action_class=ActionClass.READ_ONLY, rationale="Collect current Continuum evidence before proposing work.", dependencies=((previous,) if previous else ()), status="completed"))
            payload = {"query": text, "limit": 10} if tool_id == "design_intelligence.search" else None
            try:
                result = self.registry.execute(tool_id, payload)
            except PsycopgError:
                if tool_id != "design_intelligence.search":
                    raise
                result = ToolResult(
                    tool_id=tool_id,
                    status="degraded",
                    data={"query": text, "total": 0, "results": [], "store_status": "unavailable"},
                    sources=("app/design_intelligence/reasoning.py",),
                    warnings=("The configured Design Intelligence store could not be reached; no corpus results were returned.",),
                )
            response.tool_results.append(result)
            previous = step_id
        if intent in {RequestIntent.PLAN_BUILD, RequestIntent.MONITOR} or self._is_journalism_request(text) or self._is_design_request(text) or self._is_education_request(text):
            response.steps.append(AgentStep(step_id="prepare-1", title=self._preparation_title(text), tool_id=None, action_class=ActionClass.PREPARE_ONLY, rationale=self._preparation_rationale(text), dependencies=((previous,) if previous else ()), status="planned"))
        if use_provider and self.provider is not None:
            self._apply_provider_synthesis(response, text)
        elif self._provider_configuration_error:
            response.uncertainties.append("External provider configuration is invalid; deterministic planning was used.")
        elif use_provider:
            response.uncertainties.append("No external language-model provider is configured; this response uses deterministic planning only.")
        return response

    def _apply_provider_synthesis(self, response: AgentResponse, text: str) -> None:
        assert self.provider is not None
        request = ProviderRequest(request_id=response.request_id, user_request=text, deterministic_summary=response.summary, intent=response.intent.value, approval_required=response.approval_required, approval_reason=response.approval_reason, steps=tuple(step.to_dict() for step in response.steps), tool_results=tuple(result.to_dict() for result in response.tool_results))
        try:
            synthesis = self.provider.synthesize(request)
        except ProviderError:
            response.provider_status = "unavailable"
            response.uncertainties.append("The external provider was unavailable; deterministic planning remains authoritative.")
            return
        response.answer = synthesis.text
        response.provider = synthesis.provider
        response.provider_model = synthesis.model
        response.provider_response_id = synthesis.response_id
        response.provider_status = "completed"

    @staticmethod
    def _matches(text: str, terms: tuple[str, ...]) -> bool:
        normalized = text.casefold()
        return any(re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", normalized) for term in terms)

    @classmethod
    def _is_journalism_request(cls, text: str) -> bool:
        return cls._matches(text, _JOURNALISM_TERMS)

    @classmethod
    def _is_design_request(cls, text: str) -> bool:
        return cls._matches(text, _DESIGN_TERMS)

    @classmethod
    def _is_education_request(cls, text: str) -> bool:
        return cls._matches(text, _EDUCATION_TERMS)

    @classmethod
    def _select_tools(cls, intent: RequestIntent, text: str) -> tuple[str, ...]:
        normalized = text.casefold()
        if cls._is_education_request(text):
            tools = ["education.readiness", "design_intelligence.readiness"]
            if cls._is_design_request(text):
                tools.append("design_intelligence.search")
            tools.extend(("brain.readiness", "continuum.build_inventory"))
            return tuple(tools)
        if cls._is_design_request(text):
            return ("design_intelligence.readiness", "design_intelligence.search", "brain.readiness", "mission_control.readiness")
        if cls._is_journalism_request(text):
            return ("journalism.readiness", "brain.readiness", "continuum.build_inventory")
        if "archive" in normalized:
            return ("archive.readiness", "mission_control.readiness")
        if "harvester" in normalized or "connector" in normalized:
            return ("harvester.readiness", "mission_control.readiness")
        if intent in {RequestIntent.AUDIT, RequestIntent.INSPECT}:
            return ("brain.readiness", "mission_control.readiness")
        if intent in {RequestIntent.PLAN_BUILD, RequestIntent.MONITOR}:
            return ("brain.readiness", "mission_control.readiness", "continuum.build_inventory")
        return ("continuum.build_inventory",)

    @classmethod
    def _preparation_title(cls, text: str) -> str:
        if cls._is_education_request(text):
            return "Prepare a bounded education or University improvement specification"
        if cls._is_design_request(text):
            return "Prepare a bounded website design and accessibility specification"
        if cls._is_journalism_request(text):
            return "Prepare an evidence-grounded journalism brief"
        return "Prepare a bounded implementation or monitoring specification"

    @classmethod
    def _preparation_rationale(cls, text: str) -> str:
        if cls._is_education_request(text):
            return "Calyx may recommend curricula, lessons, assessments, and virtual labs; publication and implementation remain approval-gated."
        if cls._is_design_request(text):
            return "Calyx may recommend UX, accessibility, navigation, and visualization changes; repository mutation and deployment remain approval-gated."
        if cls._is_journalism_request(text):
            return "Calyx may prepare evidence packets and article briefs, but publication remains approval-gated."
        return "Preparation may proceed, but repository or schedule mutation remains approval-gated."

    @classmethod
    def _summary(cls, intent: RequestIntent, text: str) -> str:
        if cls._is_education_request(text):
            return "Calyx inspected educational-design knowledge and University runtime readiness."
        if cls._is_design_request(text):
            return "Calyx inspected website-design intelligence and prepared a governed improvement path."
        if cls._is_journalism_request(text):
            return "Calyx inspected journalism readiness and prepared an approval-gated article workflow."
        summaries = {
            RequestIntent.AUDIT: "Calyx performed a governed read-only audit plan.",
            RequestIntent.INSPECT: "Calyx inspected the currently registered Continuum capabilities.",
            RequestIntent.PLAN_BUILD: "Calyx inspected dependencies and prepared a bounded build-planning path.",
            RequestIntent.MONITOR: "Calyx prepared a monitoring design without changing schedules.",
            RequestIntent.MUTATE: "The requested mutation was blocked pending explicit owner approval.",
            RequestIntent.SCIENTIFIC_PUBLICATION: "The requested scientific publication was blocked pending canonical scientific review.",
            RequestIntent.GENERAL: "Calyx produced a structured response from currently registered internal evidence.",
        }
        return summaries[intent]
