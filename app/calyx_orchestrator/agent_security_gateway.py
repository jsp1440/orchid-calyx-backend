from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import StrEnum

from .github_coding_executor import (
    CodingAgentProvider,
    DispatchRequest,
    DispatchResult,
    RepositoryInspectionGateway,
    RepositorySnapshot,
)


class ActionRisk(StrEnum):
    READ = "read"
    WRITE = "write"
    DESTRUCTIVE = "destructive"
    CREDENTIAL = "credential"
    PRODUCTION = "production"
    PUBLICATION = "publication"
    SPENDING = "spending"


PRIVILEGED_RISKS = frozenset(
    {
        ActionRisk.DESTRUCTIVE,
        ActionRisk.CREDENTIAL,
        ActionRisk.PRODUCTION,
        ActionRisk.PUBLICATION,
        ActionRisk.SPENDING,
    }
)


@dataclass(frozen=True, slots=True)
class AgentPolicy:
    scopes: frozenset[str]


@dataclass(frozen=True, slots=True)
class ToolPolicy:
    required_scopes: frozenset[str]
    allowed_risks: frozenset[ActionRisk]
    resource_allowlist: frozenset[str] = frozenset()
    max_cost_units: int = 1
    approval_required_for: frozenset[ActionRisk] = PRIVILEGED_RISKS


@dataclass(frozen=True, slots=True)
class GatewayPolicy:
    agents: Mapping[str, AgentPolicy]
    tools: Mapping[str, ToolPolicy]
    enabled: bool = True
    max_total_cost_units: int = 25


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    request_id: str
    agent_id: str
    tool_name: str
    risk: ActionRisk
    resource: str | None = None
    provider: str | None = None
    untrusted_context: bool = False
    approved: bool = False
    cost_units: int = 1
    argument_count: int = 0


@dataclass(frozen=True, slots=True)
class SecurityAuditEvent:
    decision_id: str
    request_id: str
    agent_id: str
    tool_name: str
    risk: str
    resource: str | None
    provider: str | None
    allowed: bool
    reason: str
    cost_units: int
    argument_count: int
    metadata_fingerprint: str

    def as_dict(self) -> dict[str, object]:
        return {
            "decision_id": self.decision_id,
            "request_id": self.request_id,
            "agent_id": self.agent_id,
            "tool_name": self.tool_name,
            "risk": self.risk,
            "resource": self.resource,
            "provider": self.provider,
            "allowed": self.allowed,
            "reason": self.reason,
            "cost_units": self.cost_units,
            "argument_count": self.argument_count,
            "metadata_fingerprint": self.metadata_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class SecurityDecision:
    allowed: bool
    reason: str
    audit: SecurityAuditEvent


class AgentSecurityGateway:
    """Fail-closed policy boundary for MCP/tool/provider actions.

    Authorization is based on logical agent identity, tool, scope, resource,
    action risk, trust state, approval state, and bounded cost. Provider/model
    identity is recorded for provenance but deliberately does not participate in
    the authorization decision, so Claude/Gemini/OpenAI substitution cannot
    widen authority.

    Tool argument values are never accepted by this object and therefore cannot
    be persisted in its audit records. Callers may report only ``argument_count``.
    """

    def __init__(self, policy: GatewayPolicy) -> None:
        if policy.max_total_cost_units < 0:
            raise ValueError("SECURITY_GATEWAY_TOTAL_BUDGET_INVALID")
        self.policy = policy
        self._spent_cost_units = 0
        self._audit_events: list[SecurityAuditEvent] = []

    @property
    def spent_cost_units(self) -> int:
        return self._spent_cost_units

    @property
    def remaining_cost_units(self) -> int:
        return max(0, self.policy.max_total_cost_units - self._spent_cost_units)

    def audit_events(self) -> tuple[SecurityAuditEvent, ...]:
        return tuple(self._audit_events)

    def authorize(self, invocation: ToolInvocation) -> SecurityDecision:
        reason = self._decision_reason(invocation)
        allowed = reason == "ALLOW"
        if allowed:
            self._spent_cost_units += invocation.cost_units
        audit = self._audit(invocation, allowed=allowed, reason=reason)
        self._audit_events.append(audit)
        return SecurityDecision(allowed=allowed, reason=reason, audit=audit)

    def enforce(self, invocation: ToolInvocation) -> SecurityAuditEvent:
        decision = self.authorize(invocation)
        if not decision.allowed:
            raise PermissionError(f"AGENT_SECURITY_GATEWAY_DENIED:{decision.reason}")
        return decision.audit

    def _decision_reason(self, invocation: ToolInvocation) -> str:
        if not self.policy.enabled:
            return "GATEWAY_KILL_SWITCH"
        if not invocation.request_id.strip():
            return "REQUEST_ID_REQUIRED"
        if invocation.cost_units < 0:
            return "REQUEST_COST_INVALID"

        agent = self.policy.agents.get(invocation.agent_id)
        if agent is None:
            return "AGENT_NOT_ALLOWED"
        tool = self.policy.tools.get(invocation.tool_name)
        if tool is None:
            return "TOOL_NOT_ALLOWED"
        if invocation.risk not in tool.allowed_risks:
            return "RISK_NOT_ALLOWED"
        if not tool.required_scopes.issubset(agent.scopes):
            return "REQUIRED_SCOPE_MISSING"
        if tool.resource_allowlist:
            if not invocation.resource or invocation.resource not in tool.resource_allowlist:
                return "RESOURCE_NOT_ALLOWED"
        if invocation.untrusted_context and invocation.risk != ActionRisk.READ:
            return "UNTRUSTED_CONTEXT_MUTATION_PROHIBITED"
        if invocation.risk in tool.approval_required_for and not invocation.approved:
            return "EXPLICIT_APPROVAL_REQUIRED"
        if invocation.cost_units > tool.max_cost_units:
            return "REQUEST_COST_LIMIT_EXCEEDED"
        if self._spent_cost_units + invocation.cost_units > self.policy.max_total_cost_units:
            return "GATEWAY_BUDGET_EXHAUSTED"
        return "ALLOW"

    def _audit(
        self,
        invocation: ToolInvocation,
        *,
        allowed: bool,
        reason: str,
    ) -> SecurityAuditEvent:
        safe_metadata = {
            "request_id": invocation.request_id,
            "agent_id": invocation.agent_id,
            "tool_name": invocation.tool_name,
            "risk": invocation.risk.value,
            "resource": invocation.resource,
            "provider": invocation.provider,
            "allowed": allowed,
            "reason": reason,
            "cost_units": invocation.cost_units,
            "argument_count": invocation.argument_count,
        }
        canonical = json.dumps(
            safe_metadata,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        decision_id = hashlib.sha256(
            f"{invocation.request_id}|{fingerprint}".encode("utf-8")
        ).hexdigest()[:24]
        return SecurityAuditEvent(
            decision_id=decision_id,
            request_id=invocation.request_id,
            agent_id=invocation.agent_id,
            tool_name=invocation.tool_name,
            risk=invocation.risk.value,
            resource=invocation.resource,
            provider=invocation.provider,
            allowed=allowed,
            reason=reason,
            cost_units=invocation.cost_units,
            argument_count=invocation.argument_count,
            metadata_fingerprint=fingerprint,
        )


def build_github_coding_security_gateway(
    repository_allowlist: tuple[str, ...],
    *,
    enabled: bool = True,
    max_total_cost_units: int = 25,
) -> AgentSecurityGateway:
    resources = frozenset(repository_allowlist)
    return AgentSecurityGateway(
        GatewayPolicy(
            agents={
                "calyx.github_coding_agent": AgentPolicy(
                    scopes=frozenset({"repo.inspect", "repo.proposal.write"})
                )
            },
            tools={
                "github.repository.inspect": ToolPolicy(
                    required_scopes=frozenset({"repo.inspect"}),
                    allowed_risks=frozenset({ActionRisk.READ}),
                    resource_allowlist=resources,
                    max_cost_units=0,
                    approval_required_for=frozenset(),
                ),
                "github.coding_agent.dispatch": ToolPolicy(
                    required_scopes=frozenset({"repo.proposal.write"}),
                    allowed_risks=frozenset({ActionRisk.WRITE}),
                    resource_allowlist=resources,
                    max_cost_units=1,
                    approval_required_for=frozenset(),
                ),
            },
            enabled=enabled,
            max_total_cost_units=max_total_cost_units,
        )
    )


class SecuredRepositoryInspectionGateway:
    """Security wrapper around the existing repository-inspection gateway."""

    def __init__(
        self,
        *,
        inner: RepositoryInspectionGateway,
        security: AgentSecurityGateway,
        agent_id: str = "calyx.github_coding_agent",
    ) -> None:
        self.inner = inner
        self.security = security
        self.agent_id = agent_id

    def inspect(
        self,
        *,
        repository: str,
        objective: str,
        mission_id: str,
    ) -> RepositorySnapshot:
        self.security.enforce(
            ToolInvocation(
                request_id=f"{mission_id}:inspect",
                agent_id=self.agent_id,
                tool_name="github.repository.inspect",
                risk=ActionRisk.READ,
                resource=repository,
                cost_units=0,
                argument_count=3,
            )
        )
        return self.inner.inspect(
            repository=repository,
            objective=objective,
            mission_id=mission_id,
        )


class SecuredCodingAgentProvider:
    """Security wrapper around a provider-neutral coding-agent dispatcher."""

    def __init__(
        self,
        *,
        inner: CodingAgentProvider,
        security: AgentSecurityGateway,
        agent_id: str = "calyx.github_coding_agent",
    ) -> None:
        self.inner = inner
        self.security = security
        self.agent_id = agent_id
        self.provider_name = inner.provider_name
        self.executor_class = inner.executor_class

    def dispatch(self, request: DispatchRequest) -> DispatchResult:
        audit = self.security.enforce(
            ToolInvocation(
                request_id=f"{request.mission_id}:dispatch",
                agent_id=self.agent_id,
                tool_name="github.coding_agent.dispatch",
                risk=ActionRisk.WRITE,
                resource=request.repository,
                provider=self.provider_name,
                cost_units=1,
                argument_count=14,
            )
        )
        result = self.inner.dispatch(request)
        security_evidence = tuple(
            f"security-audit:{event.decision_id}"
            for event in self.security.audit_events()
            if event.request_id.startswith(f"{request.mission_id}:")
        )
        if f"security-audit:{audit.decision_id}" not in security_evidence:
            security_evidence = (*security_evidence, f"security-audit:{audit.decision_id}")
        return replace(
            result,
            validation_evidence=tuple(
                dict.fromkeys((*result.validation_evidence, *security_evidence))
            ),
        )
