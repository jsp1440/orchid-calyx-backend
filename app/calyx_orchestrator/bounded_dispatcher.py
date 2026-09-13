"""Bounded, idempotent dispatcher for DeepOrchestrate TaskLeaves.

Orchestrates the full autonomous execution loop:

    DeepOrchestrate.refill()            # make READY tasks visible
    DeepOrchestrate.lease(key)          # atomic; raises on conflict / not-ready
    DeterministicResearchWorker.execute(leaf) → TaskExecutionResult
    DeepOrchestrate.complete(key, evidence=…)  # canonical completion
     OR DeepOrchestrate.block(key, reason=…)   # canonical block

Hard boundaries enforced here:
- max_tasks:      total tasks executed across the run (default 20)
- max_iterations: times the reservoir is scanned for ready work (default 10)
- width:          maximum concurrent task leases (default: reservoir width)
- OWNER_GATED-state tasks are never leased — skipped without error
  (tasks authorized via reservoir.authorize() are READY and ARE dispatched)
- Completed tasks are never re-executed (idempotent)
- Expired leases are recovered before each iteration

No infinite loops. No paid provider calls. Fully deterministic.
"""

from __future__ import annotations

import concurrent.futures
import logging
from dataclasses import dataclass, field
from typing import Any

from .deep_orchestrate import DeepOrchestrate, TaskLeaf, TaskState
from .leaf_worker import DeterministicResearchWorker, TaskExecutionResult

log = logging.getLogger(__name__)

_DEFAULT_MAX_TASKS = 20
_DEFAULT_MAX_ITERATIONS = 10
_DEFAULT_MAX_LEASE_AGE_SECONDS = 300.0  # 5 minutes


@dataclass(frozen=True, slots=True)
class DispatchConfig:
    """Bounded execution parameters."""

    max_tasks: int = _DEFAULT_MAX_TASKS
    max_iterations: int = _DEFAULT_MAX_ITERATIONS
    lease_holder: str = "bounded-dispatcher-v1"
    max_lease_age_seconds: float = _DEFAULT_MAX_LEASE_AGE_SECONDS
    width: int | None = None  # None → use reservoir.configured_width


@dataclass
class DispatchRun:
    """Mutable accumulator for one bounded dispatch run."""

    results: list[TaskExecutionResult] = field(default_factory=list)
    iterations: int = 0
    tasks_executed: int = 0
    tasks_skipped: int = 0
    expired_recovered: int = 0

    def summary(self) -> dict[str, Any]:
        return {
            "iterations": self.iterations,
            "tasks_executed": self.tasks_executed,
            "tasks_skipped": self.tasks_skipped,
            "expired_recovered": self.expired_recovered,
            "completed": sum(1 for r in self.results if r.status == "completed"),
            "blocked": sum(1 for r in self.results if r.status == "blocked"),
            "results": [r.as_evidence() for r in self.results],
        }


class BoundedDispatcher:
    """Orchestrate bounded autonomous execution of a DeepOrchestrate reservoir.

    Usage::

        dispatcher = BoundedDispatcher(reservoir, worker=DeterministicResearchWorker())
        run = dispatcher.run(config=DispatchConfig(max_tasks=10))
        print(run.summary())
    """

    def __init__(
        self,
        reservoir: DeepOrchestrate,
        worker: DeterministicResearchWorker | None = None,
    ) -> None:
        self.reservoir = reservoir
        self.worker = worker or DeterministicResearchWorker()

    def run(self, config: DispatchConfig | None = None) -> DispatchRun:
        """Execute a bounded dispatch loop. Returns when:
        - No ready tasks remain, OR
        - max_tasks reached, OR
        - max_iterations reached.

        Never blocks indefinitely. Never executes owner-gated tasks.
        """
        cfg = config or DispatchConfig()
        width = cfg.width if cfg.width is not None else self.reservoir.configured_width
        run = DispatchRun()

        for _ in range(cfg.max_iterations):
            if run.tasks_executed >= cfg.max_tasks:
                break

            run.iterations += 1

            # Recover any expired leases before scanning for new work.
            expired = self.reservoir.recover_expired_leases(cfg.max_lease_age_seconds)
            run.expired_recovered += len(expired)

            self.reservoir.refill()
            remaining = cfg.max_tasks - run.tasks_executed
            slots = min(width - _active_count(self.reservoir), remaining)
            ready_keys = self._collect_ready_keys(slots)
            if not ready_keys:
                break  # Nothing left to do — exit before limit.

            results = self._dispatch_batch(ready_keys, cfg)
            run.results.extend(results)
            run.tasks_executed += len(results)

        return run

    # ── Internals ─────────────────────────────────────────────────────────────

    def _collect_ready_keys(self, slots: int) -> list[str]:
        """Return up to `slots` READY, dispatchable task keys.

        Tasks that are still in OWNER_GATED state are skipped; tasks that were
        authorized via reservoir.authorize() are in READY state and ARE dispatched.
        ready_tasks() only returns state==READY leaves, so the state check below
        is a defensive belt-and-suspenders guard only.
        """
        if slots <= 0:
            return []
        keys: list[str] = []
        for leaf in self.reservoir.ready_tasks():
            if len(keys) >= slots:
                break
            if leaf.state == TaskState.OWNER_GATED:
                continue  # Still pending explicit authorization; never auto-dispatch.
            keys.append(leaf.key)
        return keys

    def _dispatch_batch(
        self, keys: list[str], cfg: DispatchConfig
    ) -> list[TaskExecutionResult]:
        """Lease, execute, and commit one batch of tasks. Thread-safe per key."""
        results: list[TaskExecutionResult] = []
        if len(keys) == 1:
            result = self._execute_one(keys[0], cfg.lease_holder)
            if result is not None:
                results.append(result)
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=len(keys)) as pool:
                futures = {
                    pool.submit(self._execute_one, k, cfg.lease_holder): k
                    for k in keys
                }
                for future in concurrent.futures.as_completed(futures):
                    result = future.result()
                    if result is not None:
                        results.append(result)
        return results

    def _execute_one(
        self, key: str, lease_holder: str
    ) -> TaskExecutionResult | None:
        """Lease → execute → commit one task. Returns None if lease fails."""
        try:
            leaf: TaskLeaf = self.reservoir.lease(key, holder=lease_holder)
        except (LookupError, ValueError) as exc:
            log.debug("lease failed for %s: %s", key, exc)
            return None

        result = self.worker.execute(leaf)

        if result.status == "completed":
            try:
                self.reservoir.complete(key, evidence=result.as_evidence())
            except Exception:
                log.exception("complete() failed for %s; attempting block", key)
                try:
                    self.reservoir.block(key, reason="DISPATCHER_COMPLETE_FAILED")
                except Exception:
                    log.exception("block() also failed for %s", key)
        else:
            reason = result.error_reason or "WORKER_BLOCKED"
            try:
                self.reservoir.block(key, reason=reason)
            except Exception:
                log.exception("block() failed for %s", key)

        return result


def _active_count(reservoir: DeepOrchestrate) -> int:
    """Count tasks currently in an active (leased/running/validating) state."""
    from .deep_orchestrate import _ACTIVE

    return sum(1 for t in reservoir._tasks.values() if t.state in _ACTIVE)
