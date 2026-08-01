from __future__ import annotations

from dataclasses import dataclass

from app.calyx_agent.providers import ProviderError, ProviderRequest, ProviderResponse
from app.calyx_agent.service import CalyxAgentService


@dataclass
class FakeProvider:
    provider_id: str = "fake"
    model: str = "fake-model"

    def synthesize(self, request: ProviderRequest) -> ProviderResponse:
        assert request.intent == "audit"
        assert request.approval_required is False
        assert request.tool_results
        return ProviderResponse(
            provider=self.provider_id,
            model=self.model,
            response_id="resp-test",
            text="Grounded synthesis from deterministic evidence.",
        )


@dataclass
class FailingProvider:
    provider_id: str = "fake"
    model: str = "fake-model"

    def synthesize(self, request: ProviderRequest) -> ProviderResponse:
        raise ProviderError("CALYX_PROVIDER_REQUEST_FAILED")


def test_provider_synthesizes_after_deterministic_tools() -> None:
    response = CalyxAgentService(provider=FakeProvider()).handle(
        actor="owner",
        request_text="audit the brain",
    )
    assert response.provider_status == "completed"
    assert response.answer == "Grounded synthesis from deterministic evidence."
    assert response.provider == "fake"
    assert response.provider_model == "fake-model"
    assert response.provider_response_id == "resp-test"
    assert all(step.status == "completed" for step in response.steps)


def test_provider_cannot_bypass_owner_approval_gate() -> None:
    response = CalyxAgentService(provider=FakeProvider()).handle(
        actor="owner",
        request_text="merge and deploy it",
    )
    assert response.approval_required is True
    assert response.answer is None
    assert response.provider_status == "configured"
    assert response.steps[0].status == "blocked_pending_approval"


def test_provider_cannot_bypass_scientific_approval_gate() -> None:
    response = CalyxAgentService(provider=FakeProvider()).handle(
        actor="owner",
        request_text="publish this scientific conclusion",
    )
    assert response.approval_required is True
    assert response.answer is None
    assert response.steps[0].action_class.value == "scientific_approval"


def test_provider_failure_falls_back_to_deterministic_response() -> None:
    response = CalyxAgentService(provider=FailingProvider()).handle(
        actor="owner",
        request_text="audit the brain",
    )
    assert response.provider_status == "unavailable"
    assert response.answer is None
    assert response.tool_results
    assert any("deterministic planning" in item for item in response.uncertainties)


def test_provider_can_be_disabled_per_request() -> None:
    response = CalyxAgentService(provider=FakeProvider()).handle(
        actor="owner",
        request_text="audit the brain",
        use_provider=False,
    )
    assert response.answer is None
    assert response.provider_status == "configured"
