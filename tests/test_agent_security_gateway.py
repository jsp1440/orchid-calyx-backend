from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from app.calyx_orchestrator.agent_security_gateway import (
    ActionRisk,
    AgentPolicy,
    AgentSecurityGateway,
    GatewayPolicy,
    SecuredCodingAgentProvider,
    SecuredRepositoryInspectionGateway,
    ToolInvocation,
    ToolPolicy,
    build_github_coding_security_gateway,
)
from app.calyx_orchestrator.github_coding_executor import (
    BudgetClass,
    ConvergenceClass,
    DispatchRequest,
    DispatchResult,
    RepositorySnapshot,
)


def policy_gateway(
    *,
    enabled: bool = True,
    scopes: frozenset[str] = frozenset({"read", "write", "privileged"}),
    budget: int = 5,
) -> AgentSecurityGateway:
    return AgentSecurityGateway(
        GatewayPolicy(
            agents={"agent-1": AgentPolicy(scopes=scopes)},
            tools={
                "tool.read": ToolPolicy(
                    required_scopes=frozenset({"read"}),
                    allowed_risks=frozenset({ActionRisk.READ}),
                    max_cost_units=1,
                    approval_required_for=frozenset(),
                ),
                "tool.write": ToolPolicy(
                    required_scopes=frozenset({"write"}),
                    allowed_risks=frozenset({ActionRisk.WRITE}),
                    max_cost_units=1,
                    approval_required_for=frozenset(),
                ),
                "tool.production": ToolPolicy(
                    required_scopes=frozenset({"privileged"}),
                    allowed_risks=frozenset({ActionRisk.PRODUCTION}),
                    max_cost_units=1,
                ),
            },
            enabled=enabled,
            max_total_cost_units=budget,
        )
    )


def invoke(
    *,
    agent_id: str = "agent-1",
    tool_name: str = "tool.read",
    risk: ActionRisk = ActionRisk.READ,
    provider: str | None = None,
    untrusted_context: bool = False,
    approved: bool = False,
    cost_units: int = 1,
) -> ToolInvocation:
    return ToolInvocation(
        request_id="request-1",
        agent_id=agent_id,
        tool_name=tool_name,
        risk=risk,
        resource="resource-1",
        provider=provider,
        untrusted_context=untrusted_context,
        approved=approved,
        cost_units=cost_units,
        argument_count=2,
    )


def test_unknown_agent_is_denied() -> None:
    decision = policy_gateway().authorize(invoke(agent_id="unknown"))
    assert decision.allowed is False
    assert decision.reason == "AGENT_NOT_ALLOWED"


def test_non_allowlisted_tool_is_denied() -> None:
    decision = policy_gateway().authorize(invoke(tool_name="tool.shell"))
    assert decision.allowed is False
    assert decision.reason == "TOOL_NOT_ALLOWED"


def test_missing_scope_is_denied() -> None:
    gateway = policy_gateway(scopes=frozenset({"read"}))
    decision = gateway.authorize(
        invoke(tool_name="tool.write", risk=ActionRisk.WRITE)
    )
    assert decision.allowed is False
    assert decision.reason == "REQUIRED_SCOPE_MISSING"


def test_explicitly_scoped_read_is_allowed() -> None:
    gateway = policy_gateway(scopes=frozenset({"read"}))
    decision = gateway.authorize(invoke())
    assert decision.allowed is True
    assert decision.reason == "ALLOW"
    assert gateway.spent_cost_units == 1


def test_untrusted_context_cannot_trigger_write() -> None:
    decision = policy_gateway().authorize(
        invoke(
            tool_name="tool.write",
            risk=ActionRisk.WRITE,
            untrusted_context=True,
        )
    )
    assert decision.allowed is False
    assert decision.reason == "UNTRUSTED_CONTEXT_MUTATION_PROHIBITED"


def test_privileged_action_requires_explicit_approval() -> None:
    gateway = policy_gateway()
    denied = gateway.authorize(
        invoke(tool_name="tool.production", risk=ActionRisk.PRODUCTION)
    )
    allowed = gateway.authorize(
        ToolInvocation(
            request_id="request-2",
            agent_id="agent-1",
            tool_name="tool.production",
            risk=ActionRisk.PRODUCTION,
            resource="resource-1",
            approved=True,
            cost_units=1,
        )
    )
    assert denied.reason == "EXPLICIT_APPROVAL_REQUIRED"
    assert allowed.allowed is True


def test_kill_switch_blocks_all_outbound_actions() -> None:
    decision = policy_gateway(enabled=False).authorize(invoke(cost_units=0))
    assert decision.allowed is False
    assert decision.reason == "GATEWAY_KILL_SWITCH"


def test_quota_exhaustion_blocks_additional_actions() -> None:
    gateway = policy_gateway(budget=1)
    assert gateway.authorize(invoke()).allowed is True
    second = gateway.authorize(
        ToolInvocation(
            request_id="request-2",
            agent_id="agent-1",
            tool_name="tool.read",
            risk=ActionRisk.READ,
            resource="resource-1",
            cost_units=1,
        )
    )
    assert second.allowed is False
    assert second.reason == "GATEWAY_BUDGET_EXHAUSTED"


def test_audit_record_is_secret_safe_metadata_only() -> None:
    secret_value = "sk-this-must-never-appear"
    gateway = policy_gateway()
    audit = gateway.authorize(invoke(provider="gemini")).audit
    payload = json.dumps(audit.as_dict(), sort_keys=True)
    assert secret_value not in payload
    assert "argument_count" in payload
    assert "arguments" not in payload
    assert "gemini" in payload


def test_provider_identity_does_not_change_authorization() -> None:
    claude = policy_gateway().authorize(invoke(provider="claude"))
    gemini = policy_gateway().authorize(invoke(provider="gemini"))
    openai = policy_gateway().authorize(invoke(provider="openai"))
    assert (claude.allowed, claude.reason) == (True, "ALLOW")
    assert (gemini.allowed, gemini.reason) == (True, "ALLOW")
    assert (openai.allowed, openai.reason) == (True, "ALLOW")


@dataclass
class InnerInspector:
    calls: int = 0

    def inspect(self, *, repository: str, objective: str, mission_id: str) -> RepositorySnapshot:
        self.calls += 1
        return RepositorySnapshot(
            repository=repository,
            base_ref="oc-autonomous-integration",
            base_sha="a" * 40,
        )


@dataclass
class InnerProvider:
    provider_name: str = "gemini"
    executor_class: str = "test-provider"
    calls: int = 0

    def dispatch(self, request: DispatchRequest) -> DispatchResult:
        self.calls += 1
        return DispatchResult(
            provider=self.provider_name,
            executor_class=self.executor_class,
            repository=request.repository,
            base_sha=request.base_sha,
            branch="agent/mission-1",
            issue_number=1130,
            pull_request_number=1200,
            pull_request_url="https://github.com/jsp1440/orchid-calyx-backend/pull/1200",
            draft=True,
        )


def dispatch_request() -> DispatchRequest:
    return DispatchRequest(
        mission_id="OC-SECURITY-007",
        repository="jsp1440/orchid-calyx-backend",
        objective="Implement the bounded security gateway",
        acceptance_criteria=("draft only",),
        validation_commands=("pytest -q tests/test_agent_security_gateway.py",),
        budget_class=BudgetClass.NORMAL,
        convergence_class=ConvergenceClass.NEW,
        base_ref="oc-autonomous-integration",
        base_sha="a" * 40,
        related_issue_numbers=(1130,),
        overlapping_pr_numbers=(),
        continuation_pr_numbers=(),
        convergence_pr_numbers=(),
        superseded_pr_numbers=(),
        retry_count=0,
    )


def test_secured_github_wrappers_allow_only_allowlisted_bounded_actions() -> None:
    security = build_github_coding_security_gateway(
        ("jsp1440/orchid-calyx-backend",)
    )
    inner_inspector = InnerInspector()
    inspector = SecuredRepositoryInspectionGateway(
        inner=inner_inspector,
        security=security,
    )
    snapshot = inspector.inspect(
        repository="jsp1440/orchid-calyx-backend",
        objective="Inspect bounded work",
        mission_id="OC-SECURITY-007",
    )
    assert snapshot.repository == "jsp1440/orchid-calyx-backend"
    assert inner_inspector.calls == 1

    inner_provider = InnerProvider()
    provider = SecuredCodingAgentProvider(inner=inner_provider, security=security)
    result = provider.dispatch(dispatch_request())
    assert inner_provider.calls == 1
    assert result.draft is True
    assert result.provider == "gemini"
    assert len([item for item in result.validation_evidence if item.startswith("security-audit:")]) == 2


def test_secured_github_wrapper_denies_non_allowlisted_repository_before_network() -> None:
    security = build_github_coding_security_gateway(
        ("jsp1440/orchid-calyx-backend",)
    )
    inner = InnerInspector()
    inspector = SecuredRepositoryInspectionGateway(inner=inner, security=security)
    with pytest.raises(PermissionError, match="RESOURCE_NOT_ALLOWED"):
        inspector.inspect(
            repository="attacker/other-repo",
            objective="Do not execute",
            mission_id="OC-SECURITY-007",
        )
    assert inner.calls == 0
