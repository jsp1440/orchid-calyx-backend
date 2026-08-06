from __future__ import annotations

import pytest

from app.calyx_orchestrator.scheduler import (
    DependencyScheduler,
    ScheduledJob,
    ScheduledState,
    SchedulerLimits,
)


def job(key: str, **overrides) -> ScheduledJob:
    values = {
        "job_key": key,
        "role_key": "brain_engineer",
        "architecture": "brain",
        "repository": "repo-a",
        "priority": 100,
        "created_order": 0,
    }
    values.update(overrides)
    return ScheduledJob(**values)


def decision(snapshot, key: str):
    return next(item for item in snapshot.decisions if item.job_key == key)


def test_critical_path_then_priority_then_creation_order_is_deterministic():
    jobs = (
        job("root-a", priority=20, created_order=2),
        job("root-b", priority=10, created_order=1),
        job("middle"),
        job("report"),
    )
    dependencies = (("root-a", "middle"), ("middle", "report"))
    first = DependencyScheduler().project(jobs=jobs, dependencies=dependencies)
    second = DependencyScheduler().project(jobs=tuple(reversed(jobs)), dependencies=tuple(reversed(dependencies)))

    assert first.runnable_order == ("root-a", "root-b")
    assert second.runnable_order == first.runnable_order
    assert decision(first, "root-a").critical_path_depth == 2
    assert decision(first, "root-b").critical_path_depth == 0


def test_prerequisite_waiting_and_failure_are_distinguished():
    jobs = (
        job("waiting-parent"),
        job("failed-parent", state=ScheduledState.BLOCKED, outcome="BLOCKED"),
        job("waiting-child"),
        job("failed-child"),
    )
    snapshot = DependencyScheduler().project(
        jobs=jobs,
        dependencies=(("waiting-parent", "waiting-child"), ("failed-parent", "failed-child")),
    )
    assert decision(snapshot, "waiting-child").code == "WAITING_FOR_PREREQUISITES"
    assert decision(snapshot, "waiting-child").blocked_by == ("waiting-parent",)
    assert decision(snapshot, "failed-child").code == "PREREQUISITE_FAILED"
    assert decision(snapshot, "failed-child").blocked_by == ("failed-parent",)


def test_successful_prerequisite_releases_child():
    jobs = (
        job("source", state=ScheduledState.COMPLETED, outcome="DELIVERED"),
        job("child"),
    )
    snapshot = DependencyScheduler().project(jobs=jobs, dependencies=(("source", "child"),))
    assert snapshot.runnable_order == ("child",)
    assert decision(snapshot, "child").runnable is True


def test_capacity_is_applied_in_deterministic_order():
    jobs = (
        job("running", state=ScheduledState.RUNNING),
        job("first", priority=1),
        job("second", priority=2),
    )
    snapshot = DependencyScheduler().project(
        jobs=jobs,
        dependencies=(),
        limits=SchedulerLimits(
            max_global_running=2,
            max_architecture_running=2,
            max_role_running=2,
            max_repository_running=2,
        ),
    )
    assert snapshot.runnable_order == ("first",)
    assert decision(snapshot, "second").code == "GLOBAL_CAPACITY_REACHED"


def test_architecture_role_and_repository_limits_fail_closed():
    running = job("running", state=ScheduledState.RUNNING)
    architecture_blocked = job("architecture-blocked", role_key="other", repository="repo-b")
    snapshot = DependencyScheduler().project(
        jobs=(running, architecture_blocked),
        dependencies=(),
        limits=SchedulerLimits(max_architecture_running=1),
    )
    assert decision(snapshot, "architecture-blocked").code == "ARCHITECTURE_CAPACITY_REACHED"

    role_blocked = job("role-blocked", architecture="atlas", repository="repo-b")
    snapshot = DependencyScheduler().project(
        jobs=(running, role_blocked),
        dependencies=(),
        limits=SchedulerLimits(max_architecture_running=3, max_role_running=1),
    )
    assert decision(snapshot, "role-blocked").code == "ROLE_CAPACITY_REACHED"

    repository_blocked = job("repository-blocked", architecture="atlas", role_key="other")
    snapshot = DependencyScheduler().project(
        jobs=(running, repository_blocked),
        dependencies=(),
        limits=SchedulerLimits(max_architecture_running=3, max_role_running=2, max_repository_running=1),
    )
    assert decision(snapshot, "repository-blocked").code == "REPOSITORY_CAPACITY_REACHED"


def test_missing_self_and_cyclic_dependencies_are_rejected():
    scheduler = DependencyScheduler()
    with pytest.raises(ValueError, match="SCHEDULE_DEPENDENCY_JOB_NOT_FOUND"):
        scheduler.project(jobs=(job("one"),), dependencies=(("missing", "one"),))
    with pytest.raises(ValueError, match="SCHEDULE_SELF_DEPENDENCY"):
        scheduler.project(jobs=(job("one"),), dependencies=(("one", "one"),))
    with pytest.raises(ValueError, match="CYCLIC_SCHEDULE_DEPENDENCY"):
        scheduler.project(jobs=(job("one"), job("two")), dependencies=(("one", "two"), ("two", "one")))
