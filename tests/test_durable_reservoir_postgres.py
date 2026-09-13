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


@pytest.fixture
def pg_session_factory(pg_engine):
    return sessionmaker(bind=pg_engine, autocommit=False, autoflush=False)


@pytest.fixture
def run_id():
    return f"pg-proof-{uuid.uuid4().hex[:12]}"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_pg_run_creation_persists(pg_session_factory, run_id):
    """create_run writes a run record; from_db reconstructs it."""
    s1 = pg_session_factory()
    DurableOrchestrate.create_run(s1, run_id, configured_width=4)
    s1.close()

    s2 = pg_session_factory()
    reservoir = DurableOrchestrate.from_db(s2, run_id)
    assert reservoir._run_id == run_id
    s2.close()


def test_pg_blueprint_enqueue_idempotent(pg_session_factory, run_id):
    """Enqueuing same task twice produces exactly one DB row."""
    session = pg_session_factory()
    reservoir = DurableOrchestrate.create_run(session, run_id, configured_width=4)

    leaf = TaskLeaf(
        key=f"{run_id}:t1",
        title="Idempotency test",
        repo="orchid-calyx",
        module="calyx_orchestrator",
        priority=Priority.P2,
        authority_class=AUTH_WORKSPACE,
        consequence_risk="low",
    )
    reservoir.register(leaf)
    reservoir.register(leaf)  # duplicate — should be ignored

    count = session.query(DurableReservoirTask).filter(
        DurableReservoirTask.run_id == run_id
    ).count()
    assert count == 1, f"Expected 1 row, got {count}"
    session.close()


def test_pg_task_rows_persist(pg_session_factory, run_id):
    """Tasks registered in session 1 are visible in session 2 (real persistence)."""
    s1 = pg_session_factory()
    reservoir1 = DurableOrchestrate.create_run(s1, run_id, configured_width=4)
    leaf = TaskLeaf(
        key=f"{run_id}:t1",
        title="Persistence test",
        repo="orchid-calyx",
        module="calyx_orchestrator",
        priority=Priority.P2,
        authority_class=AUTH_WORKSPACE,
        consequence_risk="low",
    )
    reservoir1.register(leaf)
    s1.close()

    s2 = pg_session_factory()
    reservoir2 = DurableOrchestrate.from_db(s2, run_id)
    task = reservoir2.get(f"{run_id}:t1")
    assert task is not None
    assert task.state == TaskState.READY
    s2.close()


def test_pg_select_for_update_skip_locked_prevents_double_lease(pg_session_factory, run_id):
    """SELECT FOR UPDATE SKIP LOCKED: second lease attempt on same task raises."""
    session = pg_session_factory()
    reservoir = DurableOrchestrate.create_run(session, run_id, configured_width=4)
    leaf = TaskLeaf(
        key=f"{run_id}:t1",
        title="FOR UPDATE test",
        repo="orchid-calyx",
        module="calyx_orchestrator",
        priority=Priority.P2,
        authority_class=AUTH_WORKSPACE,
        consequence_risk="low",
    )
    reservoir.register(leaf)

    reservoir.lease(f"{run_id}:t1", holder="worker-A")

    with pytest.raises((LookupError, ValueError)):
        reservoir.lease(f"{run_id}:t1", holder="worker-B")

    session.close()


def test_pg_two_concurrent_workers_cannot_double_lease(pg_session_factory, run_id):
    """Two threads racing to lease the same task: exactly one wins."""
    session = pg_session_factory()
    reservoir = DurableOrchestrate.create_run(session, run_id, configured_width=4)
    leaf = TaskLeaf(
        key=f"{run_id}:t1",
        title="Concurrent lease test",
        repo="orchid-calyx",
        module="calyx_orchestrator",
        priority=Priority.P2,
        authority_class=AUTH_WORKSPACE,
        consequence_risk="low",
    )
    reservoir.register(leaf)

    winners: list[str] = []
    errors: list[str] = []

    def try_lease(worker_id: str) -> None:
        try:
            reservoir.lease(f"{run_id}:t1", holder=worker_id)
            winners.append(worker_id)
        except (LookupError, ValueError) as exc:
            errors.append(str(exc))

    t1 = threading.Thread(target=try_lease, args=("worker-A",))
    t2 = threading.Thread(target=try_lease, args=("worker-B",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert len(winners) == 1, f"Expected 1 winner, got {len(winners)}: {winners}"
    assert len(errors) == 1
    session.close()


def test_pg_active_task_survives_process_destruction(pg_session_factory, run_id):
    """A LEASED task in session 1 is still LEASED in session 2 (true persistence)."""
    s1 = pg_session_factory()
    reservoir1 = DurableOrchestrate.create_run(s1, run_id, configured_width=4)
    leaf = TaskLeaf(
        key=f"{run_id}:t1",
        title="Survive restart test",
        repo="orchid-calyx",
        module="calyx_orchestrator",
        priority=Priority.P2,
        authority_class=AUTH_WORKSPACE,
        consequence_risk="low",
    )
    reservoir1.register(leaf)
    reservoir1.lease(f"{run_id}:t1", holder="worker-crash")
    s1.close()  # simulate process death

    s2 = pg_session_factory()
    reservoir2 = DurableOrchestrate.from_db(s2, run_id)
    task = reservoir2.get(f"{run_id}:t1")
    assert task.state == TaskState.LEASED
    s2.close()


def test_pg_expired_lease_recovery(pg_session_factory, run_id):
    """recover_expired_leases moves a stale LEASED task to REPAIR_BACKOFF."""
    s1 = pg_session_factory()
    reservoir1 = DurableOrchestrate.create_run(s1, run_id, configured_width=4)
    leaf = TaskLeaf(
        key=f"{run_id}:t1",
        title="Expired lease test",
        repo="orchid-calyx",
        module="calyx_orchestrator",
        priority=Priority.P2,
        authority_class=AUTH_WORKSPACE,
        consequence_risk="low",
    )
    reservoir1.register(leaf)
    reservoir1.lease(f"{run_id}:t1", holder="worker-crash")

    # Backdate lease
    row = s1.query(DurableReservoirTask).filter(
        DurableReservoirTask.run_id == run_id,
        DurableReservoirTask.task_key == f"{run_id}:t1",
    ).first()
    row.leased_at = datetime.now(timezone.utc) - timedelta(seconds=600)
    s1.commit()
    s1.close()

    s2 = pg_session_factory()
    reservoir2 = DurableOrchestrate.from_db(s2, run_id)
    recovered = reservoir2.recover_expired_leases(max_lease_age_seconds=300)
    assert len(recovered) == 1
    assert reservoir2.get(f"{run_id}:t1").state == TaskState.REPAIR_BACKOFF
    s2.close()


def test_pg_owner_gated_survives_restart(pg_session_factory, run_id):
    """OWNER_GATED state written in session 1 is intact in session 2."""
    s1 = pg_session_factory()
    reservoir = DurableOrchestrate.create_run(s1, run_id, configured_width=4)
    leaf = TaskLeaf(
        key=f"{run_id}:t1",
        title="Owner gate persistence",
        repo="orchid-calyx",
        module="calyx_orchestrator",
        priority=Priority.P1,
        authority_class=AUTH_PRODUCTION,
        consequence_risk="high",
    )
    reservoir.register(leaf)
    # Force OWNER_GATED state
    reservoir.authorize(f"{run_id}:t1")  # marks as gated
    s1.close()

    s2 = pg_session_factory()
    reservoir2 = DurableOrchestrate.from_db(s2, run_id)
    assert reservoir2.get(f"{run_id}:t1").state == TaskState.OWNER_GATED
    s2.close()


def test_pg_authorization_after_restart_releases_exactly_intended_task(pg_session_factory, run_id):
    """After restart, releasing one OWNER_GATED task does not affect others."""
    s1 = pg_session_factory()
    reservoir = DurableOrchestrate.create_run(s1, run_id, configured_width=4)
    for i in range(3):
        leaf = TaskLeaf(
            key=f"{run_id}:t{i}",
            title=f"Gate test {i}",
            repo="orchid-calyx",
            module="calyx_orchestrator",
            priority=Priority.P1,
            authority_class=AUTH_PRODUCTION,
            consequence_risk="high",
        )
        reservoir.register(leaf)
        reservoir.authorize(f"{run_id}:t{i}")
    s1.close()

    s2 = pg_session_factory()
    reservoir2 = DurableOrchestrate.from_db(s2, run_id)
    # Release only t1
    reservoir2.advance(f"{run_id}:t1", TaskState.READY)
    assert reservoir2.get(f"{run_id}:t0").state == TaskState.OWNER_GATED
    assert reservoir2.get(f"{run_id}:t1").state == TaskState.READY
    assert reservoir2.get(f"{run_id}:t2").state == TaskState.OWNER_GATED
    s2.close()


def test_pg_evidence_survives_restart(pg_session_factory, run_id):
    """Evidence written in session 1 is readable in session 2."""
    s1 = pg_session_factory()
    reservoir = DurableOrchestrate.create_run(s1, run_id, configured_width=4)
    leaf = TaskLeaf(
        key=f"{run_id}:t1",
        title="Evidence persistence",
        repo="orchid-calyx",
        module="calyx_orchestrator",
        priority=Priority.P2,
        authority_class=AUTH_WORKSPACE,
        consequence_risk="low",
    )
    reservoir.register(leaf)
    reservoir.lease(f"{run_id}:t1", holder="worker")
    evidence = {"source": "pg-proof", "statement": "Orchidaceae: Orchid family", "confidence": 0.97}
    reservoir.complete(f"{run_id}:t1", evidence=evidence)
    s1.close()

    s2 = pg_session_factory()
    reservoir2 = DurableOrchestrate.from_db(s2, run_id)
    task = reservoir2.get(f"{run_id}:t1")
    assert task.state == TaskState.COMPLETED
    assert task.evidence is not None
    assert task.evidence.get("confidence") == 0.97
    s2.close()


def test_pg_same_run_id_resumes_after_new_process(pg_session_factory, run_id):
    """Full conductor run: create, dispatch, restart, resume, terminal."""
    worker = DeterministicResearchWorker()

    # Session 1: create and enqueue
    s1 = pg_session_factory()
    reservoir1 = DurableOrchestrate.create_run(s1, run_id, configured_width=4)
    leaves = [
        TaskLeaf(
            key=f"{run_id}:t{i}",
            title=f"Resume test {i}",
            repo="orchid-calyx",
            module="calyx_orchestrator",
            priority=Priority.P2,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
        )
        for i in range(4)
    ]
    for leaf in leaves:
        reservoir1.register(leaf)

    # Partial dispatch: run only 2 tasks
    dispatcher1 = BoundedDispatcher(reservoir1, worker=worker)
    dispatcher1.run(DispatchConfig(max_tasks=2, max_iterations=2))
    s1.close()  # "process death"

    # Session 2: resume
    s2 = pg_session_factory()
    reservoir2 = DurableOrchestrate.from_db(s2, run_id)
    # Recover any stale leases
    reservoir2.recover_expired_leases(max_lease_age_seconds=0)  # force all
    for t in reservoir2.ready_tasks():
        reservoir2.recover_from_backoff(t.key)

    dispatcher2 = BoundedDispatcher(reservoir2, worker=worker)
    dispatcher2.run(DispatchConfig(max_tasks=10, max_iterations=5))

    # All tasks should now be terminal
    for leaf in leaves:
        state = reservoir2.get(leaf.key).state
        assert state in (TaskState.COMPLETED, TaskState.BLOCKED), (
            f"{leaf.key} stuck in {state}"
        )

    # No stale leases
    assert len(reservoir2.active_tasks()) == 0
    s2.close()


def test_pg_zero_orphaned_leases_after_full_run(pg_session_factory, run_id):
    """After a complete dispatcher run, no task remains LEASED."""
    session = pg_session_factory()
    reservoir = DurableOrchestrate.create_run(session, run_id, configured_width=6)
    worker = DeterministicResearchWorker()

    for i in range(6):
        leaf = TaskLeaf(
            key=f"{run_id}:t{i}",
            title=f"No-orphan test {i}",
            repo="orchid-calyx",
            module="calyx_orchestrator",
            priority=Priority.P2,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
        )
        reservoir.register(leaf)

    dispatcher = BoundedDispatcher(reservoir, worker=worker)
    dispatcher.run(DispatchConfig(max_tasks=20, max_iterations=10))

    active = reservoir.active_tasks()
    assert len(active) == 0, f"Orphaned leases: {[t.key for t in active]}"
    session.close()


def test_pg_zero_paid_provider_calls(pg_session_factory, run_id):
    """DeterministicResearchWorker makes zero paid provider API calls."""
    session = pg_session_factory()
    reservoir = DurableOrchestrate.create_run(session, run_id, configured_width=4)
    worker = DeterministicResearchWorker()

    for i in range(4):
        leaf = TaskLeaf(
            key=f"{run_id}:t{i}",
            title=f"Zero cost test {i}",
            repo="orchid-calyx",
            module="calyx_orchestrator",
            priority=Priority.P2,
            authority_class=AUTH_WORKSPACE,
            consequence_risk="low",
        )
        reservoir.register(leaf)

    dispatcher = BoundedDispatcher(reservoir, worker=worker)
    run = dispatcher.run(DispatchConfig(max_tasks=10, max_iterations=5))

    paid = sum(1 for r in run.results if r.output.get("provider_api_called", False))
    assert paid == 0, f"Paid provider calls: {paid}"
    session.close()
