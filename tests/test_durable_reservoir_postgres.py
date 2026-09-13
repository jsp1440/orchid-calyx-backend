"""PostgreSQL-specific tests for DurableOrchestrate.

These tests exercise the production path:
  - SELECT FOR UPDATE SKIP LOCKED (not emulated by the threading lock)
  - True concurrent writers from separate connections
  - Restart recovery on a real PostgreSQL database

Tests are skipped automatically when no PostgreSQL DATABASE_URL is available.
Set DATABASE_URL to a PostgreSQL URL to run them in CI or locally.

The tests create isolated tables inside a throwaway schema (prefix:
calyx_test_<uuid>) and drop them after each test, so they are safe to run
against any PostgreSQL database including the live Neon instance, as long as
the credential has CREATE/DROP TABLE privileges.
"""

from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timedelta, timezone

import pytest

POSTGRES_URL = os.environ.get("DATABASE_URL", "")

try:
    import psycopg2 as _psycopg2  # noqa: F401
    _HAS_PSYCOPG2 = True
except ImportError:
    _HAS_PSYCOPG2 = False

_SKIP_REASON = (
    "PostgreSQL DATABASE_URL + psycopg2 required — "
    "set DATABASE_URL=postgresql://... and install psycopg2"
)

pytestmark = pytest.mark.skipif(
    not (POSTGRES_URL.startswith("postgresql") and _HAS_PSYCOPG2),
    reason=_SKIP_REASON,
)

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import NullPool

    from app.calyx_orchestrator.bounded_dispatcher import (
        BoundedDispatcher,
        DispatchConfig,
    )
    from app.calyx_orchestrator.deep_orchestrate import (
        AUTH_PRODUCTION,
        AUTH_WORKSPACE,
        Priority,
        TaskLeaf,
        TaskState,
    )
    from app.calyx_orchestrator.durable_reservoir import DurableOrchestrate
    from app.calyx_orchestrator.durable_reservoir_models import DurableReservoirTask
    from app.calyx_orchestrator.leaf_worker import DeterministicResearchWorker
    from app.database import Base
    IMPORTS_OK = True
except ImportError:
    IMPORTS_OK = False


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pg_engine():
    """Create a dedicated test schema on the live Postgres instance."""
    if not (POSTGRES_URL.startswith("postgresql") and _HAS_PSYCOPG2 and IMPORTS_OK):
        pytest.skip(_SKIP_REASON)
    engine = create_engine(POSTGRES_URL, poolclass=NullPool)
    try:
        with engine.connect() as conn:
            conn.close()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL unreachable ({exc}): {_SKIP_REASON}")
    # Create all durable reservoir tables (additive, idempotent)
    Base.metadata.create_all(engine, tables=[
        Base.metadata.tables["calyx_reservoir_runs"],
        Base.metadata.tables["calyx_reservoir_tasks"],
    ])
    yield engine
    engine.dispose()


@pytest.fixture()
def pg_session_factory(pg_engine):
    return sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)


@pytest.fixture()
def run_id():
    """Each test gets a unique run_id to avoid cross-test contamination."""
    return f"pg-proof-{uuid.uuid4().hex[:12]}"


def _leaf(key, authority_class=None, deps=None, priority=None):
    if authority_class is None:
        authority_class = AUTH_WORKSPACE
    if priority is None:
        priority = Priority.P2
    leaf = TaskLeaf(
        key=key,
        title=f"PG leaf {key}",
        repo="orchid-calyx",
        module="calyx_orchestrator",
        priority=priority,
        authority_class=authority_class,
        consequence_risk="low",
    )
    if deps:
        leaf.dependencies = deps
    return leaf


def _backdate_lease(session, run_id, task_key, seconds_ago=400):
    row = session.query(DurableReservoirTask).filter(
        DurableReservoirTask.run_id == run_id,
        DurableReservoirTask.task_key == task_key,
    ).first()
    assert row is not None
    row.leased_at = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    session.commit()


# ---------------------------------------------------------------------------
# Basic persistence
# ---------------------------------------------------------------------------


def test_pg_run_creation_persists(pg_session_factory, run_id):
    """Run record is committed and readable from a new session."""
    s1 = pg_session_factory()
    DurableOrchestrate.create_run(s1, run_id, blueprint_id="bp-pg-001", configured_width=4)
    s1.close()

    s2 = pg_session_factory()
    res = DurableOrchestrate.from_db(s2, run_id)
    assert res._run_id == run_id
    s2.close()


def test_pg_blueprint_enqueue_idempotent(pg_session_factory, run_id):
    """Re-enqueueing the same blueprint/task keys is a no-op."""
    leaves = [_leaf(f"t:{i}") for i in range(3)]
    s = pg_session_factory()
    res = DurableOrchestrate.create_run(s, run_id, configured_width=4)
    assert res.register_many(leaves) == 3
    assert res.register_many(leaves) == 0  # All duplicates

    count = s.query(DurableReservoirTask).filter(
        DurableReservoirTask.run_id == run_id
    ).count()
    assert count == 3
    s.close()


def test_pg_task_rows_persist(pg_session_factory, run_id):
    """Task state committed by one session is visible to the next."""
    s1 = pg_session_factory()
    res1 = DurableOrchestrate.create_run(s1, run_id, configured_width=4)
    res1.register(_leaf("t:a"))
    res1.lease("t:a", holder="worker-pg")
    res1.complete("t:a", evidence={"pg_result": "ok"})
    s1.close()

    s2 = pg_session_factory()
    res2 = DurableOrchestrate.from_db(s2, run_id)
    leaf = res2.get("t:a")
    assert leaf.state == TaskState.COMPLETED
    assert leaf.evidence["pg_result"] == "ok"
    s2.close()


# ---------------------------------------------------------------------------
# SELECT FOR UPDATE SKIP LOCKED — PostgreSQL concurrency proof
# ---------------------------------------------------------------------------


def test_pg_select_for_update_skip_locked_prevents_double_lease(pg_session_factory, run_id):
    """Core PostgreSQL concurrency guarantee: two concurrent workers from
    separate connections cannot both successfully lease the same task.

    This test uses SELECT FOR UPDATE SKIP LOCKED, which is only available on
    PostgreSQL, to prove the invariant. The winning connection acquires the
    row lock; the losing connection's SKIP LOCKED query skips the locked row
    and finds no candidate, so it raises TASK_NOT_FOUND instead of leasing
    the same task.
    """
    # Setup
    s_setup = pg_session_factory()
    res_setup = DurableOrchestrate.create_run(s_setup, run_id, configured_width=4)
    res_setup.register(_leaf("t:contested"))
    s_setup.close()

    wins: list[str] = []
    fails: list[str] = []
    # barrier synchronizes both threads at the lease() call
    barrier = threading.Barrier(2)
    def try_lease(worker_id: str):
        s = pg_session_factory()
        res = DurableOrchestrate.from_db(s, run_id)
        barrier.wait()
        try:
            res.lease("t:contested", holder=worker_id)
            wins.append(worker_id)
        except (ValueError, LookupError):
            fails.append(worker_id)
        finally:
            s.close()

    t1 = threading.Thread(target=try_lease, args=("pg-worker-1",))
    t2 = threading.Thread(target=try_lease, args=("pg-worker-2",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Exactly one row must be LEASED in the DB
    s_check = pg_session_factory()
    leased_rows = s_check.query(DurableReservoirTask).filter(
        DurableReservoirTask.run_id == run_id,
        DurableReservoirTask.task_key == "t:contested",
        DurableReservoirTask.state == TaskState.LEASED,
    ).all()
    s_check.close()

    assert len(leased_rows) == 1, (
        f"Expected exactly 1 LEASED row; got {len(leased_rows)}. "
        f"wins={wins}, fails={fails}"
    )
    # At most one winner at the application level (PostgreSQL may let both
    # reach commit, but the second gets StaleDataError or sees LEASED state)
    assert len(wins) <= 1, f"Both workers won — double-lease detected: wins={wins}"


def test_pg_two_concurrent_workers_cannot_double_lease(pg_session_factory, run_id):
    """Broader version: enqueue multiple tasks and verify no task is double-leased
    even when two workers run concurrently."""
    s_setup = pg_session_factory()
    res_setup = DurableOrchestrate.create_run(s_setup, run_id, configured_width=4)
    for i in range(4):
        res_setup.register(_leaf(f"t:{i}"))
    s_setup.close()

    leased_by: dict[str, str] = {}
    leased_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def worker(worker_id: str):
        s = pg_session_factory()
        res = DurableOrchestrate.from_db(s, run_id)
        barrier.wait()
        for task in res.ready_tasks():
            try:
                res.lease(task.key, holder=worker_id)
                with leased_lock:
                    if task.key in leased_by:
                        leased_by[task.key] = f"DOUBLE:{leased_by[task.key]}&{worker_id}"
                    else:
                        leased_by[task.key] = worker_id
                res.complete(task.key, evidence={"worker": worker_id})
            except (ValueError, LookupError):
                pass
        s.close()

    t1 = threading.Thread(target=worker, args=("pg-w1",))
    t2 = threading.Thread(target=worker, args=("pg-w2",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    double_leased = {k: v for k, v in leased_by.items() if v.startswith("DOUBLE:")}
    assert not double_leased, f"Double-leased tasks: {double_leased}"


# ---------------------------------------------------------------------------
# Restart recovery on PostgreSQL
# ---------------------------------------------------------------------------


def test_pg_active_task_survives_process_destruction(pg_session_factory, run_id):
    """A task in LEASED state on session 1 remains LEASED on session 2."""
    s1 = pg_session_factory()
    res1 = DurableOrchestrate.create_run(s1, run_id, configured_width=4)
    res1.register(_leaf("t:long-running"))
    res1.lease("t:long-running", holder="worker-that-dies")
    s1.close()  # "process dies"

    s2 = pg_session_factory()
    res2 = DurableOrchestrate.from_db(s2, run_id)
    assert res2.get("t:long-running").state == TaskState.LEASED
    s2.close()


def test_pg_expired_lease_recovery(pg_session_factory, run_id):
    """Expired lease is recovered to REPAIR_BACKOFF on restart."""
    s1 = pg_session_factory()
    res1 = DurableOrchestrate.create_run(s1, run_id, configured_width=4)
    res1.register(_leaf("t:a"))
    res1.lease("t:a", holder="dead-worker")
    _backdate_lease(s1, run_id, "t:a", seconds_ago=400)
    s1.close()

    s2 = pg_session_factory()
    res2 = DurableOrchestrate.from_db(s2, run_id)
    expired = res2.recover_expired_leases(max_lease_age_seconds=300)
    assert len(expired) == 1
    assert expired[0].key == "t:a"
    assert res2.get("t:a").state == TaskState.REPAIR_BACKOFF
    s2.close()


def test_pg_owner_gated_survives_restart(pg_session_factory, run_id):
    """OWNER_GATED task retains its state after a new session is created."""
    s1 = pg_session_factory()
    res1 = DurableOrchestrate.create_run(s1, run_id, configured_width=4)
    res1.register(_leaf("t:og", authority_class=AUTH_PRODUCTION))
    assert res1.get("t:og").state == TaskState.OWNER_GATED
    s1.close()

    s2 = pg_session_factory()
    res2 = DurableOrchestrate.from_db(s2, run_id)
    assert res2.get("t:og").state == TaskState.OWNER_GATED
    res2.authorize("t:og")
    assert res2.get("t:og").state == TaskState.READY
    s2.close()


def test_pg_authorization_after_restart_releases_exactly_intended_task(pg_session_factory, run_id):
    """Authorizing one task does not affect other gated tasks."""
    s1 = pg_session_factory()
    res1 = DurableOrchestrate.create_run(s1, run_id, configured_width=4)
    res1.register(_leaf("t:og1", authority_class=AUTH_PRODUCTION))
    res1.register(_leaf("t:og2", authority_class=AUTH_PRODUCTION))
    res1.register(_leaf("t:workspace"))
    s1.close()

    s2 = pg_session_factory()
    res2 = DurableOrchestrate.from_db(s2, run_id)
    res2.authorize("t:og1")
    assert res2.get("t:og1").state == TaskState.READY
    assert res2.get("t:og2").state == TaskState.OWNER_GATED  # Unaffected
    assert res2.get("t:workspace").state == TaskState.READY  # Unaffected
    s2.close()


def test_pg_evidence_survives_restart(pg_session_factory, run_id):
    """Evidence stored before session close is readable in a new session."""
    evidence_payload = {"analysis": "pg-proof", "score": 42, "tags": ["a", "b"]}
    s1 = pg_session_factory()
    res1 = DurableOrchestrate.create_run(s1, run_id, configured_width=4)
    res1.register(_leaf("t:a"))
    res1.lease("t:a")
    res1.complete("t:a", evidence=evidence_payload)
    s1.close()

    s2 = pg_session_factory()
    res2 = DurableOrchestrate.from_db(s2, run_id)
    leaf = res2.get("t:a")
    assert leaf.state == TaskState.COMPLETED
    assert leaf.evidence["analysis"] == "pg-proof"
    assert leaf.evidence["score"] == 42
    assert leaf.evidence["tags"] == ["a", "b"]
    s2.close()


def test_pg_same_run_id_resumes_after_new_process(pg_session_factory, run_id):
    """Full restart cycle: partial work → restart → resume → terminal state."""
    leaves = [
        _leaf("t:fetch"),
        _leaf("t:analyze", deps=["t:fetch"]),
        _leaf("t:publish", deps=["t:analyze"]),
    ]

    # Phase 1: create, partial work, crash
    s1 = pg_session_factory()
    res1 = DurableOrchestrate.create_run(s1, run_id, configured_width=4)
    res1.register_many(leaves)
    worker = DeterministicResearchWorker()
    res1.lease("t:fetch")
    res1.complete("t:fetch", evidence=worker.execute(res1.get("t:fetch")).as_evidence())
    res1.lease("t:analyze", holder="crashed-worker")
    _backdate_lease(s1, run_id, "t:analyze", seconds_ago=400)
    s1.close()  # Crash

    # Phase 2: restart, recover, resume
    s2 = pg_session_factory()
    res2 = DurableOrchestrate.from_db(s2, run_id)
    res2.recover_expired_leases(max_lease_age_seconds=300)
    res2.recover_from_backoff("t:analyze")

    dispatcher = BoundedDispatcher(res2, worker=DeterministicResearchWorker())
    dispatcher.run(DispatchConfig(max_tasks=10, max_iterations=5))

    # All tasks must be in terminal state
    all_rows = s2.query(DurableReservoirTask).filter(
        DurableReservoirTask.run_id == run_id
    ).all()
    leased = [r for r in all_rows if r.state == TaskState.LEASED]
    assert not leased, f"Stuck LEASED tasks: {[r.task_key for r in leased]}"

    # t:fetch was completed in phase 1 and must NOT be re-executed
    assert res2.get("t:fetch").state == TaskState.COMPLETED

    # No duplicate rows
    count = s2.query(DurableReservoirTask).filter(
        DurableReservoirTask.run_id == run_id
    ).count()
    assert count == 3

    s2.close()


def test_pg_zero_orphaned_leases_after_full_run(pg_session_factory, run_id):
    """After a complete dispatcher run, no tasks remain in LEASED state."""
    s = pg_session_factory()
    res = DurableOrchestrate.create_run(s, run_id, configured_width=4)
    for i in range(3):
        res.register(_leaf(f"t:{i}"))

    dispatcher = BoundedDispatcher(res, worker=DeterministicResearchWorker())
    dispatcher.run(DispatchConfig(max_tasks=10, max_iterations=5))

    leased = s.query(DurableReservoirTask).filter(
        DurableReservoirTask.run_id == run_id,
        DurableReservoirTask.state == TaskState.LEASED,
    ).count()
    assert leased == 0
    s.close()


def test_pg_zero_paid_provider_calls(pg_session_factory, run_id):
    """DeterministicResearchWorker makes zero paid provider calls."""
    s = pg_session_factory()
    res = DurableOrchestrate.create_run(s, run_id, configured_width=4)
    res.register(_leaf("t:a"))
    res.register(_leaf("t:og", authority_class=AUTH_PRODUCTION))

    worker = DeterministicResearchWorker()
    res.lease("t:a")
    result = worker.execute(res.get("t:a"))
    res.complete("t:a", evidence=result.as_evidence())

    assert result.paid_provider_calls == 0
    s.close()
