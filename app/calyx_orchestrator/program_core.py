from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from .engineering_core import TerminalOutcome


class ProgramStatus(StrEnum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class ProgramJobStatus(StrEnum):
    WAITING = "waiting"
    READY = "ready"
    RUNNING = "running"
    TERMINAL = "terminal"
    CANCELLED = "cancelled"


SUCCESSFUL_DEPENDENCY_OUTCOMES = {
    TerminalOutcome.DELIVERED,
    TerminalOutcome.NO_OP,
}


@dataclass(frozen=True, slots=True)
class ProgramJobSpec:
    job_key: str
    role_key: str
    title: str
    repository: str
    branch: str | None = None
    mutating: bool = False
    depends_on: tuple[str, ...] = ()


@dataclass(slots=True)
class ProgramJobState:
    spec: ProgramJobSpec
    status: ProgramJobStatus
    outcome: TerminalOutcome | None = None
    evidence: tuple[str, ...] = ()


@dataclass(slots=True)
class EngineeringProgram:
    program_id: str
    owner: str
    title: str
    status: ProgramStatus = ProgramStatus.DRAFT
    jobs: dict[str, ProgramJobState] = field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        program_id: str,
        owner: str,
        title: str,
        jobs: Iterable[ProgramJobSpec],
    ) -> EngineeringProgram:
        specs = list(jobs)
        if not specs:
            raise ValueError("PROGRAM_REQUIRES_JOBS")
        keys = [item.job_key for item in specs]
        if len(keys) != len(set(keys)):
            raise ValueError("DUPLICATE_PROGRAM_JOB_KEY")
        known = set(keys)
        for item in specs:
            missing = set(item.depends_on) - known
            if missing:
                raise ValueError(f"UNKNOWN_DEPENDENCY:{','.join(sorted(missing))}")
            if item.job_key in item.depends_on:
                raise ValueError("SELF_DEPENDENCY")
        _assert_acyclic(specs)
        states = {
            item.job_key: ProgramJobState(
                spec=item,
                status=ProgramJobStatus.WAITING if item.depends_on else ProgramJobStatus.READY,
            )
            for item in specs
        }
        return cls(program_id=program_id, owner=owner, title=title, jobs=states)

    def start(self) -> None:
        if self.status not in {ProgramStatus.DRAFT, ProgramStatus.PAUSED}:
            raise ValueError("PROGRAM_NOT_STARTABLE")
        self.status = ProgramStatus.RUNNING
        self.release_ready_jobs()

    def pause(self) -> None:
        if self.status != ProgramStatus.RUNNING:
            raise ValueError("PROGRAM_NOT_RUNNING")
        self.status = ProgramStatus.PAUSED

    def cancel(self) -> None:
        if self.status in {ProgramStatus.COMPLETED, ProgramStatus.CANCELLED}:
            raise ValueError("PROGRAM_NOT_CANCELLABLE")
        self.status = ProgramStatus.CANCELLED
        for state in self.jobs.values():
            if state.status in {ProgramJobStatus.WAITING, ProgramJobStatus.READY}:
                state.status = ProgramJobStatus.CANCELLED
                state.outcome = TerminalOutcome.CANCELLED

    def mark_running(self, job_key: str) -> None:
        self._require_running_program()
        state = self._job(job_key)
        if state.status != ProgramJobStatus.READY:
            raise ValueError("PROGRAM_JOB_NOT_READY")
        state.status = ProgramJobStatus.RUNNING

    def complete_job(
        self,
        job_key: str,
        *,
        outcome: TerminalOutcome,
        evidence: Iterable[str] = (),
    ) -> tuple[str, ...]:
        self._require_running_program()
        state = self._job(job_key)
        if state.status not in {ProgramJobStatus.READY, ProgramJobStatus.RUNNING}:
            raise ValueError("PROGRAM_JOB_NOT_COMPLETABLE")
        if state.status == ProgramJobStatus.TERMINAL:
            raise ValueError("DUPLICATE_TERMINAL_COMPLETION")
        state.status = ProgramJobStatus.TERMINAL
        state.outcome = outcome
        state.evidence = tuple(evidence)
        released = self.release_ready_jobs()
        self._refresh_program_status()
        return released

    def release_ready_jobs(self) -> tuple[str, ...]:
        if self.status != ProgramStatus.RUNNING:
            return ()
        released: list[str] = []
        changed = True
        while changed:
            changed = False
            for key, state in self.jobs.items():
                if state.status != ProgramJobStatus.WAITING:
                    continue
                dependencies = [self.jobs[item] for item in state.spec.depends_on]
                if any(
                    dep.status == ProgramJobStatus.TERMINAL
                    and dep.outcome not in SUCCESSFUL_DEPENDENCY_OUTCOMES
                    for dep in dependencies
                ):
                    state.status = ProgramJobStatus.TERMINAL
                    state.outcome = TerminalOutcome.BLOCKED
                    state.evidence = ("PREREQUISITE_NOT_SUCCESSFUL",)
                    changed = True
                    continue
                if dependencies and all(
                    dep.status == ProgramJobStatus.TERMINAL
                    and dep.outcome in SUCCESSFUL_DEPENDENCY_OUTCOMES
                    for dep in dependencies
                ):
                    state.status = ProgramJobStatus.READY
                    released.append(key)
                    changed = True
        return tuple(released)

    def snapshot(self) -> dict:
        return {
            "program_id": self.program_id,
            "owner": self.owner,
            "title": self.title,
            "status": self.status.value,
            "jobs": {
                key: {
                    "status": state.status.value,
                    "outcome": state.outcome.value if state.outcome else None,
                    "role_key": state.spec.role_key,
                    "repository": state.spec.repository,
                    "branch": state.spec.branch,
                    "mutating": state.spec.mutating,
                    "depends_on": list(state.spec.depends_on),
                    "evidence": list(state.evidence),
                }
                for key, state in self.jobs.items()
            },
        }

    def _refresh_program_status(self) -> None:
        if any(state.status == ProgramJobStatus.RUNNING for state in self.jobs.values()):
            return
        if any(state.status in {ProgramJobStatus.READY, ProgramJobStatus.WAITING} for state in self.jobs.values()):
            return
        if all(
            state.outcome in SUCCESSFUL_DEPENDENCY_OUTCOMES
            for state in self.jobs.values()
            if state.status == ProgramJobStatus.TERMINAL
        ):
            self.status = ProgramStatus.COMPLETED
        else:
            self.status = ProgramStatus.BLOCKED

    def _job(self, job_key: str) -> ProgramJobState:
        try:
            return self.jobs[job_key]
        except KeyError as exc:
            raise LookupError("PROGRAM_JOB_NOT_FOUND") from exc

    def _require_running_program(self) -> None:
        if self.status != ProgramStatus.RUNNING:
            raise ValueError("PROGRAM_NOT_RUNNING")


def _assert_acyclic(specs: Iterable[ProgramJobSpec]) -> None:
    graph = {item.job_key: item.depends_on for item in specs}
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visited:
            return
        if key in visiting:
            raise ValueError("CYCLIC_PROGRAM_DEPENDENCY")
        visiting.add(key)
        for dependency in graph[key]:
            visit(dependency)
        visiting.remove(key)
        visited.add(key)

    for key in graph:
        visit(key)
