from datetime import datetime, timezone

from runtime.continuous_governed_cycle import ContinuousGovernedCycle
from runtime.draft_engineering_executor import EngineeringTask
from runtime.github_connector_dispatcher import AuditedGitHubDispatcher
from runtime.live_activation_bridge import ActivationPolicy, LiveActivationBridge
from runtime.reactive_scheduler import ReactiveScheduler, SchedulerPolicy

REPOSITORY = "jsp1440/orchid-calyx-backend"


def build_cycle() -> ContinuousGovernedCycle:
    scheduler = ReactiveScheduler(
        SchedulerPolicy(enabled=True, owner_approved=True, interval_minutes=60)
    )
    bridge = LiveActivationBridge(
        ActivationPolicy(
            enabled=True,
            owner_approved=True,
            repository_allowlist=(REPOSITORY,),
        ),
        scheduler,
    )
    dispatcher = AuditedGitHubDispatcher((REPOSITORY,))
    return ContinuousGovernedCycle(scheduler, bridge, dispatcher)


def approved_task() -> EngineeringTask:
    return EngineeringTask(
        task_key="cycle:bounded-fix",
        title="Prepare bounded runtime fix",
        repository=REPOSITORY,
        objective="Correct one approved low-risk defect.",
        allowed_paths=("runtime", "tests"),
        risk="low",
        owner_approved=True,
    )


def test_cycle_creates_branch_and_draft_pr_once():
    calls = []
    cycle = build_cycle()
    result = cycle.run_if_due(
        now=datetime(2026, 8, 2, tzinfo=timezone.utc),
        select_task=approved_task,
        changed_paths=lambda task: ("runtime/example.py",),
        validation_results=lambda task: {
            "ruff": True,
            "pytest": True,
            "diff_check": True,
        },
        connector_executor=lambda command: calls.append(command.operation)
        or {"operation": command.operation},
    )
    assert result.executed is True
    assert calls == ["create_branch", "create_draft_pull_request"]
    assert len(result.receipts) == 2


def test_cycle_is_interval_bounded():
    cycle = build_cycle()
    now = datetime(2026, 8, 2, tzinfo=timezone.utc)
    first = cycle.run_if_due(
        now=now,
        select_task=approved_task,
        changed_paths=lambda task: ("runtime/example.py",),
        validation_results=lambda task: {
            "ruff": True,
            "pytest": True,
            "diff_check": True,
        },
        connector_executor=lambda command: {"operation": command.operation},
    )
    second = cycle.run_if_due(
        now=now,
        select_task=approved_task,
        changed_paths=lambda task: ("runtime/example.py",),
        validation_results=lambda task: {
            "ruff": True,
            "pytest": True,
            "diff_check": True,
        },
        connector_executor=lambda command: {"operation": command.operation},
    )
    assert first.executed is True
    assert second.executed is False


def test_cycle_reports_consequential_actions_disabled():
    status = build_cycle().status()
    assert status["automatic_merge"] is False
    assert status["automatic_deploy"] is False
    assert status["scientific_publication"] is False
    assert status["production_deletion"] is False
    assert status["external_communication"] is False
