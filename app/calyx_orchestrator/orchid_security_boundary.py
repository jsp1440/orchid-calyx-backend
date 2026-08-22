from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from .agent_security_gateway import (
    ActionRisk,
    AgentPolicy,
    AgentSecurityGateway,
    GatewayPolicy,
    PRIVILEGED_RISKS,
    ToolInvocation,
    ToolPolicy,
)


class DataClass(StrEnum):
    """Data sensitivity presented to an outbound execution surface."""

    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"
    SECRET = "secret"


class TransportClass(StrEnum):
    """How a declared capability reaches its execution target."""

    INTERNAL = "internal"
    CONNECTOR = "connector"
    MCP = "mcp"
    PROVIDER = "provider"


NON_SECRET_DATA_CLASSES = frozenset(
    {
        DataClass.PUBLIC,
        DataClass.INTERNAL,
        DataClass.SENSITIVE,
        DataClass.RESTRICTED,
    }
)


@dataclass(frozen=True, slots=True)
class CapabilityManifest:
    """Declarative authority for one tool/capability on one server."""

    server_id: str
    tool_name: str
    transport: TransportClass
    required_scopes: frozenset[str]
    allowed_risks: frozenset[ActionRisk]
    allowed_data_classes: frozenset[DataClass] = NON_SECRET_DATA_CLASSES
    resource_allowlist: frozenset[str] = frozenset()
    max_cost_units: int = 1
    approval_required_for: frozenset[ActionRisk] = PRIVILEGED_RISKS

    @property
    def policy_key(self) -> str:
        return f"{self.server_id}::{self.tool_name}"


@dataclass(frozen=True, slots=True)
class ServerManifest:
    """Identity and declared capabilities for an internal/connector/MCP/provider server."""

    server_id: str
    transport: TransportClass
    capabilities: tuple[CapabilityManifest, ...] = ()
    enabled: bool = True
    description: str = ""


@dataclass(frozen=True, slots=True)
class BoundaryAuditEvent:
    decision_id: str
    base_decision_id: str | None
    request_id: str
    agent_id: str
    server_id: str
    transport: str | None
    tool_name: str
    risk: str | None
    data_class: str
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
            "base_decision_id": self.base_decision_id,
            "request_id": self.request_id,
            "agent_id": self.agent_id,
            "server_id": self.server_id,
            "transport": self.transport,
            "tool_name": self.tool_name,
            "risk": self.risk,
            "data_class": self.data_class,
            "resource": self.resource,
            "provider": self.provider,
            "allowed": self.allowed,
            "reason": self.reason,
            "cost_units": self.cost_units,
            "argument_count": self.argument_count,
            "metadata_fingerprint": self.metadata_fingerprint,
        }


@dataclass(frozen=True, slots=True)
class BoundaryDecision:
    allowed: bool
    reason: str
    audit: BoundaryAuditEvent


class OrchidSecurityBoundary:
    """Common fail-closed execution boundary for Orchid Continuum.

    The boundary adds server identity, transport identity, capability manifests,
    and data-classification checks around the OC-SECURITY-007 policy engine.
    Provider/model identity is provenance only and never grants authority.

    Payload values are intentionally absent from this API. Callers can report
    only argument counts and safe resource identifiers, so credentials or model
    prompts cannot leak into the security audit ledger.
    """

    def __init__(
        self,
        *,
        agents: Mapping[str, AgentPolicy],
        servers: tuple[ServerManifest, ...] = (),
        enabled: bool = True,
        max_total_cost_units: int = 100,
    ) -> None:
        self._servers: dict[str, ServerManifest] = {}
        self._capabilities: dict[tuple[str, str], CapabilityManifest] = {}
        self._tool_policies: dict[str, ToolPolicy] = {}
        self._audit_events: list[BoundaryAuditEvent] = []
        self._gateway = AgentSecurityGateway(
            GatewayPolicy(
                agents=dict(agents),
                tools=self._tool_policies,
                enabled=enabled,
                max_total_cost_units=max_total_cost_units,
            )
        )
        for server in servers:
            self.register_server(server)

    @property
    def enabled(self) -> bool:
        return self._gateway.policy.enabled

    @property
    def spent_cost_units(self) -> int:
        return self._gateway.spent_cost_units

    @property
    def remaining_cost_units(self) -> int:
        return self._gateway.remaining_cost_units

    def audit_events(self) -> tuple[BoundaryAuditEvent, ...]:
        return tuple(self._audit_events)

    def register_server(self, manifest: ServerManifest) -> None:
        server_id = manifest.server_id.strip()
        if not server_id:
            raise ValueError("SECURITY_SERVER_ID_REQUIRED")
        if server_id in self._servers:
            raise ValueError("SECURITY_SERVER_ALREADY_REGISTERED")
        self._servers[server_id] = manifest
        for capability in manifest.capabilities:
            self.register_capability(capability)

    def register_capability(self, manifest: CapabilityManifest) -> None:
        server = self._servers.get(manifest.server_id)
        if server is None:
            raise ValueError("SECURITY_SERVER_NOT_REGISTERED")
        if manifest.transport != server.transport:
            raise ValueError("SECURITY_TRANSPORT_MISMATCH")
        if not manifest.tool_name.strip():
            raise ValueError("SECURITY_TOOL_NAME_REQUIRED")
        key = (manifest.server_id, manifest.tool_name)
        if key in self._capabilities:
            raise ValueError("SECURITY_CAPABILITY_ALREADY_REGISTERED")
        if manifest.max_cost_units < 0:
            raise ValueError("SECURITY_CAPABILITY_COST_INVALID")
        self._capabilities[key] = manifest
        self._tool_policies[manifest.policy_key] = ToolPolicy(
            required_scopes=manifest.required_scopes,
            allowed_risks=manifest.allowed_risks,
            resource_allowlist=manifest.resource_allowlist,
            max_cost_units=manifest.max_cost_units,
            approval_required_for=manifest.approval_required_for,
        )

    def manifest(self) -> dict[str, object]:
        servers = []
        for server_id in sorted(self._servers):
            server = self._servers[server_id]
            tools = [
                capability
                for (candidate_server, _), capability in self._capabilities.items()
                if candidate_server == server_id
            ]
            servers.append(
                {
                    "server_id": server.server_id,
                    "transport": server.transport.value,
                    "enabled": server.enabled,
                    "description": server.description,
                    "tools": [
                        {
                            "tool_name": tool.tool_name,
                            "required_scopes": sorted(tool.required_scopes),
                            "allowed_risks": sorted(risk.value for risk in tool.allowed_risks),
                            "allowed_data_classes": sorted(
                                data_class.value for data_class in tool.allowed_data_classes
                            ),
                            "resource_allowlist": sorted(tool.resource_allowlist),
                            "max_cost_units": tool.max_cost_units,
                            "approval_required_for": sorted(
                                risk.value for risk in tool.approval_required_for
                            ),
                        }
                        for tool in sorted(tools, key=lambda item: item.tool_name)
                    ],
                }
            )
        return {
            "boundary": "orchid-continuum-common-security",
            "enabled": self.enabled,
            "spent_cost_units": self.spent_cost_units,
            "remaining_cost_units": self.remaining_cost_units,
            "servers": servers,
        }

    def authorize_tool(
        self,
        *,
        request_id: str,
        agent_id: str,
        server_id: str,
        tool_name: str,
        data_class: DataClass | str = DataClass.INTERNAL,
        risk: ActionRisk | None = None,
        resource: str | None = None,
        provider: str | None = None,
        untrusted_context: bool = False,
        approved: bool = False,
        cost_units: int = 0,
        argument_count: int = 0,
    ) -> BoundaryDecision:
        normalized_data_class = self._normalize_data_class(data_class)
        server = self._servers.get(server_id)
        capability = self._capabilities.get((server_id, tool_name))

        if not self.enabled:
            return self._precheck_decision(
                request_id=request_id,
                agent_id=agent_id,
                server=server,
                server_id=server_id,
                tool_name=tool_name,
                risk=risk,
                data_class=normalized_data_class,
                resource=resource,
                provider=provider,
                allowed=False,
                reason="GATEWAY_KILL_SWITCH",
                cost_units=cost_units,
                argument_count=argument_count,
            )
        if server is None:
            return self._precheck_decision(
                request_id=request_id,
                agent_id=agent_id,
                server=None,
                server_id=server_id,
                tool_name=tool_name,
                risk=risk,
                data_class=normalized_data_class,
                resource=resource,
                provider=provider,
                allowed=False,
                reason="SERVER_NOT_DECLARED",
                cost_units=cost_units,
                argument_count=argument_count,
            )
        if not server.enabled:
            return self._precheck_decision(
                request_id=request_id,
                agent_id=agent_id,
                server=server,
                server_id=server_id,
                tool_name=tool_name,
                risk=risk,
                data_class=normalized_data_class,
                resource=resource,
                provider=provider,
                allowed=False,
                reason="SERVER_DISABLED",
                cost_units=cost_units,
                argument_count=argument_count,
            )
        if capability is None:
            return self._precheck_decision(
                request_id=request_id,
                agent_id=agent_id,
                server=server,
                server_id=server_id,
                tool_name=tool_name,
                risk=risk,
                data_class=normalized_data_class,
                resource=resource,
                provider=provider,
                allowed=False,
                reason="TOOL_NOT_DECLARED",
                cost_units=cost_units,
                argument_count=argument_count,
            )
        if normalized_data_class not in capability.allowed_data_classes:
            return self._precheck_decision(
                request_id=request_id,
                agent_id=agent_id,
                server=server,
                server_id=server_id,
                tool_name=tool_name,
                risk=risk,
                data_class=normalized_data_class,
                resource=resource,
                provider=provider,
                allowed=False,
                reason="DATA_CLASS_NOT_ALLOWED",
                cost_units=cost_units,
                argument_count=argument_count,
            )

        selected_risk = risk
        if selected_risk is None:
            if len(capability.allowed_risks) != 1:
                return self._precheck_decision(
                    request_id=request_id,
                    agent_id=agent_id,
                    server=server,
                    server_id=server_id,
                    tool_name=tool_name,
                    risk=None,
                    data_class=normalized_data_class,
                    resource=resource,
                    provider=provider,
                    allowed=False,
                    reason="RISK_CLASS_REQUIRED",
                    cost_units=cost_units,
                    argument_count=argument_count,
                )
            selected_risk = next(iter(capability.allowed_risks))

        base = self._gateway.authorize(
            ToolInvocation(
                request_id=request_id,
                agent_id=agent_id,
                tool_name=capability.policy_key,
                risk=selected_risk,
                resource=resource,
                provider=provider,
                untrusted_context=untrusted_context,
                approved=approved,
                cost_units=cost_units,
                argument_count=argument_count,
            )
        )
        audit = self._audit(
            request_id=request_id,
            agent_id=agent_id,
            server=server,
            server_id=server_id,
            tool_name=tool_name,
            risk=selected_risk,
            data_class=normalized_data_class,
            resource=resource,
            provider=provider,
            allowed=base.allowed,
            reason=base.reason,
            cost_units=cost_units,
            argument_count=argument_count,
            base_decision_id=base.audit.decision_id,
        )
        self._audit_events.append(audit)
        return BoundaryDecision(allowed=base.allowed, reason=base.reason, audit=audit)

    def enforce_tool(self, **kwargs: object) -> BoundaryAuditEvent:
        decision = self.authorize_tool(**kwargs)  # type: ignore[arg-type]
        if not decision.allowed:
            raise PermissionError(f"ORCHID_SECURITY_BOUNDARY_DENIED:{decision.reason}")
        return decision.audit

    def _precheck_decision(
        self,
        *,
        request_id: str,
        agent_id: str,
        server: ServerManifest | None,
        server_id: str,
        tool_name: str,
        risk: ActionRisk | None,
        data_class: DataClass,
        resource: str | None,
        provider: str | None,
        allowed: bool,
        reason: str,
        cost_units: int,
        argument_count: int,
    ) -> BoundaryDecision:
        audit = self._audit(
            request_id=request_id,
            agent_id=agent_id,
            server=server,
            server_id=server_id,
            tool_name=tool_name,
            risk=risk,
            data_class=data_class,
            resource=resource,
            provider=provider,
            allowed=allowed,
            reason=reason,
            cost_units=cost_units,
            argument_count=argument_count,
            base_decision_id=None,
        )
        self._audit_events.append(audit)
        return BoundaryDecision(allowed=allowed, reason=reason, audit=audit)

    @staticmethod
    def _normalize_data_class(value: DataClass | str) -> DataClass:
        try:
            return value if isinstance(value, DataClass) else DataClass(str(value))
        except ValueError as exc:
            raise ValueError("SECURITY_DATA_CLASS_INVALID") from exc

    @staticmethod
    def _audit(
        *,
        request_id: str,
        agent_id: str,
        server: ServerManifest | None,
        server_id: str,
        tool_name: str,
        risk: ActionRisk | None,
        data_class: DataClass,
        resource: str | None,
        provider: str | None,
        allowed: bool,
        reason: str,
        cost_units: int,
        argument_count: int,
        base_decision_id: str | None,
    ) -> BoundaryAuditEvent:
        safe_metadata = {
            "request_id": request_id,
            "agent_id": agent_id,
            "server_id": server_id,
            "transport": server.transport.value if server else None,
            "tool_name": tool_name,
            "risk": risk.value if risk else None,
            "data_class": data_class.value,
            "resource": resource,
            "provider": provider,
            "allowed": allowed,
            "reason": reason,
            "cost_units": cost_units,
            "argument_count": argument_count,
            "base_decision_id": base_decision_id,
        }
        canonical = json.dumps(
            safe_metadata,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )
        fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
        decision_id = hashlib.sha256(
            f"{request_id}|{server_id}|{tool_name}|{fingerprint}".encode()
        ).hexdigest()[:24]
        return BoundaryAuditEvent(
            decision_id=decision_id,
            base_decision_id=base_decision_id,
            request_id=request_id,
            agent_id=agent_id,
            server_id=server_id,
            transport=server.transport.value if server else None,
            tool_name=tool_name,
            risk=risk.value if risk else None,
            data_class=data_class.value,
            resource=resource,
            provider=provider,
            allowed=allowed,
            reason=reason,
            cost_units=cost_units,
            argument_count=argument_count,
            metadata_fingerprint=fingerprint,
        )


def build_orchid_continuum_security_boundary(
    *,
    enabled: bool | None = None,
    max_total_cost_units: int | None = None,
) -> OrchidSecurityBoundary:
    """Build the common boundary with least-privilege logical identities.

    Capability servers are registered by their owning runtime at composition
    time. No MCP server receives authority simply by being reachable.
    """

    if enabled is None:
        enabled = os.getenv("ORCHID_SECURITY_GATEWAY_ENABLED", "true").strip().casefold() not in {
            "0",
            "false",
            "no",
            "off",
        }
    if max_total_cost_units is None:
        max_total_cost_units = int(os.getenv("ORCHID_SECURITY_MAX_COST_UNITS", "100"))

    agents = {
        "calyx.agent": AgentPolicy(
            scopes=frozenset(
                {
                    "continuum.read",
                    "continuum.prepare",
                    "connector.read",
                    "model.synthesize",
                }
            )
        ),
        "calyx.connector_api": AgentPolicy(scopes=frozenset({"connector.read"})),
        "calyx.github_coding_agent": AgentPolicy(
            scopes=frozenset({"repo.inspect", "repo.proposal.write"})
        ),
        "calyx.model_runtime": AgentPolicy(scopes=frozenset({"model.synthesize"})),
    }
    return OrchidSecurityBoundary(
        agents=agents,
        enabled=enabled,
        max_total_cost_units=max_total_cost_units,
    )
