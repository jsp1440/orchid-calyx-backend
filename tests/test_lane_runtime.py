"""Tests for lane_runtime.py — OC-RUNTIME-001 Phase 1 concurrency proof.

Deterministic tests proving:
1. 3 distinct lanes can run concurrently (mock workers, track thread IDs)
2. Duplicate key raises LaneCollision
3. Lane is released after failure (worker raises exception)
4. Lane freed → refill from queue (4th task enters after 1st completes)
5. Cost is never silently zero (UNKNOWN when not measured)
6. max_lanes=8 is the ceiling (can't acquire 9th slot)
7. Production mutation gate: no merge/deploy methods on dispatcher result
"""

from __future__ import annotations

import threading
import time

import pytest

from app.calyx_orchestrator.bounded_dispatcher import DispatchConfig, DispatchRun
from app.calyx_orchestrator.deep_orchestrate import (
    AUTH_WORKSPACE,
    DeepOrchestrate,
    Priority,
    TaskLeaf,
)
from app.calyx_orchestrator.lane_runtime import (
    COST_UNKNOWN,
    MAX_ACTIVE_LANES,
    ConcurrentBoundedDispatcher,
    LaneCollision,
    LaneIdentity,
    LaneManager,
)
from app.calyx_orchestrator.leaf_worker import TaskExecutionResult

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_leaf(key: str, *, priority: int = Priority.P2) -> TaskLeaf:
    """Return a ready workspace-authority TaskLeaf."""
    return TaskLeaf(
        key=key,
        title=f"Test leaf {key}",
        repo="orchid-calyx-backend",
        module="app/calyx_orchestrator",
        priority=priority,
        authority_class=AUTH_WORKSPACE,
        consequence_risk="low",
    )


def _make_reservoir(*keys: str, width: int | None = None) -> DeepOrchestrate:
    w = width if width is not None else max(len(keys), 1)
    reservoir = DeepOrchestrate(configured_width=w)
    for key in keys:
        reservoir.register(_make_leaf(key))
    return reservoir


class _MockWorker:
    """Deterministic mock worker that records the calling thread ID.

    If a ``barrier`` is provided, all threads must arrive before any proceeds,
    proving genuine concurrent execution.
    """

    def __init__(
        self,
        *,
        barrier: threading.Barrier | None = None,
        delay: float = 0.0,
    ) -> None:
        self.barrier = barrier
        self.delay = delay
        self._lock = threading.Lock()
        self.thread_ids: list[int] = []

    def execute(self, leaf: TaskLeaf) -> TaskExecutionResult:
        tid = threading.get_ident()
        with self._lock:
            self.thread_ids.append(tid)
        if self.barrier is not None:
            self.barrier.wait(timeout=5.0)
        if self.delay:
            time.sleep(self.delay)
        return TaskExecutionResult(
            task_key=leaf.key,
            worker_id="mock-worker",
            status="completed",
            started_at="2026-09-15T00:00:00+00:00",
            completed_at="2026-09-15T00:00:01+00:00",
            duration_seconds=0.001,
            output={"mock": True},
        )


class _FailingWorker:
    """Worker that always raises a RuntimeError — simulates worker crash."""

    def execute(self, leaf: TaskLeaf) -> TaskExecutionResult:
        raise RuntimeError(f"SIMULATED_FAILURE:{leaf.key}")


# ---------------------------------------------------------------------------
# Test 1: 3 distinct lanes run concurrently with distinct thread IDs
# ---------------------------------------------------------------------------


def test_three_lanes_concurrent_distinct_thread_ids() -> None:
    """Prove 3 TaskLeaves run in 3 distinct threads with 3 distinct lane IDs."""
    keys = [
        "rt:retrieve-evidence:task-a",
        "rt:retrieve-evidence:task-b",
        "rt:retrieve-evidence:task-c",
    ]
    # Barrier forces all 3 worker threads to overlap before any can finish.
    barrier = threading.Barrier(3)
    worker = _MockWorker(barrier=barrier)
    reservoir = _make_reservoir(*keys, width=3)

    dispatcher = ConcurrentBoundedDispatcher(
        reservoir, worker=worker, max_lanes=8  # type: ignore[arg-type]
    )
    run = dispatcher.run(DispatchConfig(max_tasks=3, max_iterations=2))

    assert run.tasks_executed == 3, (
        f"Expected 3 executed tasks, got {run.tasks_executed}"
    )

    # 3 evidence records with 3 distinct lane IDs.
    evidence = dispatcher.lane_evidence_snapshot()
    assert len(evidence) == 3
    lane_ids = [e["lane_id"] for e in evidence]
    assert len(set(lane_ids)) == 3, (
        f"Expected 3 distinct lane IDs, got {set(lane_ids)!r}"
    )

    # At least 2 distinct thread IDs proves concurrent (not serial) execution.
    assert len(set(worker.thread_ids)) >= 2, (
        f"Expected >= 2 distinct thread IDs (concurrent), got {worker.thread_ids!r}"
    )

    # All lanes completed successfully.
    statuses = [e["status"] for e in evidence]
    assert all(s == "completed" for s in statuses), (
        f"Expected all 'completed', got {statuses!r}"
    )


# ---------------------------------------------------------------------------
# Test 2: Duplicate key raises LaneCollision
# ---------------------------------------------------------------------------


def test_duplicate_key_raises_lane_collision() -> None:
    """Acquiring the same key twice raises LaneCollision."""
    manager = LaneManager(max_lanes=8)
    lane = manager.acquire("task:retrieve-evidence:alpha", holder="tester-1")
    assert isinstance(lane, LaneIdentity)
    assert lane.lease_key == "task:retrieve-evidence:alpha"

    with pytest.raises(LaneCollision, match="LANE_COLLISION"):
        manager.acquire("task:retrieve-evidence:alpha", holder="tester-2")

    # Release and re-acquire must succeed (slot is freed).
    manager.release(lane.lane_id)
    lane2 = manager.acquire("task:retrieve-evidence:alpha", holder="tester-3")
    assert lane2.lane_id != lane.lane_id
    manager.release(lane2.lane_id)


# ---------------------------------------------------------------------------
# Test 3: Lane released after worker failure
# ---------------------------------------------------------------------------


def test_lane_released_after_worker_failure() -> None:
    """Lane slot is released even when the worker raises an exception."""
    key = "rt:retrieve-evidence:fail-task"
    reservoir = _make_reservoir(key)
    failing_worker = _FailingWorker()

    dispatcher = ConcurrentBoundedDispatcher(
        reservoir, worker=failing_worker, max_lanes=8  # type: ignore[arg-type]
    )
    dispatcher.run(DispatchConfig(max_tasks=1, max_iterations=1))

    # All 8 slots must be available after the failure (lane was released).
    assert dispatcher.lane_manager.available_slots() == 8, (
        "Lane slot was not released after worker failure"
    )

    # Evidence record must exist and carry 'failed' status.
    evidence = dispatcher.lane_evidence_snapshot()
    assert len(evidence) == 1
    assert evidence[0]["status"] == "failed", (
        f"Expected 'failed' evidence status, got {evidence[0]['status']!r}"
    )


# ---------------------------------------------------------------------------
# Test 4: Lane freed → refill from queue (4th task after 1st batch completes)
# ---------------------------------------------------------------------------


def test_lane_freed_refills_from_queue() -> None:
    """After a lane frees, the next iteration picks the 4th task from the queue."""
    keys = [
        "rt:retrieve-evidence:q1",
        "rt:retrieve-evidence:q2",
        "rt:retrieve-evidence:q3",
        "rt:retrieve-evidence:q4",
    ]
    reservoir = _make_reservoir(*keys, width=4)
    worker = _MockWorker()

    # max_lanes=2 forces two separate batches of 2, proving refill behaviour.
    dispatcher = ConcurrentBoundedDispatcher(
        reservoir, worker=worker, max_lanes=2  # type: ignore[arg-type]
    )
    run = dispatcher.run(DispatchConfig(max_tasks=4, max_iterations=4, width=2))

    assert run.tasks_executed == 4, (
        f"Expected 4 executed tasks, got {run.tasks_executed}"
    )

    evidence = dispatcher.lane_evidence_snapshot()
    executed_keys = {e["lease_key"] for e in evidence}
    assert executed_keys == set(keys), (
        f"Not all 4 tasks executed: missing {set(keys) - executed_keys!r}"
    )

    # Verify at least 2 iterations ran (first batch freed lanes, second batch refilled).
    assert run.iterations >= 2, (
        f"Expected at least 2 dispatch iterations (refill proof), got {run.iterations}"
    )


# ---------------------------------------------------------------------------
# Test 5: Cost is never silently zero (UNKNOWN when not measured)
# ---------------------------------------------------------------------------


def test_cost_is_never_silently_zero() -> None:
    """ConcurrentBoundedDispatcher records COST_UNKNOWN, never 0 or None."""
    key = "rt:retrieve-evidence:cost-check"
    reservoir = _make_reservoir(key)
    worker = _MockWorker()

    dispatcher = ConcurrentBoundedDispatcher(
        reservoir, worker=worker, max_lanes=8  # type: ignore[arg-type]
    )
    dispatcher.run(DispatchConfig(max_tasks=1, max_iterations=1))

    evidence = dispatcher.lane_evidence_snapshot()
    assert len(evidence) == 1

    cost = evidence[0]["cost"]
    assert cost == COST_UNKNOWN, f"Expected COST_UNKNOWN ({COST_UNKNOWN!r}), got {cost!r}"
    assert cost != 0, "Cost must not be silently zero (integer)"
    assert cost is not None, "Cost must not be None"
    assert cost != "0", "Cost must not be string zero"
    assert cost != 0.0, "Cost must not be float zero"

    # Sanity: the sentinel value is the string "UNKNOWN"
    assert COST_UNKNOWN == "UNKNOWN"


# ---------------------------------------------------------------------------
# Test 6: max_lanes=8 is the ceiling (can't acquire 9th slot)
# ---------------------------------------------------------------------------


def test_max_lanes_ceiling_at_eight() -> None:
    """LaneManager enforces max_lanes=8; a 9th acquisition raises LaneCollision."""
    assert MAX_ACTIVE_LANES == 8, (
        "MAX_ACTIVE_LANES must equal 8 per owner authorization (Jeff Parham, OC-RUNTIME-001)"
    )

    manager = LaneManager(max_lanes=MAX_ACTIVE_LANES)
    lanes = []
    for i in range(8):
        lane = manager.acquire(f"task:retrieve-evidence:slot-{i}", holder="test")
        lanes.append(lane)

    assert manager.available_slots() == 0
    assert len(manager.active_lanes()) == 8

    # 9th acquisition must raise LaneCollision.
    with pytest.raises(LaneCollision, match="LANE_CAPACITY_FULL"):
        manager.acquire("task:retrieve-evidence:overflow", holder="test")

    # Release one → 9th (now renamed) must succeed.
    manager.release(lanes[0].lane_id)
    assert manager.available_slots() == 1

    lane_ok = manager.acquire("task:retrieve-evidence:now-ok", holder="test")
    assert lane_ok is not None
    manager.release(lane_ok.lane_id)

    # Clean up remaining lanes.
    for lane in lanes[1:]:
        manager.release(lane.lane_id)
    assert manager.available_slots() == 8


# ---------------------------------------------------------------------------
# Test 7: Production mutation gate (structural)
# ---------------------------------------------------------------------------


def test_no_production_mutation_methods_on_dispatcher() -> None:
    """ConcurrentBoundedDispatcher and DispatchRun never expose merge/deploy methods.

    This is a structural gate: no lane completing should be able to trigger
    production mutation merely by calling a method on the dispatcher result.
    """
    dispatcher = ConcurrentBoundedDispatcher(
        DeepOrchestrate(configured_width=1),
        max_lanes=8,
    )
    run_result = DispatchRun()

    forbidden_names = [
        "merge",
        "deploy",
        "activate",
        "publish",
        "push_to_production",
        "mutate_production",
        "activate_production",
        "spend",
        "delete_production",
        "merge_pr",
        "deploy_to_prod",
    ]

    dispatcher_violations = [n for n in forbidden_names if hasattr(dispatcher, n)]
    run_violations = [n for n in forbidden_names if hasattr(run_result, n)]

    assert not dispatcher_violations, (
        f"ConcurrentBoundedDispatcher must not expose production-mutation methods: "
        f"{dispatcher_violations!r}"
    )
    assert not run_violations, (
        f"DispatchRun must not expose production-mutation methods: "
        f"{run_violations!r}"
    )
