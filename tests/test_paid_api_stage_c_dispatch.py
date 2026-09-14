"""Stage C deterministic proof: PaidAPIWorker executes only through BoundedDispatcher.

ZERO real provider calls: MockPaidProvider only.  The hosted real-provider canary is
separate and must remain explicitly bounded by the Budget Governor.
"""

from __future__ import annotations

import threading

from app.calyx_orchestrator.bounded_dispatcher import BoundedDispatcher, DispatchConfig
from app.calyx_orchestrator.deep_orchestrate import (
    AUTH_PRODUCTION,
    AUTH_WORKSPACE,
    DeepOrchestrate,
    Priority,
    TaskLeaf,
    TaskState,
)
from app.calyx_orchestrator.github_coding_executor import BudgetClass, ConvergenceClass
from app.calyx_orchestrator.paid_api_worker import (
    PaidAPIWorker,
    build_paid_api_worker_with_mock,
)

FAKE_SHA = "a" * 40


def _leaf(key: str, *, authority: str = AUTH_WORKSPACE, deps: list[str] | None = None) -> TaskLeaf:
    leaf = TaskLeaf(
        key=key,
        title=f"Stage C proof {key}",
        repo="orchid-calyx-backend",
        module="app/calyx_orchestrator",
        priority=Priority.P1,
        authority_class=authority,
        consequence_risk="low",
        acceptance_criteria=["canonical dispatcher records terminal evidence"],
    )
    if deps:
        leaf.dependencies = deps
    leaf.evidence = {
        "mission_id": key,
        "repository": "jsp1440/orchid-calyx-backend",
        "objective": f"Bounded Stage C proof for {key}",
        "acceptance_criteria": ["tests pass"],
        "validation_commands": ["pytest -q tests/test_paid_api_stage_c_dispatch.py"],
        "budget_class": BudgetClass.TINY.value,
        "convergence_class": ConvergenceClass.NEW.value,
        "base_ref": "main",
        "base_sha": FAKE_SHA,
    }
    return leaf


class BarrierPaidWorker:
    """Wrap a real PaidAPIWorker and hold a batch until all leased lanes arrive."""

    def __init__(self, inner: PaidAPIWorker, width: int) -> None:
        self.inner = inner
        self.barrier = threading.Barrier(width)
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.seen_states: list[TaskState] = []

    def execute(self, leaf: TaskLeaf):
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            self.seen_states.append(leaf.state)
        try:
            self.barrier.wait(timeout=5)
            return self.inner.execute(leaf)
        finally:
            with self.lock:
                self.active -= 1


def test_stage_c_two_simultaneous_leases_use_canonical_dispatcher() -> None:
    reservoir = DeepOrchestrate(configured_width=2)
    reservoir.register_many([_leaf("stage-c:one"), _leaf("stage-c:two")])
    inner, governor, provider = build_paid_api_worker_with_mock(responses=["one", "two"])
    worker = BarrierPaidWorker(inner, width=2)

    run = BoundedDispatcher(reservoir, worker=worker).run(
        DispatchConfig(max_tasks=2, max_iterations=2, width=2, lease_holder="stage-c-proof")
    )

    assert run.tasks_executed == 2
    assert run.summary()["completed"] == 2
    assert worker.max_active == 2
    assert worker.seen_states == [TaskState.LEASED, TaskState.LEASED]
    assert len(provider.calls) == 2
    assert governor.reserved_usd == 0.0
    assert all(reservoir.get(key).state == TaskState.COMPLETED for key in ("stage-c:one", "stage-c:two"))
    assert reservoir.active_tasks() == []


def test_stage_c_eight_simultaneous_leases_are_bounded_to_width() -> None:
    reservoir = DeepOrchestrate(configured_width=8)
    leaves = [_leaf(f"stage-c:eight:{index}") for index in range(8)]
    reservoir.register_many(leaves)
    inner, governor, provider = build_paid_api_worker_with_mock(responses=[f"ok-{i}" for i in range(8)])
    worker = BarrierPaidWorker(inner, width=8)

    run = BoundedDispatcher(reservoir, worker=worker).run(
        DispatchConfig(max_tasks=8, max_iterations=2, width=8, lease_holder="stage-c-eight")
    )

    assert run.tasks_executed == 8
    assert run.summary()["completed"] == 8
    assert worker.max_active == 8
    assert len(provider.calls) == 8
    assert governor.reserved_usd == 0.0
    assert reservoir.active_tasks() == []


def test_stage_c_refills_after_first_batch_and_activates_dependency() -> None:
    reservoir = DeepOrchestrate(configured_width=2)
    upstream = _leaf("stage-c:upstream")
    peer = _leaf("stage-c:peer")
    downstream = _leaf("stage-c:downstream", deps=[upstream.key])
    reservoir.register_many([upstream, peer, downstream])
    worker, _, provider = build_paid_api_worker_with_mock(responses=["up", "peer", "down"])

    run = BoundedDispatcher(reservoir, worker=worker).run(
        DispatchConfig(max_tasks=3, max_iterations=4, width=2, lease_holder="stage-c-refill")
    )

    assert run.tasks_executed == 3
    assert run.iterations >= 2
    assert run.summary()["completed"] == 3
    assert len(provider.calls) == 3
    assert reservoir.get(downstream.key).state == TaskState.COMPLETED
    assert reservoir.active_tasks() == []


def test_stage_c_owner_gate_does_not_consume_lane_or_provider_budget() -> None:
    reservoir = DeepOrchestrate(configured_width=2)
    protected = _leaf("stage-c:protected", authority=AUTH_PRODUCTION)
    safe = _leaf("stage-c:safe")
    reservoir.register_many([protected, safe])
    worker, governor, provider = build_paid_api_worker_with_mock(responses=["safe"])

    run = BoundedDispatcher(reservoir, worker=worker).run(
        DispatchConfig(max_tasks=2, max_iterations=3, width=2, lease_holder="stage-c-gate")
    )

    assert run.tasks_executed == 1
    assert reservoir.get(protected.key).state == TaskState.OWNER_GATED
    assert reservoir.get(safe.key).state == TaskState.COMPLETED
    assert len(provider.calls) == 1
    assert governor.reserved_usd == 0.0


def test_stage_c_one_blocked_lane_does_not_prevent_peer_completion() -> None:
    reservoir = DeepOrchestrate(configured_width=2)
    reservoir.register_many([_leaf("stage-c:bad"), _leaf("stage-c:good")])
    worker, _, provider = build_paid_api_worker_with_mock(
        responses=[RuntimeError("simulated provider failure"), "good", RuntimeError("still failed")]
    )

    run = BoundedDispatcher(reservoir, worker=worker).run(
        DispatchConfig(max_tasks=2, max_iterations=2, width=2, lease_holder="stage-c-isolation")
    )

    states = {reservoir.get("stage-c:bad").state, reservoir.get("stage-c:good").state}
    assert TaskState.COMPLETED in states
    assert TaskState.BLOCKED in states
    assert run.tasks_executed == 2
    assert len(provider.calls) >= 2
    assert reservoir.active_tasks() == []
