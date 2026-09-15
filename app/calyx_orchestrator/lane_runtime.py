"""Lane-aware concurrent dispatcher for Orchid Continuum Calyx.

OC-RUNTIME-001 Phase 1 — provider-free concurrency proof.

Adds lane-identity tracking on top of BoundedDispatcher:
  - LaneManager: up to MAX_ACTIVE_LANES=8 concurrent lane slots
  - ConcurrentBoundedDispatcher: extends BoundedDispatcher with LaneManager
    for width-8 concurrent TaskLeaf execution with per-lane evidence.

Invariants enforced here:
  - Duplicate lease key → LaneCollision (never silently absorbed)
  - Lane released on completion AND on failure (always in finally)
  - Cost recorded as UNKNOWN when not measurable (never silently zero)
  - No merge/deploy/spend/production-mutate methods on this class (structural gate)

Authorization: MAX_ACTIVE_LANES=8 authorized by Jeff Parham (OC-RUNTIME-001).
"""

from __future__ import annotations

import concurrent.futures
import logging
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

from .bounded_dispatcher import BoundedDispatcher, DispatchConfig, DispatchRun
from .deep_orchestrate import DeepOrchestrate, TaskLeaf
from .leaf_worker import DeterministicResearchWorker, TaskExecutionResult

log = logging.getLogger(__name__)

MAX_ACTIVE_LANES: int = 8  # Owner-authorized ceiling (Jeff Parham, OC-RUNTIME-001)

COST_UNKNOWN: str = "UNKNOWN"  # Cost sentinel — never silently zero or None


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class LaneCollision(Exception):
    """Raised when a lane acquisition is attempted for a key already held,
    or when the max-lane ceiling would be exceeded."""


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LaneIdentity:
    """Immutable identity record for one active concurrent lane slot."""

    lane_id: str        # Unique ID generated at acquisition (uuid4 hex)
    lease_key: str      # Task key held in this lane
    width: int          # Configured max-width at acquisition time
    acquired_at: float  # time.monotonic() at acquisition
    holder: str         # Holder name passed to acquire()


@dataclass
class LaneEvidence:
    """Per-lane execution evidence recorded by ConcurrentBoundedDispatcher."""

    lane_id: str
    lease_key: str
    holder: str
    start_time: float
    end_time: float | None = None
    duration_seconds: float | None = None
    status: str = "pending"   # "completed" | "blocked" | "failed" | "pending"
    cost: str = COST_UNKNOWN  # Always UNKNOWN — provider-free execution
    thread_id: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "lane_id": self.lane_id,
            "lease_key": self.lease_key,
            "holder": self.holder,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_seconds": self.duration_seconds,
            "status": self.status,
            "cost": self.cost,
            "thread_id": self.thread_id,
        }


# ---------------------------------------------------------------------------
# LaneManager
# ---------------------------------------------------------------------------


class LaneManager:
    """Manages up to ``max_lanes`` concurrent lane slots.

    Thread-safe via an internal lock.  Each lane is identified by a unique
    ``lane_id`` (uuid4 hex).  Attempting to acquire an already-held key, or
    acquiring beyond ``max_lanes``, raises :class:`LaneCollision`.

    Usage::

        manager = LaneManager(max_lanes=8)
        lane = manager.acquire("my:task:key", holder="worker-1")
        # ... execute work ...
        manager.release(lane.lane_id)
    """

    def __init__(self, max_lanes: int = MAX_ACTIVE_LANES) -> None:
        if max_lanes < 1:
            raise ValueError(f"max_lanes must be >= 1, got {max_lanes}")
        self.max_lanes = max_lanes
        self._lock = threading.Lock()
        self._lanes: dict[str, LaneIdentity] = {}    # lane_id → LaneIdentity
        self._key_to_lane: dict[str, str] = {}       # lease_key → lane_id

    def acquire(self, key: str, holder: str) -> LaneIdentity:
        """Atomically acquire a lane slot for ``key``.

        Raises:
            LaneCollision: if ``key`` already has an active lane, or if
                          ``max_lanes`` active lanes would be exceeded.
        """
        with self._lock:
            if key in self._key_to_lane:
                existing = self._key_to_lane[key]
                raise LaneCollision(
                    f"LANE_COLLISION:key={key!r}:existing_lane={existing}"
                )
            if len(self._lanes) >= self.max_lanes:
                raise LaneCollision(
                    f"LANE_CAPACITY_FULL:max_lanes={self.max_lanes}:key={key!r}"
                )
            lane_id = uuid.uuid4().hex
            identity = LaneIdentity(
                lane_id=lane_id,
                lease_key=key,
                width=self.max_lanes,
                acquired_at=time.monotonic(),
                holder=holder,
            )
            self._lanes[lane_id] = identity
            self._key_to_lane[key] = lane_id
            return identity

    def release(self, lane_id: str) -> None:
        """Release a lane slot by lane_id.  No-op if lane_id is unknown."""
        with self._lock:
            identity = self._lanes.pop(lane_id, None)
            if identity is not None:
                self._key_to_lane.pop(identity.lease_key, None)

    def active_lanes(self) -> list[LaneIdentity]:
        """Return a snapshot of currently active :class:`LaneIdentity` records."""
        with self._lock:
            return list(self._lanes.values())

    def available_slots(self) -> int:
        """Return the number of free lane slots."""
        with self._lock:
            return max(0, self.max_lanes - len(self._lanes))


# ---------------------------------------------------------------------------
# ConcurrentBoundedDispatcher
# ---------------------------------------------------------------------------


class ConcurrentBoundedDispatcher(BoundedDispatcher):
    """BoundedDispatcher extended with LaneManager for concurrent width-8 execution.

    Each TaskLeaf execution:
    1. Acquires a :class:`LaneIdentity` before the reservoir lease.
    2. Runs the task worker inside a ``ThreadPoolExecutor`` slot.
    3. Releases the lane on completion AND on failure (always in ``finally``).
    4. Records per-lane evidence (lane_id, start_time, duration, status, cost).
    5. Cost: always ``COST_UNKNOWN`` — provider-free run (never silently zero).
    6. Refills from the canonical queue whenever a lane frees.

    Production mutation gate: no merge/deploy/spend/production-mutate methods
    exist on this class.  Any completed :class:`DispatchRun` likewise carries
    none of these methods.
    """

    DISPATCHER_ID: str = "concurrent-bounded-dispatcher-v1"

    def __init__(
        self,
        reservoir: DeepOrchestrate,
        worker: DeterministicResearchWorker | None = None,
        *,
        max_lanes: int = MAX_ACTIVE_LANES,
    ) -> None:
        super().__init__(reservoir, worker)
        self.lane_manager = LaneManager(max_lanes=max_lanes)
        self._evidence_lock = threading.Lock()
        self._lane_evidence: list[LaneEvidence] = []

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self, config: DispatchConfig | None = None) -> DispatchRun:
        """Execute a bounded concurrent dispatch loop using LaneManager slots.

        Returns when no ready tasks remain, ``max_tasks`` is reached, or
        ``max_iterations`` is exhausted.  Never blocks indefinitely.
        """
        cfg = config or DispatchConfig()
        width = cfg.width if cfg.width is not None else min(
            self.reservoir.configured_width, self.lane_manager.max_lanes
        )
        run = DispatchRun()

        for _ in range(cfg.max_iterations):
            if run.tasks_executed >= cfg.max_tasks:
                break

            run.iterations += 1

            # Recover any expired leases before scanning for new work.
            expired = self.reservoir.recover_expired_leases(cfg.max_lease_age_seconds)
            run.expired_recovered += len(expired)

            self.reservoir.refill()

            # Concurrency constraint: the smaller of available lane slots and width.
            available = min(self.lane_manager.available_slots(), width)
            remaining = cfg.max_tasks - run.tasks_executed
            slots = min(available, remaining)
            ready_keys = self._collect_ready_keys(slots)
            if not ready_keys:
                break

            results = self._dispatch_concurrent_batch(ready_keys, cfg)
            run.results.extend(results)
            run.tasks_executed += len(results)

        return run

    def lane_evidence_snapshot(self) -> list[dict[str, Any]]:
        """Return a copy of per-lane evidence records accumulated so far."""
        with self._evidence_lock:
            return [e.as_dict() for e in self._lane_evidence]

    # ── Internals ─────────────────────────────────────────────────────────────

    def _dispatch_concurrent_batch(
        self, keys: list[str], cfg: DispatchConfig
    ) -> list[TaskExecutionResult]:
        """Acquire lane, execute in thread pool, release lane — for each key."""
        results: list[TaskExecutionResult] = []

        if len(keys) == 1:
            result = self._execute_in_lane(keys[0], cfg.lease_holder)
            if result is not None:
                results.append(result)
        else:
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=len(keys)
            ) as pool:
                futures = {
                    pool.submit(self._execute_in_lane, k, cfg.lease_holder): k
                    for k in keys
                }
                for future in concurrent.futures.as_completed(futures):
                    result = future.result()
                    if result is not None:
                        results.append(result)

        return results

    def _execute_in_lane(
        self, key: str, lease_holder: str
    ) -> TaskExecutionResult | None:
        """Acquire lane → lease task → execute → commit → release lane.

        The lane is ALWAYS released in ``finally``, whether the task
        completed, blocked, or raised an unexpected exception.
        Cost is recorded as ``COST_UNKNOWN`` regardless of outcome.
        """
        # Acquire lane slot first — raises LaneCollision if duplicate or full.
        try:
            lane = self.lane_manager.acquire(key, holder=lease_holder)
        except LaneCollision as exc:
            log.debug("lane acquisition failed for %s: %s", key, exc)
            return None

        evidence = LaneEvidence(
            lane_id=lane.lane_id,
            lease_key=key,
            holder=lease_holder,
            start_time=time.monotonic(),
            thread_id=threading.get_ident(),
            cost=COST_UNKNOWN,
        )

        try:
            # Lease the reservoir task (atomic state transition).
            try:
                leaf: TaskLeaf = self.reservoir.lease(key, holder=lease_holder)
            except (LookupError, ValueError) as exc:
                log.debug("reservoir lease failed for %s: %s", key, exc)
                evidence.status = "failed"
                self._finalise_evidence(evidence)
                return None

            # Execute worker (deterministic, no provider calls).
            try:
                result = self.worker.execute(leaf)
            except Exception as exc:  # noqa: BLE001
                log.warning("worker raised for %s: %s", key, exc)
                evidence.status = "failed"
                self._finalise_evidence(evidence)
                _safe_block(self.reservoir, key, "CBD_WORKER_EXCEPTION")
                return None

            # Commit outcome to reservoir.
            if result.status == "completed":
                try:
                    self.reservoir.complete(
                        key,
                        evidence={
                            **result.as_evidence(),
                            "lane_id": lane.lane_id,
                            "cost": COST_UNKNOWN,
                        },
                    )
                except Exception:
                    log.exception("complete() failed for %s; attempting block", key)
                    _safe_block(self.reservoir, key, "CBD_COMPLETE_FAILED")
            else:
                reason = result.error_reason or "WORKER_BLOCKED"
                _safe_block(self.reservoir, key, reason)

            evidence.status = result.status
            self._finalise_evidence(evidence)
            return result

        except Exception:
            # Catch-all: unexpected failure path — lane must still be released.
            log.exception("unexpected failure in lane execution for %s", key)
            evidence.status = "failed"
            self._finalise_evidence(evidence)
            _safe_block(self.reservoir, key, "CBD_UNEXPECTED_FAILURE")
            return None

        finally:
            # ALWAYS release the lane slot — completion, failure, or exception.
            self.lane_manager.release(lane.lane_id)

    def _finalise_evidence(self, evidence: LaneEvidence) -> None:
        """Stamp end_time/duration and append to the evidence log."""
        now = time.monotonic()
        evidence.end_time = now
        evidence.duration_seconds = now - evidence.start_time
        with self._evidence_lock:
            self._lane_evidence.append(evidence)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_block(reservoir: DeepOrchestrate, key: str, reason: str) -> None:
    """Block a reservoir task without raising."""
    try:
        reservoir.block(key, reason=reason)
    except Exception:
        log.exception("block() failed for %s (reason=%s)", key, reason)
