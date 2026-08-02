import pytest

from runtime.draft_engineering_executor import (
    EngineeringTask,
    GovernedDraftEngineeringExecutor,
)


def approved_task(**overrides):
    values = {
        "task_key": "self-audit:ci-repair-17",
        "title": "Repair focused CI failure",
        "repository": "jsp1440/orchid-calyx-backend",
        "objective": "Correct one bounded validation defect.",
        "allowed_paths": ("runtime", "tests"),
        "risk": "low",
        "owner_approved": True,
    }
    values.update(overrides)
    return EngineeringTask(**values)


def test_executor_requires_owner_approval_and_low_risk():
    executor = GovernedDraftEngineeringExecutor()
    with pytest.raises(PermissionError):
        executor.plan(approved_task(owner_approved=False))
    with pytest.raises(PermissionError):
        executor.plan(approved_task(risk="medium"))


def test_plan_is_bounded_draft_only_and_prohibits_merge_and_deploy():
    plan = GovernedDraftEngineeringExecutor().plan(approved_task())
    assert plan.draft_only is True
    assert plan.branch_name.startswith("calyx/draft/")
    assert "merge" in plan.prohibited_actions
    assert "deploy" in plan.prohibited_actions


def test_changed_paths_must_remain_inside_approved_scope():
    executor = GovernedDraftEngineeringExecutor()
    plan = executor.plan(approved_task())
    executor.validate_changed_paths(
        plan, ("runtime/example.py", "tests/test_example.py")
    )
    with pytest.raises(PermissionError):
        executor.validate_changed_paths(plan, ("render.yaml",))


def test_failed_validation_prevents_draft_pr_package():
    executor = GovernedDraftEngineeringExecutor()
    task = approved_task()
    plan = executor.plan(task)
    with pytest.raises(RuntimeError):
        executor.build_draft_pr_package(
            task,
            plan,
            ("runtime/example.py",),
            {"ruff": True, "pytest": False},
        )


def test_passing_validation_creates_draft_pr_package_with_evidence():
    executor = GovernedDraftEngineeringExecutor()
    task = approved_task()
    plan = executor.plan(task)
    package = executor.build_draft_pr_package(
        task,
        plan,
        ("runtime/example.py", "tests/test_example.py"),
        {"ruff": True, "pytest": True, "diff_check": True},
    )
    assert package.draft is True
    assert package.base_branch == "main"
    assert package.evidence["task_key"] == task.task_key
    assert package.evidence["validation_results"]["pytest"] is True


def test_path_traversal_is_rejected():
    with pytest.raises(ValueError):
        GovernedDraftEngineeringExecutor().plan(
            approved_task(allowed_paths=("runtime/../secrets",))
        )
