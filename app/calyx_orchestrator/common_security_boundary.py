from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

from .agent_security_gateway import (
    ActionRisk,
    AgentSecurityGateway,
    ToolInvocation,
)


class TransportClass(StrEnum):
    INTERNAL = "internal"
    CONNECTOR = "connector"
    MCP = "mcp"
    PROVIDER = "provider"


class DataClass(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE_LOCALITY = "sensitive_locality"
    CREDENTIAL = "credential"


@dataclass(frozen=True, slots=True)
class CapabilityTool:
    tool_name: str
    risk: ActionRisk
    allowed_data_classes: frozenset[DataClass]


@dataclass(frozen=True, slots=True)
class CapabilityManifest:
    server_id: str
    transport: TransportClass
    tools: Mapping[str, CapabilityTool]
    enabled: bool = True


@dataclass(frozen=True, slots=True)
class BoundaryInvocation:
    request_id: str
    agent_id: str
    server_id: str
    tool_name: str
    data_class: DataClass
    resource: str | None = None
    provider: str | None = None
    untrusted_context: bool = False
    approved: bool = False
    cost_units: int = 0
    argument_count: int = 0


@dataclass(frozen=True, slots=True)
class BoundaryAuditEvent:
    decision_id: str
    request_id: str
    agent_id: str
    server_id: str
    tool_name: str
    transport: str | None
    data_class: str
    provider: str | None
    allowed: bool
    reason: str
    metadata_fingerprint: str

    def as_dict(self) -> dict[str, object]:
        return {
            "decision_id": self.decision_id,
            "request_id": self.request_id,
            "agent_id": self.agent_id,
            "server_id": self.server_id,
            "tool_name": self.tool_name,
            "transport": self.transport,
            "data_class": self.data_class,
            "provider": self.provider,
            "allowed": self.allowed,
            "reason": self.reason,
            "metadata_fingerprint": self.metadata_fingerprint,
        }


_ResultT = TypeVar("_ResultT")


class CommonSecurityBoundary:
    """Provider-neutral deny-by-default boundary for outbound execution surfaces.

    Payload values and credentials are deliberately absent from every input that
    may be persisted to the boundary audit log. Provider identity is provenance
    only: authorization is determined by the manifest and Agent Security Gateway.
    """

    def __init__(
        self,
        *,
        manifests: Mapping[str, CapabilityManifest],
        gateway: AgentSecurityGateway,
        enabled: bool = True,
    ) -> None:
        self._manifests = dict(manifests)
        self._gateway = gateway
        self._enabled = enabled
        self._audit_events: list[BoundaryAuditEvent] = []

    def audit_events(self) -> tuple[BoundaryAuditEvent, ...]:
        return tuple(self._audit_events)

    def execute(
        self,
        invocation: BoundaryInvocation,
        handler: Callable[[], _ResultT],
    ) -> _ResultT:
        manifest, tool, reason = self._manifest_decision(invocation)
        if reason != "ALLOW":
            self._record(invocation, manifest=manifest, allowed=False, reason=reason)
            raise PermissionError(f"COMMON_SECURITY_BOUNDARY_DENIED:{reason}")

        assert manifest is not None
        assert tool is not None
        try:
            self._gateway.enforce(
                ToolInvocation(
                    request_id=invocation.request_id,
                    agent_id=invocation.agent_id,
                    tool_name=tool.tool_name,
                    risk=tool.risk,
                    resource=invocation.resource,
                    provider=invocation.provider,
                    untrusted_context=invocation.untrusted_context,
                    approved=invocation.approved,
                    cost_units=invocation.cost_units,
                    argument_count=invocation.argument_count,
                )
            )
        except PermissionError as exc:
            reason = str(exc).rsplit(":", maxsplit=1)[-1]
            self._record(invocation, manifest=manifest, allowed=False, reason=reason)
            raise

        self._record(invocation, manifest=manifest, allowed=True, reason="ALLOW")
        return handler()

    def _manifest_decision(
        self,
        invocation: BoundaryInvocation,
    ) -> tuple[CapabilityManifest | None, CapabilityTool | None, str]:
        if not self._enabled:
            return None, None, "BOUNDARY_KILL_SWITCH"
        manifest = self._manifests.get(invocation.server_id)
        if manifest is None:
            return None, None, "SERVER_NOT_DECLARED"
        if manifest.server_id != invocation.server_id:
            return manifest, None, "SERVER_IDENTITY_MISMATCH"
        if not manifest.enabled:
            return manifest, None, "SERVER_DISABLED"
        tool = manifest.tools.get(invocation.tool_name)
        if tool is None:
            return manifest, None, "TOOL_NOT_DECLARED"
        if tool.tool_name != invocation.tool_name:
            return manifest, tool, "TOOL_IDENTITY_MISMATCH"
        if invocation.data_class not in tool.allowed_data_classes:
            return manifest, tool, "DATA_CLASS_NOT_ALLOWED"
        return manifest, tool, "ALLOW"

    def _record(
        self,
        invocation: BoundaryInvocation,
        *,
        manifest: CapabilityManifest | None,
        allowed: bool,
        reason: str,
    ) -> None:
        safe_metadata = {
            "request_id": invocation.request_id,
            "agent_id": invocation.agent_id,
            "server_id": invocation.server_id,
            "tool_name": invocation.tool_name,
            "transport": manifest.transport.value if manifest else None,
            "data_class": invocation.data_class.value,
            "provider": invocation.provider,
            "allowed": allowed,
            "reason": reason,
        }
        canonical = json.dumps(safe_metadata, sort_keys=True, separators=(",", ":"))
        fingerprint = hashlib.sha256(canonical.encode()).hexdigest()
        decision_id = hashlib.sha256(
            f"{invocation.request_id}|{fingerprint}".encode()
        ).hexdigest()[:24]
        self._audit_events.append(
            BoundaryAuditEvent(
                decision_id=decision_id,
                request_id=invocation.request_id,
                agent_id=invocation.agent_id,
                server_id=invocation.server_id,
                tool_name=invocation.tool_name,
                transport=manifest.transport.value if manifest else None,
                data_class=invocation.data_class.value,
                provider=invocation.provider,
                allowed=allowed,
                reason=reason,
                metadata_fingerprint=fingerprint,
            )
        )
