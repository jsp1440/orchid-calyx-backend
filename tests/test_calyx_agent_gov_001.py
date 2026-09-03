from __future__ import annotations

from app.calyx_orchestrator.task_intent import (
    AgentBehaviorLedger,
    BehaviorKind,
    BehaviorRequest,
    IntentDecision,
    LeastAgencyGuard,
    TaskIntentContract,
    canonical_task_fingerprint,
    duplicate_material_state,
)


BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40


def contract(**overrides: object) -> TaskIntentContract:
    values: dict[str, object] = {
        "task_id": "issue-1239",
        "mission_id": "CALYX-AGENT-GOV-001",
        "repository": "jsp1440/orchid-calyx-backend",
        "base_ref": "oc-autonomous-integration",
        "base_sha": BASE_SHA,
        "objective": "Implement least-agency governance",
        "allowed_paths": ("app/calyx_orchestrator/feature/", "tests/feature/"),
        "allowed_tools": ("github.repository.inspect", "github.coding_agent.dispatch"),
        "forbidden_actions": ("deploy production", "rotate secret", "disable security"),
        "validation_commands": ("pytest -q tests/feature",),
        "issue_numbers": (1239,),
        "max_cost_units": 5,
    }
    values.update(overrides)
    return TaskIntentContract(**values)  # type: ignore[arg-type]


def test_material_fingerprint_is_stable_for_identical_contract_and_head() -> None:
    first = canonical_task_fingerprint(contract(), head_sha=HEAD_SHA)
    second = canonical_task_fingerprint(contract(), head_sha=HEAD_SHA)
    assert first == second
    assert duplicate_material_state([first], second)


def test_material_fingerprint_changes_when_objective_changes() -> None:
    first = canonical_task_fingerprint(contract(), head_sha=HEAD_SHA)
    changed = canonical_task_fingerprint(contract(objective="Different authorized objective"), head_sha=HEAD_SHA)
    assert first != changed


def test_material_fingerprint_changes_when_head_changes() -> None:
    first = canonical_task_fingerprint(contract(), head_sha=HEAD_SHA)
    changed = canonical_task_fingerprint(contract(), head_sha="c" * 40)
    assert first != changed


def test_provider_identity_does_not_change_authority() -> None:
    request = BehaviorRequest(
        kind=BehaviorKind.TOOL_CALL,
        action="inspect repository",
        tool_name="github.repository.inspect",
    )
    claude = LeastAgencyGuard(contract()).record(
        request, agent_id="calyx.github_coding_agent", provider="claude"
    )
    codex = LeastAgencyGuard(contract()).record(
        request, agent_id="calyx.github_coding_agent", provider="openai-codex"
    )
    assert claude.allowed is True
    assert codex.allowed is True
    assert claude.reason == codex.reason == "ALLOW"


def test_external_content_then_privileged_write_is_blocked() -> None:
    guard = LeastAgencyGuard(contract())
    read = guard.record(
        BehaviorRequest(
            kind=BehaviorKind.EXTERNAL_CONTENT_READ,
            action="read issue body",
            resource="github:issue:1239",
            external_context=True,
        ),
        agent_id="calyx.github_coding_agent",
    )
    write = guard.record(
        BehaviorRequest(
            kind=BehaviorKind.FILE_WRITE,
            action="write feature",
            resource="app/calyx_orchestrator/feature/change.py",
        ),
        agent_id="calyx.github_coding_agent",
    )
    assert read.allowed is True
    assert write.allowed is False
    assert write.reason == "POST_INGESTION_PRIVILEGED_ACTION_BLOCKED"


def test_sensitive_read_then_outbound_action_is_blocked() -> None:
    guard = LeastAgencyGuard(contract())
    sensitive = guard.record(
        BehaviorRequest(
            kind=BehaviorKind.SENSITIVE_READ,
            action="read environment file",
            resource=".env",
        ),
        agent_id="calyx.github_coding_agent",
    )
    outbound = guard.record(
        BehaviorRequest(
            kind=BehaviorKind.OUTBOUND_NETWORK,
            action="call external endpoint",
            resource="https://example.invalid",
        ),
        agent_id="calyx.github_coding_agent",
    )
    assert sensitive.allowed is True
    assert outbound.allowed is False
    assert outbound.reason == "SENSITIVE_READ_TO_OUTBOUND_BLOCKED"


def test_protected_governance_path_write_is_blocked() -> None:
    event = LeastAgencyGuard(contract(allowed_paths=("app/calyx_orchestrator/",))).record(
        BehaviorRequest(
            kind=BehaviorKind.FILE_WRITE,
            action="modify security policy",
            resource="app/calyx_orchestrator/agent_security_gateway.py",
        ),
        agent_id="calyx.github_coding_agent",
    )
    assert event.allowed is False
    assert event.reason == "PROTECTED_GOVERNANCE_PATH_WRITE"


def test_self_authority_expansion_is_blocked() -> None:
    event = LeastAgencyGuard(contract()).record(
        BehaviorRequest(
            kind=BehaviorKind.AUTHORITY_CHANGE,
            action="grant self production scope",
        ),
        agent_id="calyx.github_coding_agent",
    )
    assert event.allowed is False
    assert event.decision == IntentDecision.BLOCK
    assert event.reason == "SELF_AUTHORITY_EXPANSION_PROHIBITED"


def test_safe_reversible_scoped_write_is_allowed_without_untrusted_context() -> None:
    event = LeastAgencyGuard(contract()).record(
        BehaviorRequest(
            kind=BehaviorKind.FILE_WRITE,
            action="write feature implementation",
            resource="app/calyx_orchestrator/feature/change.py",
        ),
        agent_id="calyx.github_coding_agent",
    )
    assert event.allowed is True
    assert event.reason == "ALLOW"


def test_path_outside_task_scope_is_blocked() -> None:
    event = LeastAgencyGuard(contract()).record(
        BehaviorRequest(
            kind=BehaviorKind.FILE_WRITE,
            action="write unrelated module",
            resource="app/routers/unrelated.py",
        ),
        agent_id="calyx.github_coding_agent",
    )
    assert event.allowed is False
    assert event.reason == "PATH_OUTSIDE_TASK_SCOPE"


def test_tool_outside_task_scope_is_blocked() -> None:
    event = LeastAgencyGuard(contract()).record(
        BehaviorRequest(
            kind=BehaviorKind.TOOL_CALL,
            action="invoke unknown tool",
            tool_name="shell.unbounded",
        ),
        agent_id="calyx.github_coding_agent",
    )
    assert event.allowed is False
    assert event.reason == "TOOL_OUTSIDE_TASK_SCOPE"


def test_forbidden_action_is_blocked() -> None:
    event = LeastAgencyGuard(contract()).record(
        BehaviorRequest(
            kind=BehaviorKind.TOOL_CALL,
            action="deploy production now",
            tool_name="github.repository.inspect",
        ),
        agent_id="calyx.github_coding_agent",
    )
    assert event.allowed is False
    assert event.reason == "FORBIDDEN_ACTION"


def test_cost_budget_is_fail_closed() -> None:
    guard = LeastAgencyGuard(contract(max_cost_units=1))
    first = guard.record(
        BehaviorRequest(
            kind=BehaviorKind.TOOL_CALL,
            action="inspect repository",
            tool_name="github.repository.inspect",
            cost_units=1,
        ),
        agent_id="calyx.github_coding_agent",
    )
    second = guard.record(
        BehaviorRequest(
            kind=BehaviorKind.TOOL_CALL,
            action="inspect repository again",
            tool_name="github.repository.inspect",
            cost_units=1,
        ),
        agent_id="calyx.github_coding_agent",
    )
    assert first.allowed is True
    assert second.allowed is False
    assert second.reason == "TASK_COST_LIMIT_EXCEEDED"


def test_ledger_records_safe_metadata_not_raw_arguments_or_prompts() -> None:
    ledger = AgentBehaviorLedger()
    guard = LeastAgencyGuard(contract(), ledger=ledger)
    event = guard.record(
        BehaviorRequest(
            kind=BehaviorKind.TOOL_CALL,
            action="inspect repository",
            resource="jsp1440/orchid-calyx-backend",
            tool_name="github.repository.inspect",
            metadata=(("validation", "required"),),
        ),
        agent_id="calyx.github_coding_agent",
        provider="claude",
    )
    payload = event.as_dict()
    text = repr(payload).lower()
    assert payload["task_id"] == "issue-1239"
    assert payload["mission_id"] == "CALYX-AGENT-GOV-001"
    assert payload["provider"] == "claude"
    assert "prompt" not in text
    assert "chain_of_thought" not in text
    assert "credential" not in text
    assert "arguments" not in text


def test_ledger_is_idempotent_by_event_id() -> None:
    ledger = AgentBehaviorLedger()
    guard = LeastAgencyGuard(contract(), ledger=ledger)
    request = BehaviorRequest(
        kind=BehaviorKind.TOOL_CALL,
        action="inspect repository",
        tool_name="github.repository.inspect",
    )
    event = guard.record(request, agent_id="calyx.github_coding_agent")
    ledger.append(event)
    assert len(ledger.events()) == 1
