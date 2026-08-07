from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ScheduledState(StrEnum):
    WAITING = "waiting"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


SUCCESSFUL_OUTCOMES = frozenset({"DELIVERED", "NO_OP"})
FAILED_OUTCOMES = frozenset({"BLOCKED", "CANCELLED", "DEAD_LETTER"})


@dataclass(frozen=True, slots=True)
class ScheduledJob:
    job_key: str
    role_key: str
    architecture: str
    repository: str
    priority: int = 100
    created_order: int = 0
    state: ScheduledState = ScheduledState.WAITING
    outcome: str | None = None


@dataclass(frozen=True, slots=True)
class SchedulerLimits:
    max_global_running: int = 6
    max_architecture_running: int = 3
    max_role_running: int = 2
    max_repository_running: int = 2
    architecture_limits: dict[str, int] = field(default_factory=dict)

    def validate(self) -> None:
        values = (
            self.max_global_running,
            self.max_architecture_running,
            self.max_role_running,
            self.max_repository_running,
            *self.architecture_limits.values(),
        )
        if min(values) < 1:
            raise ValueError("SCHEDULER_LIMITS_MUST_BE_POSITIVE")

    def architecture_limit(self, architecture: str) -> int:
        return self.architecture_limits.get(architecture, self.max_architecture_running)


@dataclass(frozen=True, slots=True)
class ScheduledDecision:
    job_key: str
    runnable: bool
    rank: int | None
    critical_path_depth: int
    blocked_by: tuple[str, ...]
    code: str


@dataclass(frozen=True, slots=True)
class SchedulerSnapshot:
    decisions: tuple[ScheduledDecision, ...]
    runnable_order: tuple[str, ...]
    running_counts: dict[str, object]


class DependencyScheduler:
    """Pure deterministic projection over dependency and capacity state."""

    def project(
        self,
        *,
        jobs: tuple[ScheduledJob, ...],
        dependencies: tuple[tuple[str, str], ...],
        limits: SchedulerLimits | None = None,
    ) -> SchedulerSnapshot:
        limits = limits or SchedulerLimits()
        limits.validate()
        by_key = {job.job_key: job for job in jobs}
        if len(by_key) != len(jobs):
            raise ValueError("DUPLICATE_SCHEDULE_JOB_KEY")

        parents: dict[str, set[str]] = {key: set() for key in by_key}
        children: dict[str, set[str]] = {key: set() for key in by_key}
        for upstream, downstream in dependencies:
            if upstream not in by_key or downstream not in by_key:
                raise ValueError("SCHEDULE_DEPENDENCY_JOB_NOT_FOUND")
            if upstream == downstream:
                raise ValueError("SCHEDULE_SELF_DEPENDENCY")
            parents[downstream].add(upstream)
            children[upstream].add(downstream)
        self._assert_acyclic(children)

        depths = self._critical_depths(children)
        running = tuple(job for job in jobs if job.state == ScheduledState.RUNNING)
        architecture_counts = self._count(running, "architecture")
        role_counts = self._count(running, "role_key")
        repository_counts = self._count(running, "repository")

        candidates: list[ScheduledJob] = []
        preliminary: dict[str, ScheduledDecision] = {}
        for job in jobs:
            blocked_by = tuple(
                sorted(
                    parent
                    for parent in parents[job.job_key]
                    if by_key[parent].outcome not in SUCCESSFUL_OUTCOMES
                )
            )
            failed_parent = any(by_key[parent].outcome in FAILED_OUTCOMES for parent in parents[job.job_key])
            if job.state in {ScheduledState.COMPLETED, ScheduledState.BLOCKED, ScheduledState.CANCELLED}:
                preliminary[job.job_key] = ScheduledDecision(
                    job_key=job.job_key,
                    runnable=False,
                    rank=None,
                    critical_path_depth=depths[job.job_key],
                    blocked_by=blocked_by,
                    code="TERMINAL",
                )
            elif job.state == ScheduledState.RUNNING:
                preliminary[job.job_key] = ScheduledDecision(
                    job_key=job.job_key,
                    runnable=False,
                    rank=None,
                    critical_path_depth=depths[job.job_key],
                    blocked_by=(),
                    code="ALREADY_RUNNING",
                )
            elif failed_parent:
                preliminary[job.job_key] = ScheduledDecision(
                    job_key=job.job_key,
                    runnable=False,
                    rank=None,
                    critical_path_depth=depths[job.job_key],
                    blocked_by=blocked_by,
                    code="PREREQUISITE_FAILED",
                )
            elif blocked_by:
                preliminary[job.job_key] = ScheduledDecision(
                    job_key=job.job_key,
                    runnable=False,
                    rank=None,
                    critical_path_depth=depths[job.job_key],
                    blocked_by=blocked_by,
                    code="WAITING_FOR_PREREQUISITES",
                )
            else:
                candidates.append(job)

        candidates.sort(
            key=lambda job: (
                -depths[job.job_key],
                job.priority,
                job.created_order,
                job.job_key,
            )
        )

        global_count = len(running)
        admitted: list[str] = []
        for job in candidates:
            code = "RUNNABLE"
            runnable = True
            if global_count >= limits.max_global_running:
                runnable = False
                code = "GLOBAL_CAPACITY_REACHED"
            elif architecture_counts.get(job.architecture, 0) >= limits.architecture_limit(job.architecture):
                runnable = False
                code = "ARCHITECTURE_CAPACITY_REACHED"
            elif role_counts.get(job.role_key, 0) >= limits.max_role_running:
                runnable = False
                code = "ROLE_CAPACITY_REACHED"
            elif repository_counts.get(job.repository, 0) >= limits.max_repository_running:
                runnable = False
                code = "REPOSITORY_CAPACITY_REACHED"

            if runnable:
                global_count += 1
                architecture_counts[job.architecture] = architecture_counts.get(job.architecture, 0) + 1
                role_counts[job.role_key] = role_counts.get(job.role_key, 0) + 1
                repository_counts[job.repository] = repository_counts.get(job.repository, 0) + 1
                admitted.append(job.job_key)
            preliminary[job.job_key] = ScheduledDecision(
                job_key=job.job_key,
                runnable=runnable,
                rank=len(admitted) if runnable else None,
                critical_path_depth=depths[job.job_key],
                blocked_by=(),
                code=code,
            )

        decisions = tuple(preliminary[key] for key in sorted(preliminary))
        return SchedulerSnapshot(
            decisions=decisions,
            runnable_order=tuple(admitted),
            running_counts={
                "global": len(running),
                "architecture": self._count(running, "architecture"),
                "role": self._count(running, "role_key"),
                "repository": self._count(running, "repository"),
            },
        )

    @staticmethod
    def _count(jobs: tuple[ScheduledJob, ...], attribute: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for job in jobs:
            value = str(getattr(job, attribute))
            counts[value] = counts.get(value, 0) + 1
        return counts

    @staticmethod
    def _assert_acyclic(children: dict[str, set[str]]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(key: str) -> None:
            if key in visited:
                return
            if key in visiting:
                raise ValueError("CYCLIC_SCHEDULE_DEPENDENCY")
            visiting.add(key)
            for child in sorted(children[key]):
                visit(child)
            visiting.remove(key)
            visited.add(key)

        for key in sorted(children):
            visit(key)

    @staticmethod
    def _critical_depths(children: dict[str, set[str]]) -> dict[str, int]:
        memo: dict[str, int] = {}

        def depth(key: str) -> int:
            if key not in memo:
                memo[key] = 0 if not children[key] else 1 + max(depth(child) for child in children[key])
            return memo[key]

        return {key: depth(key) for key in children}
