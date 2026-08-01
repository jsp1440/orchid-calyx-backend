from __future__ import annotations

from uuid import uuid4

from .models import ActionClass, AgentResponse, AgentStep, RequestIntent
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


class CalyxAgentService:
    """Structured Calyx planning with optional governed external synthesis."""

    def __init__(
        self,
        registry: AgentToolRegistry | None = None,
        provider: AgentProvider | None = None,
    ) -> None:
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

    def handle(
        self,
        *,
        actor: str,
        request_text: str,
        use_provider: bool = True,
    ) -> AgentResponse:
        text = request_text.strip()
        if not text:
            raise ValueError("REQUEST_TEXT_REQUIRED")
        intent = classify_intent(text)
        action_class = required_action_class(intent)
        response = AgentResponse(
            request_id=str(uuid4()),
            actor=actor,
            intent=intent,
            summary=self._summary(intent, text),
            provider_status=self.provider_status(),
        )

        if action_class in {ActionClass.OWNER_APPROVAL, ActionClass.SCIENTIFIC_APPROVAL}:
            response.approval_required = True
            response.approval_reason = approval_reason(intent)
            response.steps.append(
                AgentStep(
                    step_id="approval-1",
                    title="Request explicit governed approval",
                    tool_id=None,
                    action_class=action_class,
                    rationale=response.approval_reason or "Approval is required.",
                    status="blocked_pending_approval",
                )
            )
            response.uncertainties.append(
                "No consequential action was executed; request content cannot grant its own approval."
            )
            return response

        tool_ids = self._select_tools(intent, text)
        previous: str | None = None
        for index, tool_id in enumerate(tool_ids, start=1):
            step_id = f"inspect-{index}"
            response.steps.append(
                AgentStep(
                    step_id=step_id,
                    title=f"Inspect {tool_id.replace('.', ' ')}",
                    tool_id=tool_id,
                    action_class=ActionClass.READ_ONLY,
                    rationale="Collect current Continuum evidence before proposing work.",
                    dependencies=((previous,) if previous else ()),
                    status="completed",
                )
            )
            response.tool_results.append(self.registry.execute(tool_id))
            previous = step_id

        if intent in {RequestIntent.PLAN_BUILD, RequestIntent.MONITOR} or self._is_journalism_request(text):
            response.steps.append(
                AgentStep(
                    step_id="prepare-1",
                    title=(
                        "Prepare an evidence-grounded journalism brief"
                        if self._is_journalism_request(text)
                        else "Prepare a bounded implementation or monitoring specification"
                    ),
                    tool_id=None,
                    action_class=ActionClass.PREPARE_ONLY,
                    rationale=(
                        "Calyx may prepare evidence packets and article briefs, but publication remains approval-gated."
                        if self._is_journalism_request(text)
                        else "Preparation may proceed, but repository or schedule mutation remains approval-gated."
                    ),
                    dependencies=((previous,) if previous else ()),
                    status="planned",
                )
            )

        if use_provider and self.provider is not None:
            self._apply_provider_synthesis(response, text)
        elif self._provider_configuration_error:
            response.uncertainties.append(
                "External provider configuration is invalid; deterministic planning was used."
            )
        elif use_provider:
            response.uncertainties.append(
                "No external language-model provider is configured; this response uses deterministic planning only."
            )
        return response

    def _apply_provider_synthesis(self, response: AgentResponse, text: str) -> None:
        assert self.provider is not None
        request = ProviderRequest(
            request_id=response.request_id,
            user_request=text,
            deterministic_summary=response.summary,
            intent=response.intent.value,
            approval_required=response.approval_required,
            approval_reason=response.approval_reason,
            steps=tuple(step.to_dict() for step in response.steps),
            tool_results=tuple(result.to_dict() for result in response.tool_results),
        )
        try:
            synthesis = self.provider.synthesize(request)
        except ProviderError:
            response.provider_status = "unavailable"
            response.uncertainties.append(
                "The external provider was unavailable; deterministic planning remains authoritative."
            )
            return
        response.answer = synthesis.text
        response.provider = synthesis.provider
        response.provider_model = synthesis.model
        response.provider_response_id = synthesis.response_id
        response.provider_status = "completed"

    @staticmethod
    def _is_journalism_request(text: str) -> bool:
        normalized = text.casefold()
        return any(term in normalized for term in _JOURNALISM_TERMS)

    @classmethod
    def _select_tools(cls, intent: RequestIntent, text: str) -> tuple[str, ...]:
        if cls._is_journalism_request(text):
            return (
                "journalism.readiness",
                "brain.readiness",
                "continuum.build_inventory",
            )
        if intent in {RequestIntent.AUDIT, RequestIntent.INSPECT}:
            return ("brain.readiness", "mission_control.readiness")
        if intent in {RequestIntent.PLAN_BUILD, RequestIntent.MONITOR}:
            return (
                "brain.readiness",
                "mission_control.readiness",
                "continuum.build_inventory",
            )
        return ("continuum.build_inventory",)

    @classmethod
    def _summary(cls, intent: RequestIntent, text: str) -> str:
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
