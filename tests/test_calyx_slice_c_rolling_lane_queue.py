import pytest

from app.calyx_orchestrator.lane_queue import (
    BacklogTask,
    CyclicDependencyError,
    DuplicateTaskKeyError,
    RollingLaneQueue,
    TaskStatus,
    UnknownDependencyError,
)


def _tasks(count: int, *, priority_start: int = 100) -> list[BacklogTask]:
    return [
        BacklogTask(
            task_key=f"t{i}",
            title=f"Task {i}",
            priority=priority_start - i,
            created_order=i,
        )
        for i in range(count)
    ]


def test_width_five_admits_at_most_five_active_lanes():
    queue = RollingLaneQueue(_tasks(10), width=5)
    status = queue.status()
    assert status["width"] == 5
    assert len(status["active"]) == 5
    assert [item["task_key"] for item in status["active"]] == ["t0", "t1", "t2", "t3", "t4"]
    assert [item["task_key"] for item in status["queued_next"]] == ["t5", "t6", "t7", "t8", "t9"]


def test_refill_admits_next_highest_priority_task_immediately():
    queue = RollingLaneQueue(_tasks(10), width=5)
    result = queue.advance("t2", TaskStatus.VERIFIED)
    assert result["admitted"] == ["t5"]
    status = queue.status()
    active_keys = {item["task_key"] for item in status["active"]}
    assert active_keys == {"t0", "t1", "t3", "t4", "t5"}
    assert [item["task_key"] for item in status["queued_next"]] == ["t6", "t7", "t8", "t9"]


def test_no_idle_capacity_while_eligible_work_exists():
    queue = RollingLaneQueue(_tasks(7), width=5)
    for key in ("t0", "t1", "t2", "t3", "t4"):
        queue.advance(key, TaskStatus.VERIFIED)
    status = queue.status()
    assert len(status["active"]) == 2
    assert {item["task_key"] for item in status["active"]} == {"t5", "t6"}
    assert status["queued_next"] == []


def test_priority_ordering_admits_higher_priority_before_lower():
    tasks = [
        BacklogTask(task_key="low", title="low priority", priority=1, created_order=0),
        BacklogTask(task_key="high", title="high priority", priority=100, created_order=1),
    ]
    queue = RollingLaneQueue(tasks, width=1)
    status = queue.status()
    assert [item["task_key"] for item in status["active"]] == ["high"]
    assert [item["task_key"] for item in status["queued_next"]] == ["low"]


def test_dependency_gating_keeps_blocked_task_out_of_active_width():
    tasks = [
        BacklogTask(task_key="root", title="root", priority=10),
        BacklogTask(task_key="child", title="child", priority=99, depends_on=("root",)),
    ]
    queue = RollingLaneQueue(tasks, width=5)
    status = queue.status()
    assert [item["task_key"] for item in status["active"]] == ["root"]
    assert [item["task_key"] for item in status["blocked"]] == ["child"]

    queue.advance("root", TaskStatus.VERIFIED)
    status = queue.status()
    assert [item["task_key"] for item in status["active"]] == ["child"]
    assert status["blocked"] == []


def test_dependency_blocked_by_owner_gated_parent_stays_blocked():
    tasks = [
        BacklogTask(task_key="root", title="root", priority=10),
        BacklogTask(task_key="child", title="child", priority=99, depends_on=("root",)),
    ]
    queue = RollingLaneQueue(tasks, width=5)
    queue.advance("root", TaskStatus.OWNER_GATED)
    status = queue.status()
    assert [item["task_key"] for item in status["blocked"]] == ["child"]
    assert [item["task_key"] for item in status["owner_gated"]] == ["root"]
    assert status["active"] == []


def test_duplicate_task_key_rejected():
    tasks = [
        BacklogTask(task_key="dup", title="one"),
        BacklogTask(task_key="dup", title="two"),
    ]
    with pytest.raises(DuplicateTaskKeyError):
        RollingLaneQueue(tasks, width=5)


def test_no_duplicate_active_lane_for_same_task_key_across_advances():
    queue = RollingLaneQueue(_tasks(6), width=5)
    with pytest.raises(ValueError):
        queue.advance("t0", TaskStatus.VERIFIED)
        queue.advance("t0", TaskStatus.VERIFIED)


def test_unknown_dependency_rejected():
    tasks = [BacklogTask(task_key="a", title="a", depends_on=("missing",))]
    with pytest.raises(UnknownDependencyError):
        RollingLaneQueue(tasks, width=5)


def test_cyclic_dependency_rejected():
    tasks = [
        BacklogTask(task_key="a", title="a", depends_on=("b",)),
        BacklogTask(task_key="b", title="b", depends_on=("a",)),
    ]
    with pytest.raises(CyclicDependencyError):
        RollingLaneQueue(tasks, width=5)


def test_owner_gated_task_releases_capacity_but_remains_visible():
    queue = RollingLaneQueue(_tasks(6), width=5)
    result = queue.advance("t1", TaskStatus.OWNER_GATED, note="Needs owner approval")
    assert result["admitted"] == ["t5"]
    status = queue.status()
    assert [item["task_key"] for item in status["owner_gated"]] == ["t1"]
    assert status["owner_gated"][0]["note"] == "Needs owner approval"
    assert len(status["active"]) == 5
    assert "t1" not in {item["task_key"] for item in status["active"]}


def test_owner_gate_release_requeues_and_is_reeligible_for_admission():
    tasks = _tasks(6)
    queue = RollingLaneQueue(tasks, width=5)
    queue.advance("t0", TaskStatus.OWNER_GATED)
    for key in ("t1", "t2", "t3", "t4"):
        queue.advance(key, TaskStatus.VERIFIED)
    status = queue.status()
    assert {item["task_key"] for item in status["active"]} == {"t5"}
    assert [item["task_key"] for item in status["owner_gated"]] == ["t0"]

    release = queue.release_owner_gate("t0", requeue=True)
    assert release["admitted"] == ["t0"]
    status = queue.status()
    assert {item["task_key"] for item in status["active"]} == {"t0", "t5"}
    assert status["owner_gated"] == []


def test_external_blocker_releases_lane_and_is_tracked_separately():
    queue = RollingLaneQueue(_tasks(6), width=5)
    result = queue.advance("t3", TaskStatus.EXTERNAL_BLOCKER, note="Upstream service down")
    assert result["admitted"] == ["t5"]
    status = queue.status()
    assert [item["task_key"] for item in status["external_blocked"]] == ["t3"]
    assert status["external_blocked"][0]["note"] == "Upstream service down"


def test_status_projection_is_deterministic_across_repeated_calls():
    queue = RollingLaneQueue(_tasks(9), width=5)
    queue.advance("t0", TaskStatus.VERIFIED)
    queue.advance("t4", TaskStatus.OWNER_GATED)
    first = queue.status()
    second = queue.status()
    assert first == second


def test_last_action_and_next_action_reflect_owner_gate_priority():
    queue = RollingLaneQueue(_tasks(6), width=5)
    queue.advance("t2", TaskStatus.OWNER_GATED, note="owner must decide")
    status = queue.status()
    assert status["last_action"]["task_key"] == "t2"
    assert status["last_action"]["outcome"] == "owner_gated"
    assert "Owner review required" in status["next_action"]
    assert "t2" in status["next_action"]


def test_queue_idle_next_action_when_everything_is_verified():
    tasks = _tasks(2)
    queue = RollingLaneQueue(tasks, width=5)
    queue.advance("t0", TaskStatus.VERIFIED)
    queue.advance("t1", TaskStatus.VERIFIED)
    status = queue.status()
    assert status["active"] == []
    assert status["queued_next"] == []
    assert status["next_action"] == "Queue idle; all tasks verified."


def test_advance_rejects_unknown_task_key():
    queue = RollingLaneQueue(_tasks(2), width=5)
    with pytest.raises(KeyError):
        queue.advance("does-not-exist", TaskStatus.VERIFIED)


def test_advance_rejects_task_that_is_not_active():
    queue = RollingLaneQueue(_tasks(6), width=5)
    with pytest.raises(ValueError):
        queue.advance("t5", TaskStatus.VERIFIED)


def test_advance_rejects_unsupported_outcome():
    queue = RollingLaneQueue(_tasks(2), width=5)
    with pytest.raises(ValueError):
        queue.advance("t0", TaskStatus.QUEUED)
