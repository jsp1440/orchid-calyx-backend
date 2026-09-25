"""DurableOrchestrate — PostgreSQL-backed task reservoir for the autonomous loop.

Drop-in replacement for DeepOrchestrate. Every state transition is committed to
the database, so an AutonomousResearchRun can survive process restart, container
recycle, worker crash, or deployment and resume without losing task state.

API compatibility:
  DurableOrchestrate exposes exactly the same public methods as DeepOrchestrate:
  register, register_many, ready_tasks, active_tasks, owner_gated_tasks,
  blocked_tasks, get, held_resources, lease, advance, complete, block,
  enter_repair_backoff, recover_from_backoff, recover_expired_leases, authorize,
  refill, snapshot, to_dict.

  BoundedDispatcher, OwnerAuthorizationGate, and AutonomousResearchRun all accept
  either class without modification (they duck-type the reservoir).

Concurrency:
  On PostgreSQL, lease() uses SELECT ... FOR UPDATE SKIP LOCKED so two concurrent
  workers cannot double-lease the same task. On SQLite (used in tests), the
  threading lock provides equivalent single-process protection.

Idempotency:
  register() / register_many() are INSERT-or-ignore: re-enqueueing the same
  (run_id, task_key) is a no-op. Restart and resume are safe.

Usage::

    from sqlalchemy.orm import Session
    from app.calyx_orchestrator.durable_reservoir import DurableOrchestrate
    from app.calyx_orchestrator.durable_reservoir_models import (
        DurableReservoirRun, DurableReservoirTask,
    )

    # First run — create the run record and enqueue tasks.
    reservoir = DurableOrchestrate.create_run(
        session, run_id="run-001", blueprint_id="bp-abc", configured_width=8
    )
    # ... register tasks, dispatch, save run_id ...

    # After restart — reconstruct from DB.
    reservoir = DurableOrchestrate.from_db(session, run_id="run-001")
    # Resume dispatch — expired leases are recovered, OWNER_GATED state is intact.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import exc as sa_exc
from sqlalchemy.orm import Session

from .deep_orchestrate import (
    _ACTIVE,
    _OWNER_GATE_CLASSES,
    TaskLeaf,
    TaskState,
)
from .durable_reservoir_models import (
    DurableReservoirRun,
    DurableReservoirTask,
    _utcnow,
)

log = logging.getLogger(__name__)

DURABLE_SCHEMA_VERSION = "calyx-durable-reservoir/v1"


# SQLite has no server-side row locking and, when several sessions share one
# connection, no support for concurrent transactions either. A lock held on the
# DurableOrchestrate instance cannot help: competing workers hold *different*
# instances and so never contend on it. Serializing non-PostgreSQL lease
# acquisition process-wide is therefore the only correct option, and costs
# nothing, because SQLite cannot execute those writes in parallel anyway.
# PostgreSQL deployments skip this entirely and rely on the database.
_SQLITE_LEASE_LOCK = threading.RLock()


class _NullLock:
    """No-op stand-in used where the database itself provides the guarantee."""

    def __enter__(self) -> None:
        return None

    def __exit__(self, *exc: object) -> bool:
        return False


_NULL_LEASE_LOCK = _NullLock()


@dataclass(frozen=True, slots=True)
class SettlementResult:
    """Outcome of a completion attempt.

    ``settled`` is True exactly once per task, for the write that actually
    moved it into COMPLETED. Every later replay reports ``duplicate`` so the
    caller can record the suppression instead of counting it as new progress.
    """

    leaf: TaskLeaf
    settled: bool
    duplicate: bool


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _ts_to_dt(ts: float | None) -> datetime | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _dt_to_ts(dt: datetime | None) -> float | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _row_to_leaf(row: DurableReservoirTask) -> TaskLeaf:
    """Convert a DB row back to a TaskLeaf."""
    leaf = TaskLeaf(
        key=row.task_key,
        title=row.title,
        repo=row.repo,
        module=row.module,
        priority=row.priority,
        authority_class=row.authority_class,
        consequence_risk=row.consequence_risk,
        providers=list(row.providers or []),
        estimated_size=row.estimated_size or "m",
        dependencies=list(row.dependencies or []),
        acceptance_criteria=list(row.acceptance_criteria or []),
        resources=list(row.resources or []),
        issue_number=row.issue_number,
        pr_number=row.pr_number,
    )
    leaf.state = row.state
    leaf.leased_at = _dt_to_ts(row.leased_at)
    leaf.lease_holder = row.lease_holder
    leaf.blocked_reason = row.blocked_reason
    leaf.evidence = dict(row.evidence or {})
    leaf.created_at = _dt_to_ts(row.created_at) or time.time()
    leaf.updated_at = _dt_to_ts(row.updated_at) or time.time()
    return leaf


def _is_ready_row(
    row: DurableReservoirTask, completed_keys: set[str]
) -> bool:
    if row.state != TaskState.READY:
        return False
    return all(dep in completed_keys for dep in (row.dependencies or []))


# ---------------------------------------------------------------------------
# DurableOrchestrate
# ---------------------------------------------------------------------------


class DurableOrchestrate:
    """PostgreSQL-backed task reservoir with the same API as DeepOrchestrate.

    Every public method that mutates state commits the transaction before
    returning, so callers get immediate durability without managing sessions
    themselves.

    Parameters
    ----------
    session         SQLAlchemy Session bound to a Postgres or SQLite engine.
    run_id          Stable identifier for this autonomous research run.
    configured_width  Maximum concurrent task leases (mirrors DeepOrchestrate).
    """

    def __init__(
        self,
        session: Session,
        run_id: str,
        *,
        configured_width: int = 5,
    ) -> None:
        self._session = session
        self._run_id = run_id
        self.configured_width = configured_width
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def create_run(
        cls,
        session: Session,
        run_id: str,
        *,
        blueprint_id: str = "",
        run_fingerprint: str | None = None,
        proposed_action: str = "",
        configured_width: int = 5,
    ) -> DurableOrchestrate:
        """Create a new run record (idempotent — safe to call more than once).

        If a run with this run_id already exists, the existing record is returned
        without modification. This makes the factory gate safe for retries.
        """
        existing = session.get(DurableReservoirRun, run_id)
        if existing is None:
            run = DurableReservoirRun(
                run_id=run_id,
                blueprint_id=blueprint_id,
                run_fingerprint=run_fingerprint,
                proposed_action=proposed_action,
                configured_width=configured_width,
            )
            session.add(run)
            try:
                session.commit()
            except sa_exc.IntegrityError:
                session.rollback()
                existing = session.get(DurableReservoirRun, run_id)
                configured_width = existing.configured_width if existing else configured_width
        else:
            configured_width = existing.configured_width
        return cls(session, run_id, configured_width=configured_width)

    @classmethod
    def from_db(cls, session: Session, run_id: str) -> DurableOrchestrate:
        """Reconstruct the reservoir from an existing DB run (restart recovery).

        The returned object is ready to use immediately:
        - COMPLETED tasks are already terminal.
        - OWNER_GATED tasks are still gated.
        - LEASED/RUNNING tasks with expired leases need recover_expired_leases().
        - READY tasks are dispatched normally via BoundedDispatcher.

        Raises LookupError if the run_id is not found.
        """
        run = session.get(DurableReservoirRun, run_id)
        if run is None:
            raise LookupError(f"DURABLE_RUN_NOT_FOUND:{run_id}")
        return cls(session, run_id, configured_width=run.configured_width)

    # ------------------------------------------------------------------
    # Internal DB helpers
    # ------------------------------------------------------------------

    def _all_rows(self) -> list[DurableReservoirTask]:
        return (
            self._session.query(DurableReservoirTask)
            .filter(DurableReservoirTask.run_id == self._run_id)
            .all()
        )

    def _get_row(self, key: str) -> DurableReservoirTask | None:
        return (
            self._session.query(DurableReservoirTask)
            .filter(
                DurableReservoirTask.run_id == self._run_id,
                DurableReservoirTask.task_key == key,
            )
            .first()
        )

    def _completed_keys(self) -> set[str]:
        rows = (
            self._session.query(DurableReservoirTask.task_key)
            .filter(
                DurableReservoirTask.run_id == self._run_id,
                DurableReservoirTask.state == TaskState.COMPLETED,
            )
            .all()
        )
        return {r.task_key for r in rows}

    def _held_resources_from(self, rows: list[DurableReservoirTask]) -> frozenset[str]:
        held: set[str] = set()
        for r in rows:
            if r.state in _ACTIVE:
                held.update(r.resources or [])
        return frozenset(held)

    def _dialect_name(self) -> str:
        try:
            return self._session.bind.dialect.name  # type: ignore[union-attr]
        except AttributeError:
            return "unknown"

    def _commit(self) -> None:
        self._session.commit()

    # ------------------------------------------------------------------
    # Registration (idempotent)
    # ------------------------------------------------------------------

    def register(self, leaf: TaskLeaf) -> bool:
        """Add a task leaf to the reservoir.

        Returns True if newly registered, False if key already exists (dedupe).
        Idempotent: calling register() with the same key is always safe.
        """
        with self._lock:
            if self._get_row(leaf.key) is not None:
                return False
            state = leaf.state
            if leaf.requires_owner_gate and state == TaskState.READY:
                state = TaskState.OWNER_GATED
            row = DurableReservoirTask(
                run_id=self._run_id,
                task_key=leaf.key,
                title=leaf.title,
                repo=leaf.repo,
                module=leaf.module,
                priority=leaf.priority,
                authority_class=leaf.authority_class,
                consequence_risk=leaf.consequence_risk,
                providers=list(leaf.providers),
                estimated_size=leaf.estimated_size,
                dependencies=list(leaf.dependencies),
                acceptance_criteria=list(leaf.acceptance_criteria),
                resources=list(leaf.resources),
                issue_number=leaf.issue_number,
                pr_number=leaf.pr_number,
                state=state,
                leased_at=_ts_to_dt(leaf.leased_at),
                lease_holder=leaf.lease_holder,
                blocked_reason=leaf.blocked_reason,
                evidence=dict(leaf.evidence),
                created_at=_ts_to_dt(leaf.created_at),
                updated_at=_ts_to_dt(leaf.updated_at),
            )
            self._session.add(row)
            try:
                self._session.flush()
                self._commit()
            except sa_exc.IntegrityError:
                self._session.rollback()
                return False
            return True

    def register_many(self, leaves: list[TaskLeaf]) -> int:
        """Register multiple leaves; returns count of newly registered."""
        return sum(1 for leaf in leaves if self.register(leaf))

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def ready_tasks(self, *, limit: int | None = None) -> list[TaskLeaf]:
        """Return READY tasks (all deps completed), ordered by (priority, created_at)."""
        with self._lock:
            completed = self._completed_keys()
            all_rows = self._all_rows()
            ready = [r for r in all_rows if _is_ready_row(r, completed)]
            ready.sort(key=lambda r: (r.priority, r.created_at or datetime.min.replace(tzinfo=timezone.utc)))
            if limit is not None:
                ready = ready[:limit]
            return [_row_to_leaf(r) for r in ready]

    def active_tasks(self) -> list[TaskLeaf]:
        """Tasks currently leased, running, or validating."""
        rows = (
            self._session.query(DurableReservoirTask)
            .filter(
                DurableReservoirTask.run_id == self._run_id,
                DurableReservoirTask.state.in_(list(_ACTIVE)),
            )
            .all()
        )
        return [_row_to_leaf(r) for r in rows]

    def owner_gated_tasks(self) -> list[TaskLeaf]:
        rows = (
            self._session.query(DurableReservoirTask)
            .filter(
                DurableReservoirTask.run_id == self._run_id,
                DurableReservoirTask.state == TaskState.OWNER_GATED,
            )
            .all()
        )
        return [_row_to_leaf(r) for r in rows]

    def blocked_tasks(self) -> list[TaskLeaf]:
        rows = (
            self._session.query(DurableReservoirTask)
            .filter(
                DurableReservoirTask.run_id == self._run_id,
                DurableReservoirTask.state == TaskState.BLOCKED,
            )
            .all()
        )
        return [_row_to_leaf(r) for r in rows]

    def repair_backoff_tasks(self) -> list[TaskLeaf]:
        """Tasks parked in REPAIR_BACKOFF awaiting reconciliation.

        ``blocked_tasks()`` deliberately reports only BLOCKED work. Without a
        lister of its own, work moved into repair backoff -- by a lease
        expiry, a validation failure, or an unreachable provider -- is
        invisible to every caller, so nothing can ever bring it back. A
        reconciler needs to be able to see what it is meant to reconcile.
        """
        rows = (
            self._session.query(DurableReservoirTask)
            .filter(
                DurableReservoirTask.run_id == self._run_id,
                DurableReservoirTask.state == TaskState.REPAIR_BACKOFF,
            )
            .all()
        )
        return [_row_to_leaf(r) for r in rows]

    def get(self, key: str) -> TaskLeaf | None:
        row = self._get_row(key)
        return _row_to_leaf(row) if row is not None else None

    def held_resources(self) -> frozenset[str]:
        """Resources exclusively held by active tasks."""
        return self._held_resources_from(self._all_rows())

    # ------------------------------------------------------------------
    # Lease / state transitions
    # ------------------------------------------------------------------

    def lease(self, key: str, *, holder: str = "claude") -> TaskLeaf:
        """Atomically lease a task.

        Acquisition is a database-level compare-and-set: the UPDATE that takes
        the lease is itself conditional on the row (by primary key) still being
        READY, and the caller wins only if that UPDATE matched exactly one row.
        Losing the race raises ``ValueError`` exactly as an ineligible task does.

        The conditional UPDATE, not the in-process lock, is what makes this
        safe. ``self._lock`` is per-instance, so two DurableOrchestrate objects
        -- two threads, two workers, two processes -- never contend on it, and
        without a guarded write both could read the task as READY and both
        believe they hold the lease. On PostgreSQL, SELECT ... FOR UPDATE SKIP
        LOCKED above narrows the window; on SQLite there is no row lock at all,
        so non-PostgreSQL acquisition is additionally serialized process-wide
        (``_SQLITE_LEASE_LOCK``). Either way the guard on the UPDATE is what
        actually prevents a double lease, and writer contention that surfaces
        as an ``OperationalError`` (SQLite "database is locked") is reported as
        ``LEASE_CONTENTION`` rather than as a lease.

        Raises:
            LookupError: task not found.
            ValueError: task not in READY state, deps unmet, resource
                conflict, or the lease race was lost to another holder.
        """
        dialect = self._dialect_name()
        serializer = (
            _NULL_LEASE_LOCK if dialect == "postgresql" else _SQLITE_LEASE_LOCK
        )
        with serializer, self._lock:
            q = self._session.query(DurableReservoirTask).filter(
                DurableReservoirTask.run_id == self._run_id,
                DurableReservoirTask.task_key == key,
            )
            if dialect == "postgresql":
                q = q.with_for_update(skip_locked=True)
            row = q.first()

            if row is None:
                raise LookupError(f"TASK_NOT_FOUND:{key}")

            completed = self._completed_keys()
            if not _is_ready_row(row, completed):
                raise ValueError(f"TASK_NOT_READY:{key}:state={row.state}")

            if row.resources:
                all_rows = self._all_rows()
                held = self._held_resources_from(all_rows)
                conflict = set(row.resources) & held
                if conflict:
                    raise ValueError(
                        f"RESOURCE_CONFLICT:{key}:resources={sorted(conflict)!r}"
                    )

            # Compare-and-swap: the transition is only applied to a row that is
            # still READY at write time. This is what makes the reservation
            # atomic across sessions/processes on every backend — FOR UPDATE
            # SKIP LOCKED above only reduces contention on PostgreSQL, while the
            # conditional UPDATE is the correctness guarantee on both PostgreSQL
            # and SQLite (whose default deferred transactions do not lock reads).
            now = _utcnow()
            try:
                claimed = (
                    self._session.query(DurableReservoirTask)
                    .filter(
                        DurableReservoirTask.id == row.id,
                        DurableReservoirTask.state == TaskState.READY,
                    )
                    .update(
                        {
                            DurableReservoirTask.state: TaskState.LEASED,
                            DurableReservoirTask.leased_at: now,
                            DurableReservoirTask.lease_holder: holder,
                            DurableReservoirTask.updated_at: now,
                        },
                        synchronize_session=False,
                    )
                )
                if claimed != 1:
                    self._session.rollback()
                    raise ValueError(f"TASK_NOT_READY:{key}:state=claimed_by_other_worker")
                self._commit()
            except sa_exc.OperationalError as exc:
                # Writer contention (e.g. SQLite "database is locked") means another
                # worker holds the write lock on this row set; the lease is not ours.
                self._session.rollback()
                raise ValueError(f"LEASE_CONTENTION:{key}") from exc
            self._session.expire(row)
            return _row_to_leaf(row)

    def advance(self, key: str, *, state: str) -> TaskLeaf:
        """Move a leased task to running or validating."""
        with self._lock:
            row = self._get_row(key)
            if row is None:
                raise LookupError(f"TASK_NOT_FOUND:{key}")
            if state not in (TaskState.RUNNING, TaskState.VALIDATING):
                raise ValueError(f"INVALID_ADVANCE_STATE:{state}")
            row.state = state
            row.updated_at = _utcnow()
            self._session.flush()
            self._commit()
            return _row_to_leaf(row)

    def settle(
        self,
        key: str,
        *,
        evidence: dict[str, Any] | None = None,
        pr_number: int | None = None,
        require_lease: bool = False,
        holder: str | None = None,
    ) -> SettlementResult:
        """Complete a task and report whether this was the settling write.

        This is the ownership-aware, replay-safe entry point to completion.
        ``complete()`` remains the DeepOrchestrate-compatible surface; this
        wrapper additionally tells the caller whether it actually settled the
        task or merely replayed an already-settled one, which the autonomous
        loop needs in order to distinguish real progress from a duplicate
        completion request.

        Args:
            require_lease: when True, refuse to settle a task that is not
                currently held under an active lease. Completion is an
                ownership-bearing act; a caller that never took the lease has
                no standing to declare the work done.
            holder: when given alongside ``require_lease``, the lease must be
                held by exactly this holder.

        Raises:
            LookupError: task not found.
            PermissionError: ``require_lease`` set and the caller does not
                hold an active lease on the task.
        """
        with self._lock:
            row = self._get_row(key)
            if row is None:
                raise LookupError(f"TASK_NOT_FOUND:{key}")
            already = row.state == TaskState.COMPLETED
            if require_lease and not already:
                if row.state not in _ACTIVE:
                    raise PermissionError(
                        f"COMPLETION_WITHOUT_LEASE:{key}:state={row.state}"
                    )
                if holder is not None and row.lease_holder != holder:
                    raise PermissionError(
                        f"COMPLETION_BY_NON_HOLDER:{key}"
                        f":holder={row.lease_holder}:claimed={holder}"
                    )
        leaf = self.complete(key, evidence=evidence, pr_number=pr_number)
        return SettlementResult(leaf=leaf, settled=not already, duplicate=already)

    def complete(
        self,
        key: str,
        *,
        evidence: dict[str, Any] | None = None,
        pr_number: int | None = None,
    ) -> TaskLeaf:
        """Mark a task completed and expose its dependents.

        Idempotent, first-writer-wins: a task that is already COMPLETED is
        returned unchanged. A replayed or duplicate completion request must
        never rewrite the evidence of work that has already been settled —
        settled evidence is the audit record of what actually happened, and
        a later writer overwriting it would silently corrupt provenance.
        """
        with self._lock:
            row = self._get_row(key)
            if row is None:
                raise LookupError(f"TASK_NOT_FOUND:{key}")
            if row.state == TaskState.COMPLETED:
                return _row_to_leaf(row)
            row.state = TaskState.COMPLETED
            row.updated_at = _utcnow()
            if evidence:
                merged = dict(row.evidence or {})
                merged.update(evidence)
                row.evidence = merged
            if pr_number is not None:
                row.pr_number = pr_number
            self._session.flush()
            self._propagate_completion(key)
            self._commit()
            return _row_to_leaf(row)

    def _propagate_completion(self, completed_key: str) -> None:
        """Unblock BLOCKED tasks whose only blocker was `completed_key`."""
        completed = self._completed_keys()
        all_rows = self._all_rows()
        for r in all_rows:
            if completed_key not in (r.dependencies or []):
                continue
            if r.state not in (TaskState.BLOCKED,):
                continue
            if all(dep in completed for dep in (r.dependencies or [])):
                r.state = (
                    TaskState.OWNER_GATED if r.authority_class in _OWNER_GATE_CLASSES
                    else TaskState.READY
                )
                r.blocked_reason = None
                r.updated_at = _utcnow()

    def block(self, key: str, *, reason: str) -> TaskLeaf:
        """Mark a task blocked; lease is released."""
        with self._lock:
            row = self._get_row(key)
            if row is None:
                raise LookupError(f"TASK_NOT_FOUND:{key}")
            row.state = TaskState.BLOCKED
            row.blocked_reason = reason
            row.leased_at = None
            row.lease_holder = None
            row.updated_at = _utcnow()
            self._session.flush()
            self._commit()
            return _row_to_leaf(row)

    def enter_repair_backoff(self, key: str, *, reason: str) -> TaskLeaf:
        """Transition to repair_backoff; task is not executable until recovered."""
        with self._lock:
            row = self._get_row(key)
            if row is None:
                raise LookupError(f"TASK_NOT_FOUND:{key}")
            row.state = TaskState.REPAIR_BACKOFF
            row.blocked_reason = reason
            row.leased_at = None
            row.lease_holder = None
            row.updated_at = _utcnow()
            self._session.flush()
            self._commit()
            return _row_to_leaf(row)

    def recover_from_backoff(
        self, key: str, *, evidence: dict[str, Any] | None = None
    ) -> TaskLeaf:
        """Restore a repair-backoff task to READY after a real recovery event.

        ``evidence`` (optional) is merged into the persisted task row so bounded
        retry accounting survives process restart.
        """
        with self._lock:
            row = self._get_row(key)
            if row is None:
                raise LookupError(f"TASK_NOT_FOUND:{key}")
            if row.state != TaskState.REPAIR_BACKOFF:
                raise ValueError(f"NOT_IN_BACKOFF:{key}:state={row.state}")
            target = (
                TaskState.OWNER_GATED if row.authority_class in _OWNER_GATE_CLASSES
                else TaskState.READY
            )
            row.state = target
            row.blocked_reason = None
            if evidence:
                merged = dict(row.evidence or {})
                merged.update(evidence)
                row.evidence = merged
            row.updated_at = _utcnow()
            self._session.flush()
            self._commit()
            return _row_to_leaf(row)

    def recover_expired_leases(self, max_lease_age_seconds: float) -> list[TaskLeaf]:
        """Move ACTIVE tasks with expired leases to REPAIR_BACKOFF.

        Safe to call on restart: any tasks that were LEASED/RUNNING/VALIDATING
        when the process died will have stale leased_at times and will be
        transitioned to REPAIR_BACKOFF, freeing slots for re-dispatch.
        """
        now = _utcnow()
        expired_rows: list[DurableReservoirTask] = []
        with self._lock:
            rows = (
                self._session.query(DurableReservoirTask)
                .filter(
                    DurableReservoirTask.run_id == self._run_id,
                    DurableReservoirTask.state.in_(list(_ACTIVE)),
                )
                .all()
            )
            for row in rows:
                if row.leased_at is None:
                    continue
                leased_ts = _dt_to_ts(row.leased_at)
                if leased_ts is None:
                    continue
                age = now.timestamp() - leased_ts
                if age > max_lease_age_seconds:
                    row.state = TaskState.REPAIR_BACKOFF
                    row.blocked_reason = (
                        f"LEASE_EXPIRED:max={max_lease_age_seconds}s"
                        f":holder={row.lease_holder}"
                    )
                    row.leased_at = None
                    row.lease_holder = None
                    row.updated_at = now
                    expired_rows.append(row)
            if expired_rows:
                self._session.flush()
                self._commit()
        return [_row_to_leaf(r) for r in expired_rows]

    def authorize(self, key: str) -> TaskLeaf:
        """Move an owner-gated task to READY after explicit owner approval."""
        with self._lock:
            row = self._get_row(key)
            if row is None:
                raise LookupError(f"TASK_NOT_FOUND:{key}")
            if row.state != TaskState.OWNER_GATED:
                raise ValueError(f"NOT_OWNER_GATED:{key}:state={row.state}")
            row.state = TaskState.READY
            row.updated_at = _utcnow()
            self._session.flush()
            self._commit()
            return _row_to_leaf(row)

    # ------------------------------------------------------------------
    # Refill (mirrors DeepOrchestrate)
    # ------------------------------------------------------------------

    def refill(self, *, width: int | None = None) -> list[TaskLeaf]:
        """Return up to `width` READY tasks for the dispatcher to lease."""
        w = width if width is not None else self.configured_width
        active = len(self.active_tasks())
        slots = max(0, w - active)
        if slots == 0:
            return []
        return self.ready_tasks(limit=slots)

    # ------------------------------------------------------------------
    # Snapshot / serialization
    # ------------------------------------------------------------------

    def snapshot(self, *, next_n: int = 5) -> dict[str, Any]:
        """Mission Control–compatible status snapshot."""
        all_rows = self._all_rows()
        completed = {r.task_key for r in all_rows if r.state == TaskState.COMPLETED}
        active = [r for r in all_rows if r.state in _ACTIVE]
        ready = sorted(
            [r for r in all_rows if _is_ready_row(r, completed)],
            key=lambda r: (r.priority, r.created_at or datetime.min.replace(tzinfo=timezone.utc)),
        )
        blocked = [r for r in all_rows if r.state == TaskState.BLOCKED]
        backoff = [r for r in all_rows if r.state == TaskState.REPAIR_BACKOFF]
        owner_gated = [r for r in all_rows if r.state == TaskState.OWNER_GATED]

        return {
            "schema_version": DURABLE_SCHEMA_VERSION,
            "run_id": self._run_id,
            "configured_width": self.configured_width,
            "active_count": len(active),
            "ready_depth": len(ready),
            "blocked_depth": len(blocked),
            "backoff_depth": len(backoff),
            "owner_gate_count": len(owner_gated),
            "completed_count": len(completed),
            "total_task_count": len(all_rows),
            "next_tasks": [_row_to_leaf(r).to_dict() for r in ready[:next_n]],
            "owner_gates": [_row_to_leaf(r).to_dict() for r in owner_gated],
        }

    def to_dict(self) -> dict[str, Any]:
        all_rows = self._all_rows()
        return {
            "schema_version": DURABLE_SCHEMA_VERSION,
            "run_id": self._run_id,
            "configured_width": self.configured_width,
            "tasks": {r.task_key: _row_to_leaf(r).to_dict() for r in all_rows},
        }
