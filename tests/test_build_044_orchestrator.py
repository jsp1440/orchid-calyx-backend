from runtime.autonomous_orchestrator import (
    DEFAULT_AGENTS,
    DEFAULT_TASKS,
    DefaultTaskExecutor,
    RISKY_ACTIONS,
)


def test_default_seed_includes_required_tasks():
    task_types = {task["task_type"] for task in DEFAULT_TASKS}

    assert "frontend_audit" in task_types
    assert "backend_health_check" in task_types
    assert "image_coverage_audit" in task_types
    assert "relationship_data_audit" in task_types


def test_default_seed_includes_enabled_safe_agents():
    enabled_agents = [agent for agent in DEFAULT_AGENTS if agent["enabled"]]
    allowed = {task_type for agent in enabled_agents for task_type in agent["allowed_task_types"]}

    assert "frontend_audit" in allowed
    assert "backend_health_check" in allowed
    assert "image_coverage_audit" in allowed
    assert "relationship_data_audit" in allowed


def test_executor_completes_backend_health_check():
    executor = DefaultTaskExecutor()
    task = {
        "task_type": "backend_health_check",
        "payload": {"checks": ["database_schema"]},
    }
    agent = {"agent_name": "Calyx Auditor"}

    result = executor.execute(task, agent)

    assert result.status == "completed"
    assert result.evaluation_result == "pass"
    assert result.result["changed"] == []
    assert result.observations[0]["action"] == "inspected"


def test_executor_routes_coverage_audits_to_review_until_sources_exist():
    executor = DefaultTaskExecutor()
    task = {
        "task_type": "image_coverage_audit",
        "payload": {"target_domain": "orchid_images"},
    }
    agent = {"agent_name": "Continuum Data Cartographer"}

    result = executor.execute(task, agent)

    assert result.status == "needs_review"
    assert result.evaluation_result == "needs_review"
    assert "next_action" in result.result


def test_risky_actions_are_approval_gated():
    executor = DefaultTaskExecutor()

    for action in RISKY_ACTIONS:
        task = {
            "task_type": action,
            "payload": {"action": action},
        }
        agent = {"agent_name": "Release Steward"}
        result = executor.execute(task, agent)

        assert result.status == "needs_review"
        assert result.evaluation_result == "needs_review"
        assert result.result["requires_human_approval"] is True
        assert result.observations[0]["event_type"] == "approval_gate"
