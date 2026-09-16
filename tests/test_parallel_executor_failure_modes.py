"""Deterministic failure-mode proof for the parallel executor (provider-free).

Exercises the already-built pieces together — DurableOrchestrate (reservations,
leases, restart durability), BoundedDispatcher (capacity fill, refill, crash
isolation, bounded lease recovery), DeterministicResearchWorker — over a
file-backed SQLite database so concurrent sessions use separate connections.

Cases (mission phase 4):
  A. two independent tasks run simultaneously
  B. eight independent active lanes
  C. completion refills the freed slot automatically
  D. one worker crashes: other lanes continue, failed lane records evidence
  E. one lease expires: recovery requeues and re-dispatches it (bounded)
  F. an OWNER_GATED task parks and another runnable task takes its slot
  G. dependency: B waits for A; A completes; B activates automatically
  H. restart: durable execution state survives a new process/session
  I. double lease: two workers cannot acquire the same task
  J. queue > 0 and running = 0 with stale leases: one cycle repairs it

No paid provider call is made anywhere in this module.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.calyx_orchestrator.bounded_dispatcher import BoundedDispatcher, DispatchConfig
from app.calyx_orchestrator.deep_orchestrate import (
    AUTH_PRODUCTION,
    AUTH_WORKSPACE,
    Priority,
    TaskLeaf,
    TaskState,
)
from app.calyx_orchestrator.durable_reservoir import DurableOrchestrate
from app.calyx_orchestrator.durable_reservoir_models import (
    DurableReservoirRun,
    DurableReservoirTask,
)
from app.calyx_orchestrator.leaf_worker import DeterministicResearchWorker, TaskExecutionResult

MAX_ACTIVE_LANES = 8


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def engine(tmp_path):
    """File-backed SQLite: every session owns its own connection, like Postgres."""
    e = create_engine(
        f"sqlite:///{tmp_path / 'executor.db'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    DurableReservoirRun.__table__.create(e)
    DurableReservoirTask.__table__.create(e)
    yield e
    e.dispose()


@pytest.fixture
def sessions(engine):
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def leaf(key: str, *, deps: list[str] | None = None, authority: str = AUTH_WORKSPACE,
         priority: int = Priority.P2) -> TaskLeaf:
    return TaskLeaf(
        key=key, title=key, repo="orchid-calyx-backend", module="app/calyx_orchestrator",
        priority=priority, authority_class=authority, consequence_risk="low",
        dependencies=list(deps or []),
    )


def keys(prefix: str, n: int) -> list[str]:
    return [f"{prefix}-{i}:retrieve-evidence" for i in range(n)]


class BarrierWorker:
    """Completes only if ``parties`` executions overlap in time (true concurrency)."""

    def __init__(self, parties: int, *, crash_key: str | None = None) -> None:
        self.barrier = threading.Barrier(parties)
        self.crash_key = crash_key
        self.threads: list[int] = []
        self.windows: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()
        self.worker_id = "barrier-worker"

    def execute(self, task: TaskLeaf) -> TaskExecutionResult:
        start = time.monotonic()
        with self._lock:
            self.threads.append(threading.get_ident())
        self.barrier.wait(timeout=10)
        if task.key == self.crash_key:
            raise RuntimeError(f"SIMULATED_WORKER_CRASH:{task.key}")
        result = DeterministicResearchWorker(self.worker_id).execute(task)
        with self._lock:
            self.windows[task.key] = (start, time.monotonic())
        return result


def overlapping(windows: dict[str, tuple[float, float]]) -> bool:
    spans = sorted(windows.values())
    latest_start = max(s for s, _ in spans)
    earliest_end = min(e for _, e in spans)
    return latest_start < earliest_end


def reservoir(sessions, run_id="run", width=MAX_ACTIVE_LANES, leaves=()):
    r = DurableOrchestrate.create_run(sessions(), run_id, configured_width=width)
    for item in leaves:
        r.register(item)
    return r


def states(r: DurableOrchestrate) -> dict[str, str]:
    return {k: v["state"] for k, v in r.to_dict()["tasks"].items()}


# ---------------------------------------------------------------------------
# A/B — genuine simultaneous lanes
# ---------------------------------------------------------------------------


def test_A_two_independent_tasks_run_simultaneously(sessions):
    r = reservoir(sessions, width=2, leaves=[leaf(k) for k in keys("a", 2)])
    worker = BarrierWorker(2)
    run = BoundedDispatcher(r, worker=worker).run(DispatchConfig(max_tasks=2, max_iterations=1))
    assert run.summary()["completed"] == 2
    assert len(set(worker.threads)) == 2
    assert overlapping(worker.windows)
    assert r.active_tasks() == []


def test_B_eight_independent_lanes_are_simultaneously_active(sessions):
    r = reservoir(sessions, width=MAX_ACTIVE_LANES, leaves=[leaf(k) for k in keys("b", 8)])
    worker = BarrierWorker(8)
    run = BoundedDispatcher(r, worker=worker).run(DispatchConfig(max_tasks=8, max_iterations=1))
    assert run.summary()["completed"] == 8
    assert len(set(worker.threads)) == 8
    assert overlapping(worker.windows)
    evidence = {k: v["evidence"] for k, v in r.to_dict()["tasks"].items()}
    assert all(e["worker_id"] == "barrier-worker" and e["status"] == "completed" for e in evidence.values())
    assert all(e["output"]["provider_api_called"] is False for e in evidence.values())


def test_B_capacity_is_never_exceeded_by_the_reservoir(sessions):
    r = reservoir(sessions, width=8, leaves=[leaf(k) for k in keys("cap", 12)])
    admitted = r.refill()
    assert len(admitted) == 8
    for item in admitted:
        r.lease(item.key, holder="w")
    assert r.refill() == []
    assert len(r.active_tasks()) == 8


# ---------------------------------------------------------------------------
# C — completion refills the freed slot
# ---------------------------------------------------------------------------


def test_C_completion_refills_freed_slots_automatically(sessions):
    r = reservoir(sessions, width=2, leaves=[leaf(k) for k in keys("c", 5)])
    run = BoundedDispatcher(r).run(DispatchConfig(max_tasks=5, max_iterations=5))
    assert run.summary()["completed"] == 5
    assert run.iterations == 3  # 2 + 2 + 1: each freed slot was refilled
    assert set(states(r).values()) == {TaskState.COMPLETED}


# ---------------------------------------------------------------------------
# D — worker crash isolation
# ---------------------------------------------------------------------------


def test_D_worker_crash_blocks_only_its_lane_with_exact_evidence(sessions):
    crash = "d-1:retrieve-evidence"
    r = reservoir(sessions, width=4, leaves=[leaf(k) for k in keys("d", 4)])
    worker = BarrierWorker(4, crash_key=crash)
    run = BoundedDispatcher(r, worker=worker).run(DispatchConfig(max_tasks=4, max_iterations=1))
    summary = run.summary()
    assert summary["completed"] == 3 and summary["blocked"] == 1
    assert summary["worker_exceptions"] == 1
    crashed = r.get(crash)
    assert crashed.state == TaskState.BLOCKED
    assert crashed.blocked_reason == f"WORKER_EXCEPTION:RuntimeError:SIMULATED_WORKER_CRASH:{crash}"
    assert crashed.lease_holder is None  # capacity released
    assert r.active_tasks() == []
    others = {k: v for k, v in states(r).items() if k != crash}
    assert set(others.values()) == {TaskState.COMPLETED}


def test_D_crash_in_first_batch_does_not_stop_later_batches(sessions):
    crash = "d2-0:retrieve-evidence"
    r = reservoir(sessions, width=1, leaves=[leaf(k) for k in keys("d2", 3)])

    class CrashFirst:
        worker_id = "crash-first"

        def execute(self, task):
            if task.key == crash:
                raise ValueError("boom")
            return DeterministicResearchWorker().execute(task)

    run = BoundedDispatcher(r, worker=CrashFirst()).run(DispatchConfig(max_tasks=3, max_iterations=3))
    assert run.summary()["completed"] == 2 and run.summary()["blocked"] == 1
    assert r.get(crash).blocked_reason == "WORKER_EXCEPTION:ValueError:boom"


# ---------------------------------------------------------------------------
# E — expired lease recovery (bounded)
# ---------------------------------------------------------------------------


def _expire_lease(sessions, run_id: str, key: str, age_seconds: int) -> None:
    session = sessions()
    row = (
        session.query(DurableReservoirTask)
        .filter(DurableReservoirTask.run_id == run_id, DurableReservoirTask.task_key == key)
        .one()
    )
    row.leased_at = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    session.commit()
    session.close()


def test_E_expired_lease_is_recovered_requeued_and_redispatched(sessions):
    r = reservoir(sessions, run_id="e", width=2, leaves=[leaf(k) for k in keys("e", 2)])
    dead = "e-0:retrieve-evidence"
    r.lease(dead, holder="worker-that-died")
    _expire_lease(sessions, "e", dead, age_seconds=3600)

    run = BoundedDispatcher(r).run(DispatchConfig(max_tasks=2, max_iterations=2, max_lease_age_seconds=300))
    assert run.expired_recovered == 1 and run.leases_requeued == 1 and run.leases_parked == 0
    assert run.summary()["completed"] == 2
    recovered = r.get(dead)
    assert recovered.state == TaskState.COMPLETED
    assert recovered.evidence["lease_recoveries"] == 1
    assert recovered.evidence["last_lease_recovery"]["reason"].startswith("LEASE_EXPIRED:")
    assert "worker-that-died" in recovered.evidence["last_lease_recovery"]["reason"]


def test_E_lease_recovery_is_bounded_then_parks_with_reason(sessions):
    r = reservoir(sessions, run_id="e2", width=1, leaves=[leaf("e2-0:retrieve-evidence")])
    key = "e2-0:retrieve-evidence"
    for attempt in range(3):
        r.lease(key, holder=f"dead-{attempt}")
        _expire_lease(sessions, "e2", key, age_seconds=3600)
        # A worker that never completes: dispatcher recovers, requeues, leases, then we kill it again.
        expired = r.recover_expired_leases(300)
        assert [item.key for item in expired] == [key]
        prior = int(r.get(key).evidence.get("lease_recoveries", 0))
        if prior < 2:
            r.recover_from_backoff(key, evidence={"lease_recoveries": prior + 1})
        else:
            break
    parked = r.get(key)
    assert parked.state == TaskState.REPAIR_BACKOFF
    assert parked.evidence["lease_recoveries"] == 2
    run = BoundedDispatcher(r).run(DispatchConfig(max_tasks=1, max_iterations=1))
    assert run.tasks_executed == 0 and run.leases_requeued == 0
    assert r.get(key).state == TaskState.REPAIR_BACKOFF  # stays parked, never loops


def test_E_fresh_lease_is_not_recovered(sessions):
    r = reservoir(sessions, run_id="e3", width=1, leaves=[leaf("e3-0:retrieve-evidence")])
    r.lease("e3-0:retrieve-evidence", holder="live-worker")
    run = BoundedDispatcher(r).run(DispatchConfig(max_tasks=1, max_iterations=1, max_lease_age_seconds=300))
    assert run.expired_recovered == 0
    assert r.get("e3-0:retrieve-evidence").state == TaskState.LEASED


# ---------------------------------------------------------------------------
# F — owner gate parks without consuming a slot
# ---------------------------------------------------------------------------


def test_F_owner_gated_task_parks_and_releases_its_slot(sessions):
    gated = leaf("f-gate:canonical-activation", authority=AUTH_PRODUCTION, priority=Priority.P0)
    runnable = leaf("f-run:retrieve-evidence", priority=Priority.P4)
    r = reservoir(sessions, width=1, leaves=[gated, runnable])
    assert r.get(gated.key).state == TaskState.OWNER_GATED
    run = BoundedDispatcher(r).run(DispatchConfig(max_tasks=2, max_iterations=2))
    assert run.summary()["completed"] == 1
    assert r.get(runnable.key).state == TaskState.COMPLETED
    assert r.get(gated.key).state == TaskState.OWNER_GATED
    assert r.snapshot()["owner_gate_count"] == 1 and r.snapshot()["active_count"] == 0


def test_F_worker_refuses_owner_gated_authority_even_if_leased(sessions):
    """Defence in depth: if a gated leaf ever reached a worker it is blocked, never executed."""
    gated = leaf("f2:canonical-activation", authority=AUTH_PRODUCTION)
    gated.state = TaskState.READY
    r = reservoir(sessions, width=1)
    r.register(gated)
    r.authorize(gated.key)  # explicit owner authorization path → READY
    result = DeterministicResearchWorker().execute(r.lease(gated.key, holder="w"))
    assert result.status == "blocked" and result.error_reason == "OWNER_GATE_REQUIRED"


# ---------------------------------------------------------------------------
# G — dependency activation
# ---------------------------------------------------------------------------


def test_G_dependent_task_activates_automatically_after_upstream_completes(sessions):
    a = leaf("g-a:retrieve-evidence")
    b = leaf("g-b:normalize-evidence", deps=[a.key])
    r = reservoir(sessions, width=8, leaves=[a, b])
    assert [item.key for item in r.ready_tasks()] == [a.key]
    run = BoundedDispatcher(r).run(DispatchConfig(max_tasks=2, max_iterations=3))
    assert run.summary()["completed"] == 2
    assert run.iterations == 2  # b became READY only after a completed
    assert r.get(b.key).state == TaskState.COMPLETED


def test_G_dependency_on_blocked_task_never_activates(sessions):
    a = leaf("g2-a:unknown-step")  # DeterministicResearchWorker blocks unknown steps
    b = leaf("g2-b:retrieve-evidence", deps=[a.key])
    r = reservoir(sessions, width=8, leaves=[a, b])
    run = BoundedDispatcher(r).run(DispatchConfig(max_tasks=2, max_iterations=3))
    assert run.summary()["blocked"] == 1 and run.summary()["completed"] == 0
    assert r.get(a.key).state == TaskState.BLOCKED
    assert r.get(b.key).state == TaskState.READY and r.ready_tasks() == []


# ---------------------------------------------------------------------------
# H — restart durability
# ---------------------------------------------------------------------------


def test_H_durable_state_survives_restart_without_duplicate_execution(sessions):
    first = reservoir(sessions, run_id="h", width=2, leaves=[leaf(k) for k in keys("h", 4)])
    BoundedDispatcher(first).run(DispatchConfig(max_tasks=2, max_iterations=1))
    first._session.close()  # process dies here

    resumed = DurableOrchestrate.from_db(sessions(), "h")
    before = states(resumed)
    assert list(before.values()).count(TaskState.COMPLETED) == 2
    run = BoundedDispatcher(resumed).run(DispatchConfig(max_tasks=4, max_iterations=3))
    assert run.tasks_executed == 2  # only the remaining two; completed ones never re-run
    assert set(states(resumed).values()) == {TaskState.COMPLETED}
    executed_keys = {res.task_key for res in run.results}
    assert executed_keys == {k for k, s in before.items() if s == TaskState.READY}
    assert resumed.snapshot()["total_task_count"] == 4  # no duplicate rows


def test_H_active_lease_from_dead_process_is_recovered_after_restart(sessions):
    first = reservoir(sessions, run_id="h2", width=1, leaves=[leaf("h2-0:retrieve-evidence")])
    first.lease("h2-0:retrieve-evidence", holder="crashed-process")
    _expire_lease(sessions, "h2", "h2-0:retrieve-evidence", age_seconds=999)
    first._session.close()

    resumed = DurableOrchestrate.from_db(sessions(), "h2")
    assert resumed.get("h2-0:retrieve-evidence").state == TaskState.LEASED
    run = BoundedDispatcher(resumed).run(DispatchConfig(max_tasks=1, max_iterations=1, max_lease_age_seconds=300))
    assert run.expired_recovered == 1 and run.summary()["completed"] == 1


# ---------------------------------------------------------------------------
# I — double-lease protection
# ---------------------------------------------------------------------------


def test_I_two_workers_cannot_lease_the_same_task(sessions):
    reservoir(sessions, run_id="i", width=8, leaves=[leaf("i-0:retrieve-evidence")])
    gate = threading.Barrier(2)

    def attempt(name):
        r = DurableOrchestrate.from_db(sessions(), "i")
        gate.wait(timeout=10)
        try:
            r.lease("i-0:retrieve-evidence", holder=name)
            return "leased"
        except ValueError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, ["worker-a", "worker-b"]))
    assert outcomes.count("leased") == 1
    assert any(o.startswith("TASK_NOT_READY") for o in outcomes)
    final = DurableOrchestrate.from_db(sessions(), "i").get("i-0:retrieve-evidence")
    assert final.state == TaskState.LEASED and final.lease_holder in {"worker-a", "worker-b"}


def test_I_two_dispatchers_on_one_reservoir_execute_each_task_exactly_once(sessions):
    reservoir(sessions, run_id="i2", width=4, leaves=[leaf(k) for k in keys("i2", 6)])
    gate = threading.Barrier(2)

    def dispatch(name):
        r = DurableOrchestrate.from_db(sessions(), "i2")
        gate.wait(timeout=10)
        return BoundedDispatcher(r).run(DispatchConfig(max_tasks=6, max_iterations=6, lease_holder=name))

    with ThreadPoolExecutor(max_workers=2) as pool:
        runs = list(pool.map(dispatch, ["dispatcher-a", "dispatcher-b"]))
    executed = [res.task_key for run in runs for res in run.results]
    assert sorted(executed) == sorted(keys("i2", 6))  # each exactly once across both
    assert set(states(DurableOrchestrate.from_db(sessions(), "i2")).values()) == {TaskState.COMPLETED}


# ---------------------------------------------------------------------------
# J — queue > 0 with zero live workers is repaired in one cycle
# ---------------------------------------------------------------------------


def test_J_queue_with_stale_leases_and_no_live_workers_is_repaired(sessions):
    r = reservoir(sessions, run_id="j", width=2, leaves=[leaf(k) for k in keys("j", 3)])
    # Two dead workers hold every slot; one more task waits; nothing is running.
    for key in keys("j", 2):
        r.lease(key, holder="dead")
        _expire_lease(sessions, "j", key, age_seconds=3600)
    snap = r.snapshot()
    assert snap["active_count"] == 2 and snap["ready_depth"] == 1 and r.refill() == []

    run = BoundedDispatcher(r).run(DispatchConfig(max_tasks=3, max_iterations=3, max_lease_age_seconds=300))
    assert run.expired_recovered == 2 and run.leases_requeued == 2
    assert run.summary()["completed"] == 3
    assert r.snapshot()["active_count"] == 0 and r.snapshot()["ready_depth"] == 0


def test_no_paid_provider_call_anywhere(sessions):
    r = reservoir(sessions, width=8, leaves=[leaf(k) for k in keys("np", 8)])
    BoundedDispatcher(r).run(DispatchConfig(max_tasks=8, max_iterations=1))
    outputs = [v["evidence"]["output"] for v in r.to_dict()["tasks"].values()]
    assert outputs and all(o.get("provider_api_called") is False for o in outputs)
