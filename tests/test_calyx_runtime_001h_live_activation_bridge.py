from datetime import UTC, datetime

import pytest

from runtime.draft_engineering_executor import EngineeringTask
from runtime.live_activation_bridge import ActivationPolicy, LiveActivationBridge
from runtime.reactive_scheduler import ReactiveScheduler, SchedulerPolicy

REPOSITORY = "jsp1440/orchid-calyx-backend"


def approved_task(**overrides):
    values = {
        "task_key": "activation:bounded-fix-1",
        "title": "Prepare bounded runtime fix",
        "repository": REPOSITORY,
        "objective": "Correct one approved low-risk defect.",
        "allowed_paths": ("runtime", "tests"),
        "risk": "low",
        "owner_approved": True,
    }
    values.update(overrides)
    return EngineeringTask(**values)


def scheduler():
    return ReactiveScheduler(
        SchedulerPolicy(enabled=True, owner_approved=True, interval_minutes=60)
    )


def test_bridge_fails_closed_without_activation_approval():
    bridge = LiveActivationBridge(
        ActivationPolicy(
            enabled=True,
            owner_approved=False,
            repository_allowlist=(REPOSITORY,),
        ),
        scheduler(),
    )
    with pytest.raises(PermissionError):
        bridge.prepare_draft_command(
            approved_task(),
            ("runtime/example.py",),
            {"ruff": True, "pytest": True, "diff_check": True},
        )


def test_bridge_rejects_unapproved_repository():
    bridge = LiveActivationBridge(
        ActivationPolicy(
            enabled=True,
            owner_approved=True,
            repository_allowlist=(REPOSITORY,),
        ),
        scheduler(),
    )
    with pytest.raises(PermissionError):
        bridge.prepare_draft_command(
            approved_task(repository="other/repository"),
            ("runtime/example.py",),
            {"ruff": True, "pytest": True, "diff_check": True},
        )


def test_bridge_prepares_draft_only_connector_command():
    bridge = LiveActivationBridge(
        ActivationPolicy(
            enabled=True,
            owner_approved=True,
            repository_allowlist=(REPOSITORY,),
        ),
        scheduler(),
    )
    command = bridge.prepare_draft_command(
        approved_task(),
        ("runtime/example.py", "tests/test_example.py"),
        {"ruff": True, "pytest": True, "diff_check": True},
    )
    assert command.operation == "create_draft_pull_request"
    assert command.draft is True
    assert command.expected_base == "main"
    assert bridge.status()["automatic_merge"] is False
    assert bridge.status()["automatic_deploy"] is False


def test_bridge_preserves_executor_scope_and_validation_guards():
    bridge = LiveActivationBridge(
        ActivationPolicy(
            enabled=True,
            owner_approved=True,
            repository_allowlist=(REPOSITORY,),
        ),
        scheduler(),
    )
    with pytest.raises(PermissionError):
        bridge.prepare_draft_command(
            approved_task(),
            ("render.yaml",),
            {"ruff": True, "pytest": True, "diff_check": True},
        )
    with pytest.raises(RuntimeError):
        bridge.prepare_draft_command(
            approved_task(),
            ("runtime/example.py",),
            {"ruff": True, "pytest": False, "diff_check": True},
        )


def test_scheduler_remains_owner_gated_and_interval_bounded():
    active_scheduler = scheduler()
    now = datetime(2026, 8, 2, tzinfo=UTC)
    result = active_scheduler.run_if_due(lambda limit: {"limit": limit}, now)
    assert result["executed"] is True
    repeated = active_scheduler.run_if_due(lambda limit: {"limit": limit}, now)
    assert repeated["executed"] is False
