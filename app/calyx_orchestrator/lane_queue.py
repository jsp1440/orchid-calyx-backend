"""Rolling five-lane backlog queue core (TWO-DAY-SLICE-C, issue #1027).

This module is repository-local and in-memory: it has no database, HTTP, or
workflow dependency. It operationalizes the coordinator rule in
``AGENTS.md`` ("the coordinator may maintain up to five independent active
coding lanes, but only one active implementation per issue") as a small,
deterministic, testable engine rather than a parallel job scheduler.

It intentionally does not duplicate ``app.calyx_orchestrator.scheduler``
(``DependencyScheduler``) or ``app.calyx_orchestrator.program_core``
(``EngineeringProgram``), which govern concurrency for *engineering jobs
within a program* against a persisted database. This module governs
concurrency for the *backlog of completion-tracked tasks* (for example,
issues in the TWO-DAY-SLICE family) that feed those programs, and is meant
to be driven by a caller that already knows each task's real status
(verified, owner-gated, blocked, etc.) -- it does not itself talk to GitHub.

A task occupies exactly one of five statuses at a time:

- ``BLOCKED``: one or more dependencies are not yet ``VERIFIED``. Does not
  consume active width.
- ``QUEUED``: eligible (no unmet dependency) and waiting for a free lane.
- ``ACTIVE``: currently occupying one of ``width`` lanes.
- ``VERIFIED``: terminal success. Releases its lane. Unblocks dependents.
- ``OWNER_GATED``: terminal-for-now. Releases its lane but stays visible in
  the owner-action queue until an owner resolves it.
- ``EXTERNAL_BLOCKER``: terminal-for-now. Releases its lane because of a
  blocker outside repository control (e.g. an external service or CI).

``BLOCKED`` / ``OWNER_GATED`` / ``EXTERNAL_BLOCKER`` are never confused with
"stopped": none of them halt the queue. Whenever a lane is released for any
of these reasons, the next highest-priority eligible queued task is admitted
immediately, so there is no idle capacity while eligible work exists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TaskStatus(StrEnum):
    BLOCKED = "blocked"
    QUEUED = "queued"
    ACTIVE = "active"
    VERIFIED = "verified"
    OWNER_GATED = "owner_gated"
    EXTERNAL_BLOCKER = "external_blocker"


TERMINAL_RELEASE_STATUSES = frozenset(
    {TaskStatus.VERIFIED, TaskStatus.OWNER_GATED, TaskStatus.EXTERNAL_BLOCKER}
)
DEFAULT_WIDTH = 5


@dataclass(frozen=True, slots=True)
class BacklogTask:
    """One stable, keyed backlog entry.

    ``priority`` is descending-urgency: a higher integer is admitted before
    a lower one. Ties break on ``created_order`` (insertion order), then on
    ``task_key`` for full determinism.
    """

    task_key: str
    title: str
    priority: int = 0
    created_order: int = 0
    depends_on: tuple[str, ...] = ()


@dataclass(slots=True)
class _TaskState:
    task: BacklogTask
    status: TaskStatus
    lane: int | None = None
    note: str | None = None


class DuplicateTaskKeyError(ValueError):
    pass


class UnknownDependencyError(ValueError):
    pass


class CyclicDependencyError(ValueError):
    pass


class RollingLaneQueue:
    """Deterministic admission/refill engine over a fixed number of lanes."""

    def __init__(self, tasks: list[BacklogTask], *, width: int = DEFAULT_WIDTH) -> None:
        if width < 1:
            raise ValueError("LANE_WIDTH_MUST_BE_POSITIVE")
        self.width = width
        self._sequence = 0
        self._last_action: dict[str, Any] | None = None

        by_key: dict[str, _TaskState] = {}
        for task in tasks:
            if task.task_key in by_key:
                raise DuplicateTaskKeyError(task.task_key)
            by_key[task.task_key] = _TaskState(task=task, status=TaskStatus.BLOCKED)

        for state in by_key.values():
            missing = [key for key in state.task.depends_on if key not in by_key]
            if missing:
                raise UnknownDependencyError(f"{state.task.task_key}:{','.join(sorted(missing))}")

        self._assert_acyclic(by_key)

        self._states = by_key
        self._lanes: dict[int, str] = {}
        for state in self._states.values():
            if not state.task.depends_on:
                state.status = TaskStatus.QUEUED
        self._refill()

    @staticmethod
    def _assert_acyclic(by_key: dict[str, "_TaskState"]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(key: str) -> None:
            if key in visited:
                return
            if key in visiting:
                raise CyclicDependencyError(key)
            visiting.add(key)
            for dependency in by_key[key].task.depends_on:
                visit(dependency)
            visiting.remove(key)
            visited.add(key)

        for key in by_key:
            visit(key)

    def _eligible_queue_order(self) -> list[_TaskState]:
        queued = [state for state in self._states.values() if state.status == TaskStatus.QUEUED]
        queued.sort(key=lambda state: (-state.task.priority, state.task.created_order, state.task.task_key))
        return queued

    def _free_lanes(self) -> list[int]:
        occupied = set(self._lanes)
        return [lane for lane in range(self.width) if lane not in occupied]

    def _refill(self) -> list[str]:
        admitted: list[str] = []
        free_lanes = self._free_lanes()
        for lane in free_lanes:
            candidates = self._eligible_queue_order()
            if not candidates:
                break
            next_state = candidates[0]
            next_state.status = TaskStatus.ACTIVE
            next_state.lane = lane
            self._lanes[lane] = next_state.task.task_key
            admitted.append(next_state.task.task_key)
        return admitted

    def _unblock_dependents(self, verified_key: str) -> None:
        changed = True
        while changed:
            changed = False
            for state in self._states.values():
                if state.status != TaskStatus.BLOCKED:
                    continue
                if any(
                    self._states[dep].status != TaskStatus.VERIFIED
                    for dep in state.task.depends_on
                ):
                    continue
                state.status = TaskStatus.QUEUED
                changed = True

    def advance(self, task_key: str, outcome: TaskStatus, *, note: str | None = None) -> dict[str, Any]:
        """Move an active task to a terminal-for-now status and refill its lane.

        ``outcome`` must be one of VERIFIED, OWNER_GATED, or EXTERNAL_BLOCKER.
        """

        if outcome not in TERMINAL_RELEASE_STATUSES:
            raise ValueError(f"UNSUPPORTED_ADVANCE_OUTCOME:{outcome}")
        state = self._states.get(task_key)
        if state is None:
            raise KeyError(f"UNKNOWN_TASK_KEY:{task_key}")
        if state.status != TaskStatus.ACTIVE:
            raise ValueError(f"TASK_NOT_ACTIVE:{task_key}:{state.status}")

        lane = state.lane
        state.status = outcome
        state.lane = None
        state.note = note
        if lane is not None:
            del self._lanes[lane]

        if outcome == TaskStatus.VERIFIED:
            self._unblock_dependents(task_key)

        admitted = self._refill()

        self._sequence += 1
        self._last_action = {
            "sequence": self._sequence,
            "task_key": task_key,
            "outcome": outcome.value,
            "note": note,
            "admitted": list(admitted),
        }
        return dict(self._last_action)

    def release_owner_gate(self, task_key: str, *, requeue: bool) -> dict[str, Any]:
        """Resolve an owner-action item: send it back to the queue or verify it."""

        state = self._states.get(task_key)
        if state is None:
            raise KeyError(f"UNKNOWN_TASK_KEY:{task_key}")
        if state.status != TaskStatus.OWNER_GATED:
            raise ValueError(f"TASK_NOT_OWNER_GATED:{task_key}:{state.status}")

        state.status = TaskStatus.QUEUED if requeue else TaskStatus.VERIFIED
        state.note = None
        if state.status == TaskStatus.VERIFIED:
            self._unblock_dependents(task_key)

        admitted = self._refill()
        self._sequence += 1
        self._last_action = {
            "sequence": self._sequence,
            "task_key": task_key,
            "outcome": "owner_release_requeue" if requeue else "owner_release_verified",
            "note": None,
            "admitted": list(admitted),
        }
        return dict(self._last_action)

    def status(self) -> dict[str, Any]:
        """A compact, deterministic status projection."""

        def brief(state: _TaskState) -> dict[str, Any]:
            payload = {
                "task_key": state.task.task_key,
                "title": state.task.title,
                "priority": state.task.priority,
            }
            if state.note:
                payload["note"] = state.note
            return payload

        active = [
            brief(self._states[self._lanes[lane]]) | {"lane": lane}
            for lane in sorted(self._lanes)
        ]
        queued_next = [brief(state) for state in self._eligible_queue_order()]
        owner_gated = sorted(
            (brief(state) for state in self._states.values() if state.status == TaskStatus.OWNER_GATED),
            key=lambda item: item["task_key"],
        )
        blocked = sorted(
            (brief(state) for state in self._states.values() if state.status == TaskStatus.BLOCKED),
            key=lambda item: item["task_key"],
        )
        external_blocked = sorted(
            (brief(state) for state in self._states.values() if state.status == TaskStatus.EXTERNAL_BLOCKER),
            key=lambda item: item["task_key"],
        )
        verified_count = sum(1 for state in self._states.values() if state.status == TaskStatus.VERIFIED)

        idle_lanes = self.width - len(self._lanes)
        if owner_gated:
            next_action = f"Owner review required for {len(owner_gated)} task(s): " + ", ".join(
                item["task_key"] for item in owner_gated
            )
        elif idle_lanes > 0 and queued_next:
            next_action = "Refill stalled: eligible work exists but was not admitted."
        elif blocked and not active and not queued_next:
            next_action = "Resolve blocking dependencies for: " + ", ".join(
                item["task_key"] for item in blocked
            )
        elif not active and not queued_next and not blocked and not owner_gated:
            next_action = "Queue idle; all tasks verified."
        else:
            next_action = "Continue active lanes; refill is automatic on completion."

        return {
            "width": self.width,
            "active": active,
            "queued_next": queued_next,
            "owner_gated": owner_gated,
            "blocked": blocked,
            "external_blocked": external_blocked,
            "verified_count": verified_count,
            "last_action": dict(self._last_action) if self._last_action else None,
            "next_action": next_action,
        }
