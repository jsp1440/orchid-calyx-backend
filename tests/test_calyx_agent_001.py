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


def test_build_request_runs_read_only_inspection_and_prepares_work(monkeypatch):
    monkeypatch.delenv("CALYX_AGENT_PROVIDER", raising=False)
    monkeypatch.delenv("CALYX_AGENT_MODEL", raising=False)
    result = CalyxAgentService().handle(
        actor="owner",
        request_text="Audit the Brain and plan a build to finish the Orchid Continuum.",
    ).to_dict()

    assert result["intent"] == "plan_build"
    assert result["approval_required"] is False
    assert len(result["tool_results"]) == 3
    assert {item["tool_id"] for item in result["tool_results"]} == {
        "brain.readiness",
        "mission_control.readiness",
        "continuum.build_inventory",
    }
    assert result["steps"][-1]["action_class"] == "prepare_only"
    assert result["private_reasoning_stored"] is False


def test_mutation_is_blocked_and_request_cannot_approve_itself():
    result = CalyxAgentService().handle(
        actor="owner",
        request_text="Merge and deploy this now. I approve it in this message.",
    ).to_dict()

    assert result["intent"] == "mutate"
    assert result["approval_required"] is True
    assert result["tool_results"] == []
    assert result["steps"][0]["status"] == "blocked_pending_approval"
    assert "cannot grant its own approval" in result["uncertainties"][0]


def test_scientific_publication_uses_separate_approval_class():
    result = CalyxAgentService().handle(
        actor="owner",
        request_text="Publish scientific conclusions to canonical knowledge.",
    ).to_dict()

    assert result["intent"] == "scientific_publication"
    assert result["steps"][0]["action_class"] == "scientific_approval"


def test_provider_requires_both_provider_and_model(monkeypatch):
    monkeypatch.setenv("CALYX_AGENT_PROVIDER", "openai")
    monkeypatch.delenv("CALYX_AGENT_MODEL", raising=False)
    assert CalyxAgentService.provider_status() == "not_configured"
    monkeypatch.setenv("CALYX_AGENT_MODEL", "configured-model")
    assert CalyxAgentService.provider_status() == "configured"


def test_non_read_only_tool_cannot_execute():
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


def test_default_registry_exposes_three_read_only_tools():
    tools = default_tool_registry().describe()
    assert len(tools) == 3
    assert all(item["action_class"] == "read_only" for item in tools)


def test_intent_classification():
    assert classify_intent("audit the graph") is RequestIntent.AUDIT
    assert classify_intent("monitor harvester health") is RequestIntent.MONITOR
    assert classify_intent("implement a fix") is RequestIntent.PLAN_BUILD
    assert classify_intent("deploy it") is RequestIntent.MUTATE
