from __future__ import annotations

import pytest

from app.calyx_agent.models import (
    ActionClass,
    RequestIntent,
    ToolDescriptor,
    ToolResult,
)
from app.calyx_agent.policy import classify_intent
from app.calyx_agent.service import CalyxAgentService
from app.calyx_agent.tools import AgentToolRegistry, default_tool_registry


def test_read_only_audit_executes_registered_tools():
    response = CalyxAgentService().handle(actor="owner", request_text="audit the brain")
    assert response.intent is RequestIntent.AUDIT
    assert response.approval_required is False
    assert len(response.tool_results) == 2
    assert all(step.status == "completed" for step in response.steps)


def test_build_request_prepares_without_mutating():
    response = CalyxAgentService().handle(
        actor="owner", request_text="implement a build to improve the graph"
    )
    assert response.intent is RequestIntent.PLAN_BUILD
    assert response.approval_required is False
    assert response.steps[-1].action_class is ActionClass.PREPARE_ONLY
    assert response.steps[-1].status == "planned"


def test_mutation_requires_explicit_approval():
    response = CalyxAgentService().handle(actor="owner", request_text="merge and deploy it")
    assert response.intent is RequestIntent.MUTATE
    assert response.approval_required is True
    assert response.steps[0].status == "blocked_pending_approval"
    assert response.tool_results == []


def test_scientific_publication_uses_separate_gate():
    response = CalyxAgentService().handle(
        actor="owner", request_text="publish this scientific conclusion"
    )
    assert response.intent is RequestIntent.SCIENTIFIC_PUBLICATION
    assert response.approval_required is True
    assert response.steps[0].action_class is ActionClass.SCIENTIFIC_APPROVAL


def test_tool_registry_refuses_non_read_only_execution():
    registry = AgentToolRegistry()
    registry.register(
        ToolDescriptor(
            "github.merge",
            "Merge pull request",
            ActionClass.OWNER_APPROVAL,
            "Consequential repository mutation.",
            writes_production=True,
        ),
        lambda _: ToolResult("github.merge", "unexpected", {}),
    )
    with pytest.raises(PermissionError, match="TOOL_REQUIRES_APPROVAL"):
        registry.execute("github.merge")


def test_default_registry_exposes_registered_read_only_tools():
    tools = default_tool_registry().describe()
    tool_ids = {item["tool_id"] for item in tools}
    assert tool_ids == {
        "brain.readiness",
        "continuum.build_inventory",
        "journalism.readiness",
        "mission_control.readiness",
    }
    assert all(item["action_class"] == "read_only" for item in tools)


def test_intent_classification():
    assert classify_intent("audit the graph") is RequestIntent.AUDIT
    assert classify_intent("monitor harvester health") is RequestIntent.MONITOR
    assert classify_intent("implement a fix") is RequestIntent.PLAN_BUILD
    assert classify_intent("deploy it") is RequestIntent.MUTATE
