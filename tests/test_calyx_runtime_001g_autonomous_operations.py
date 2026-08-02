from datetime import datetime, timezone

import pytest

from runtime.draft_engineering_executor import (
    EngineeringTask,
    GovernedDraftEngineeringExecutor,
)
from runtime.reactive_scheduler import ReactiveScheduler, SchedulerPolicy
from runtime.self_audit import AuditSignal, SelfAuditEngine
from runtime.self_audit_queue_bridge import report_to_tasks


def approved_engineering_task() -> EngineeringTask:
    return EngineeringTask(
        task_key="self-audit:focused-runtime-repair",
        title="Repair focused runtime defect",
        repository="jsp1440/orchid-calyx-backend",
        objective="Prepare one bounded, tested draft repair.",
        allowed_paths=("runtime", "tests"),
        risk="low",
        owner_approved=True,
    )


def test_complete_governed_cycle_prepares_draft_only_work():
    report = SelfAuditEngine().audit(
        [
            AuditSignal(
                source="github",
                check="focused_ci_failure",
                status="failed",
                severity="high",
                confidence=1.0,
            )
        ]
    )
    queued = report_to_tasks(report, limit=1)
    assert len(queued) == 1
    assert queued[0]["payload"]["execution_mode"] == "draft_only"

    scheduler = ReactiveScheduler(
        SchedulerPolicy(
            enabled=True,
            owner_approved=True,
            interval_minutes=60,
            max_tasks_per_cycle=1,
        )
    )
    scheduled = scheduler.run_if_due(
        lambda limit: {"selected_tasks": queued[:limit]},
        datetime(2026, 8, 2, tzinfo=timezone.utc),
    )
    assert scheduled["executed"] is True

    executor = GovernedDraftEngineeringExecutor()
    task = approved_engineering_task()
    plan = executor.plan(task)
    package = executor.build_draft_pr_package(
        task,
        plan,
        ("runtime/focused_repair.py", "tests/test_focused_repair.py"),
        {"ruff": True, "pytest": True, "diff_check": True},
    )
    assert package.draft is True
    assert package.base_branch == "main"
    assert "merge" in package.evidence["prohibited_actions"]
    assert "deploy" in package.evidence["prohibited_actions"]


def test_cycle_fails_closed_without_owner_approval():
    scheduler = ReactiveScheduler(
        SchedulerPolicy(enabled=True, owner_approved=False, max_tasks_per_cycle=1)
    )
    result = scheduler.run_if_due(lambda limit: {"selected": limit})
    assert result["executed"] is False

    with pytest.raises(PermissionError):
        GovernedDraftEngineeringExecutor().plan(
            EngineeringTask(
                task_key="unapproved",
                title="Unapproved",
                repository="jsp1440/orchid-calyx-backend",
                objective="Must not run.",
                allowed_paths=("runtime",),
                risk="low",
                owner_approved=False,
            )
        )


def test_scope_escape_and_failed_validation_block_pr_preparation():
    executor = GovernedDraftEngineeringExecutor()
    task = approved_engineering_task()
    plan = executor.plan(task)

    with pytest.raises(PermissionError):
        executor.build_draft_pr_package(
            task,
            plan,
            ("render.yaml",),
            {"ruff": True, "pytest": True, "diff_check": True},
        )

    with pytest.raises(RuntimeError):
        executor.build_draft_pr_package(
            task,
            plan,
            ("runtime/focused_repair.py",),
            {"ruff": True, "pytest": False, "diff_check": True},
        )


def test_consequential_actions_remain_prohibited():
    plan = GovernedDraftEngineeringExecutor().plan(approved_engineering_task())
    required = {
        "merge",
        "deploy",
        "publish_scientific_knowledge",
        "delete_production_data",
        "send_external_communication",
        "change_permissions",
        "change_governance",
    }
    assert required.issubset(set(plan.prohibited_actions))
