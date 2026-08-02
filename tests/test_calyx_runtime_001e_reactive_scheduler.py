from datetime import datetime, timedelta, timezone

import pytest

from runtime.reactive_scheduler import ReactiveScheduler, SchedulerPolicy


def test_scheduler_fails_closed_without_owner_approval():
    scheduler = ReactiveScheduler(SchedulerPolicy(enabled=True, owner_approved=False))
    called = False

    def cycle(limit):
        nonlocal called
        called = True
        return {"limit": limit}

    result = scheduler.run_if_due(cycle)
    assert result["executed"] is False
    assert called is False


def test_approved_scheduler_runs_bounded_read_only_cycle_when_due():
    now = datetime(2026, 8, 2, tzinfo=timezone.utc)
    scheduler = ReactiveScheduler(
        SchedulerPolicy(enabled=True, owner_approved=True, max_tasks_per_cycle=7)
    )
    result = scheduler.run_if_due(lambda limit: {"prepared_tasks": limit}, now)

    assert result["executed"] is True
    assert result["result"] == {"prepared_tasks": 7}
    assert result["automatic_merge"] is False
    assert result["automatic_deploy"] is False

    repeated = scheduler.run_if_due(lambda limit: {"prepared_tasks": limit}, now + timedelta(minutes=10))
    assert repeated["executed"] is False


def test_policy_bounds_fail_closed():
    with pytest.raises(ValueError):
        ReactiveScheduler(SchedulerPolicy(interval_minutes=1))
    with pytest.raises(ValueError):
        ReactiveScheduler(SchedulerPolicy(max_tasks_per_cycle=100))
