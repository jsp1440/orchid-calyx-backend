from __future__ import annotations

import pytest

from app.calyx_orchestrator.agent_security_gateway import (
    ActionRisk,
    AgentPolicy,
    AgentSecurityGateway,
    GatewayPolicy,
    ToolPolicy,
)
from app.calyx_orchestrator.common_security_boundary import (
    BoundaryInvocation,
    CapabilityManifest,
    CapabilityTool,
    CommonSecurityBoundary,
    DataClass,
    TransportClass,
)


def _gateway(*, risk: ActionRisk = ActionRisk.READ) -> AgentSecurityGateway:
    return AgentSecurityGateway(
        GatewayPolicy(
            agents={"calyx": AgentPolicy(scopes=frozenset({"science.read"}))},
            tools={
                "science.lookup": ToolPolicy(
                    required_scopes=frozenset({"science.read"}),
                    allowed_risks=frozenset({risk}),
                    max_cost_units=1,
                )
            },
        )
    )


def _manifest(
    *,
    server_id: str = "internal.science",
    transport: TransportClass = TransportClass.INTERNAL,
    risk: ActionRisk = ActionRisk.READ,
    enabled: bool = True,
) -> CapabilityManifest:
    return CapabilityManifest(
        server_id=server_id,
        transport=transport,
        enabled=enabled,
        tools={
            "science.lookup": CapabilityTool(
                tool_name="science.lookup",
                risk=risk,
                allowed_data_classes=frozenset({DataClass.PUBLIC, DataClass.INTERNAL}),
            )
        },
    )


def _invocation(**changes: object) -> BoundaryInvocation:
    values: dict[str, object] = {
        "request_id": "req-1",
        "agent_id": "calyx",
        "server_id": "internal.science",
        "tool_name": "science.lookup",
        "data_class": DataClass.PUBLIC,
        "resource": None,
        "provider": None,
        "cost_units": 0,
    }
    values.update(changes)
    return BoundaryInvocation(**values)  # type: ignore[arg-type]


def _boundary(
    *,
    manifest: CapabilityManifest | None = None,
    gateway: AgentSecurityGateway | None = None,
) -> CommonSecurityBoundary:
    selected = manifest or _manifest()
    return CommonSecurityBoundary(
        manifests={"internal.science": selected},
        gateway=gateway or _gateway(),
    )


def test_undeclared_server_denied_before_handler() -> None:
    boundary = _boundary()
    called = False

    def handler() -> str:
        nonlocal called
        called = True
        return "should-not-run"

    with pytest.raises(PermissionError, match="SERVER_NOT_DECLARED"):
        boundary.execute(_invocation(server_id="connector.unknown"), handler)

    assert called is False


def test_undeclared_tool_denied_before_handler() -> None:
    boundary = _boundary()
    called = False

    def handler() -> None:
        nonlocal called
        called = True

    with pytest.raises(PermissionError, match="TOOL_NOT_DECLARED"):
        boundary.execute(_invocation(tool_name="science.mutate"), handler)

    assert called is False


def test_server_identity_mismatch_denied() -> None:
    boundary = _boundary(manifest=_manifest(server_id="internal.other"))

    with pytest.raises(PermissionError, match="SERVER_IDENTITY_MISMATCH"):
        boundary.execute(_invocation(), lambda: None)


def test_disallowed_data_class_denied() -> None:
    boundary = _boundary()

    with pytest.raises(PermissionError, match="DATA_CLASS_NOT_ALLOWED"):
        boundary.execute(
            _invocation(data_class=DataClass.CREDENTIAL),
            lambda: None,
        )


def test_manifested_read_only_internal_tool_executes() -> None:
    boundary = _boundary()

    assert boundary.execute(_invocation(), lambda: "ok") == "ok"
    assert boundary.audit_events()[-1].allowed is True


def test_manifested_read_only_connector_executes() -> None:
    manifest = _manifest(transport=TransportClass.CONNECTOR)
    boundary = _boundary(manifest=manifest)

    assert boundary.execute(_invocation(), lambda: "connector-ok") == "connector-ok"
    assert boundary.audit_events()[-1].transport == "connector"


def test_disabled_mcp_registration_fails_closed() -> None:
    manifest = _manifest(transport=TransportClass.MCP, enabled=False)
    boundary = _boundary(manifest=manifest)

    with pytest.raises(PermissionError, match="SERVER_DISABLED"):
        boundary.execute(_invocation(), lambda: None)


def test_untrusted_context_cannot_trigger_mutation() -> None:
    manifest = _manifest(risk=ActionRisk.WRITE)
    gateway = _gateway(risk=ActionRisk.WRITE)
    boundary = _boundary(manifest=manifest, gateway=gateway)

    with pytest.raises(PermissionError, match="UNTRUSTED_CONTEXT_MUTATION_PROHIBITED"):
        boundary.execute(
            _invocation(untrusted_context=True),
            lambda: None,
        )


def test_privileged_action_still_requires_gateway_approval() -> None:
    manifest = _manifest(risk=ActionRisk.PRODUCTION)
    gateway = _gateway(risk=ActionRisk.PRODUCTION)
    boundary = _boundary(manifest=manifest, gateway=gateway)

    with pytest.raises(PermissionError, match="EXPLICIT_APPROVAL_REQUIRED"):
        boundary.execute(_invocation(), lambda: None)


def test_provider_substitution_does_not_change_authorization() -> None:
    first = _boundary()
    second = _boundary()

    assert first.execute(_invocation(provider="provider-a"), lambda: "ok") == "ok"
    assert second.execute(_invocation(provider="provider-b"), lambda: "ok") == "ok"
    assert first.audit_events()[-1].allowed == second.audit_events()[-1].allowed


def test_audit_is_metadata_only_and_contains_required_identity() -> None:
    boundary = _boundary()
    boundary.execute(
        _invocation(provider="provider-a", argument_count=3),
        lambda: "payload-secret-never-persisted",
    )

    audit = boundary.audit_events()[-1].as_dict()
    assert audit["server_id"] == "internal.science"
    assert audit["tool_name"] == "science.lookup"
    assert audit["data_class"] == "public"
    assert audit["provider"] == "provider-a"
    assert "payload" not in audit
    assert "credential" not in audit
    assert "argument_count" not in audit
