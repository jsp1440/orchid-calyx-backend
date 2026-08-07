from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .engineering_core import TerminalOutcome
from .models import utcnow
from .program_models import CalyxProgram, CalyxProgramDependency, CalyxProgramJob

TERMINAL_OUTCOMES = {outcome.value for outcome in TerminalOutcome}
SUCCESSFUL_OUTCOMES = {
    TerminalOutcome.DELIVERED.value,
    TerminalOutcome.NO_OP.value,
}
MAX_JOB_INPUT_BYTES = 2_000_000


@dataclass(frozen=True)
class ProgramJobSpec:
    job_key: str
    role_key: str
    title: str
    repository: str
    branch: str | None = None
    mutating: bool = False
    inputs: dict[str, object] | None = None

    @property
    def serialized_inputs(self) -> str | None:
        value = self.inputs or {}
        if not isinstance(value, dict):
            raise TypeError("PROGRAM_JOB_INPUTS_OBJECT_REQUIRED")
        if any(not isinstance(key, str) or not key.strip() for key in value):
            raise ValueError("PROGRAM_JOB_INPUT_KEY_INVALID")
        try:
            payload = json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("PROGRAM_JOB_INPUTS_NOT_CANONICAL_JSON") from exc
        if len(payload.encode("utf-8")) > MAX_JOB_INPUT_BYTES:
            raise ValueError("PROGRAM_JOB_INPUTS_TOO_LARGE")
        return payload if value else None

    @property
    def fingerprint(self) -> str:
        payload = "|".join(
            [
                self.job_key,
                self.role_key,
                self.repository,
                self.branch or "",
                "1" if self.mutating else "0",
                self.serialized_inputs or "{}",
            ]
        )
        return hashlib.sha256(payload.encode()).hexdigest()


class PersistentProgramRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_program(
        self,
        *,
        owner: str,
        title: str,
        objective: str,
        jobs: Iterable[ProgramJobSpec],
        dependencies: Iterable[tuple[str, str]],
        max_active_jobs: int = 6,
    ) -> CalyxProgram:
        specs = list(jobs)
        if not 1 <= max_active_jobs <= 6:
            raise ValueError("PROGRAM_ACTIVE_LIMIT_INVALID")
        keys = [item.job_key for item in specs]
        if len(keys) != len(set(keys)):
            raise ValueError("DUPLICATE_PROGRAM_JOB_KEY")
        serialized_inputs = {spec.job_key: spec.serialized_inputs for spec in specs}
        program = CalyxProgram(
            owner=owner,
            title=title,
            objective=objective,
            max_active_jobs=max_active_jobs,
            status="draft",
        )
        self.db.add(program)
        self.db.flush()
        by_key: dict[str, CalyxProgramJob] = {}
        for spec in specs:
            job = CalyxProgramJob(
                program_id=program.program_id,
                job_key=spec.job_key,
                role_key=spec.role_key,
                title=spec.title,
                repository=spec.repository,
                branch=spec.branch,
                mutating=spec.mutating,
                input_json=serialized_inputs[spec.job_key],
                work_fingerprint=spec.fingerprint,
                status="waiting",
            )
            self.db.add(job)
            self.db.flush()
            by_key[spec.job_key] = job
        edges = list(dependencies)
        for upstream_key, downstream_key in edges:
            if upstream_key == downstream_key:
                raise ValueError("SELF_DEPENDENCY")
            if upstream_key not in by_key or downstream_key not in by_key:
                raise ValueError("DEPENDENCY_JOB_NOT_FOUND")
            self.db.add(
                CalyxProgramDependency(
                    program_id=program.program_id,
                    upstream_program_job_id=by_key[upstream_key].program_job_id,
                    downstream_program_job_id=by_key[downstream_key].program_job_id,
                )
            )
        self._assert_acyclic(by_key, edges)
        self.db.commit()
        self.db.refresh(program)
        return program

    @staticmethod
    def _assert_acyclic(by_key: dict[str, CalyxProgramJob], edges: list[tuple[str, str]]) -> None:
        children: dict[str, list[str]] = {key: [] for key in by_key}
        indegree: dict[str, int] = {key: 0 for key in by_key}
        for upstream, downstream in edges:
            children[upstream].append(downstream)
            indegree[downstream] += 1
        queue = [key for key, count in indegree.items() if count == 0]
        visited = 0
        while queue:
            key = queue.pop()
            visited += 1
            for child in children[key]:
                indegree[child] -= 1
                if indegree[child] == 0:
                    queue.append(child)
        if visited != len(by_key):
            raise ValueError("CYCLIC_DEPENDENCY")

    def start(self, *, owner: str, program_id: str) -> CalyxProgram:
        program = self._owned(owner, program_id)
        if program.status not in {"draft", "paused"}:
            raise ValueError("PROGRAM_NOT_STARTABLE")
        program.status = "running"
        program.paused = False
        self.release_ready_jobs(program_id=program_id)
        self.db.commit()
        self.db.refresh(program)
        return program

    def pause(self, *, owner: str, program_id: str) -> CalyxProgram:
        program = self._owned(owner, program_id)
        if program.status != "running":
            raise ValueError("PROGRAM_NOT_RUNNING")
        program.status = "paused"
        program.paused = True
        self.db.commit()
        self.db.refresh(program)
        return program

    def cancel(self, *, owner: str, program_id: str, reason: str) -> CalyxProgram:
        program = self._owned(owner, program_id)
        if program.status in {"completed", "cancelled"}:
            raise ValueError("PROGRAM_TERMINAL")
        program.status = "cancelled"
        program.paused = False
        program.cancellation_reason = reason
        waiting = self.db.scalars(
            select(CalyxProgramJob).where(
                CalyxProgramJob.program_id == program_id,
                CalyxProgramJob.status.in_(("waiting", "queued")),
            )
        ).all()
        for job in waiting:
            job.status = "cancelled"
            job.outcome = "CANCELLED"
            job.completed_at = utcnow()
        self.db.commit()
        self.db.refresh(program)
        return program

    def record_outcome(
        self,
        *,
        owner: str,
        program_id: str,
        job_key: str,
        outcome: str,
        evidence: dict | None = None,
        blocker: str | None = None,
        human_action: str | None = None,
    ) -> CalyxProgramJob:
        if outcome not in TERMINAL_OUTCOMES:
            raise ValueError("OUTCOME_INVALID")
        self._owned(owner, program_id)
        job = self.db.scalar(
            select(CalyxProgramJob).where(
                CalyxProgramJob.program_id == program_id,
                CalyxProgramJob.job_key == job_key,
            )
        )
        if job is None:
            raise LookupError("PROGRAM_JOB_NOT_FOUND")
        if job.outcome is not None:
            raise ValueError("AUTHORITATIVE_OUTCOME_ALREADY_RECORDED")
        job.outcome = outcome
        job.status = "completed" if outcome in SUCCESSFUL_OUTCOMES else "blocked"
        job.evidence_json = json.dumps(evidence or {}, sort_keys=True, default=str)
        job.blocker = blocker
        job.human_action = human_action
        job.completed_at = utcnow()
        self.release_ready_jobs(program_id=program_id)
        self._refresh_program_status(program_id)
        self.db.commit()
        self.db.refresh(job)
        return job

    def release_ready_jobs(self, *, program_id: str) -> list[CalyxProgramJob]:
        program = self.db.get(CalyxProgram, program_id)
        if program is None or program.status != "running" or program.paused:
            return []
        jobs = self.db.scalars(
            select(CalyxProgramJob).where(CalyxProgramJob.program_id == program_id)
        ).all()
        by_id = {job.program_job_id: job for job in jobs}
        deps = self.db.scalars(
            select(CalyxProgramDependency).where(CalyxProgramDependency.program_id == program_id)
        ).all()
        upstreams: dict[str, list[CalyxProgramJob]] = {job.program_job_id: [] for job in jobs}
        for dep in deps:
            upstreams[dep.downstream_program_job_id].append(by_id[dep.upstream_program_job_id])
        released: list[CalyxProgramJob] = []
        for job in jobs:
            if job.status != "waiting":
                continue
            parents = upstreams[job.program_job_id]
            if any(parent.outcome in (TERMINAL_OUTCOMES - SUCCESSFUL_OUTCOMES) for parent in parents):
                job.status = "blocked"
                job.outcome = "BLOCKED"
                job.blocker = "UPSTREAM_JOB_FAILED"
                job.human_action = "Resolve or replace the failed prerequisite, then create a new governed program revision."
                job.completed_at = utcnow()
                continue
            if all(parent.outcome in SUCCESSFUL_OUTCOMES for parent in parents):
                job.status = "queued"
                released.append(job)
        return released

    def snapshot(self, *, owner: str, program_id: str) -> dict:
        program = self._owned(owner, program_id)
        jobs = self.db.scalars(
            select(CalyxProgramJob)
            .where(CalyxProgramJob.program_id == program_id)
            .order_by(CalyxProgramJob.created_at.asc())
        ).all()
        deps = self.db.scalars(
            select(CalyxProgramDependency).where(CalyxProgramDependency.program_id == program_id)
        ).all()
        by_id = {job.program_job_id: job.job_key for job in jobs}
        return {
            "program_id": program.program_id,
            "title": program.title,
            "objective": program.objective,
            "status": program.status,
            "paused": program.paused,
            "max_active_jobs": program.max_active_jobs,
            "jobs": [
                {
                    "job_key": job.job_key,
                    "role_key": job.role_key,
                    "title": job.title,
                    "repository": job.repository,
                    "branch": job.branch,
                    "mutating": job.mutating,
                    **self._input_manifest_metadata(job.input_json),
                    "status": job.status,
                    "outcome": job.outcome,
                    "blocker": job.blocker,
                    "human_action": job.human_action,
                }
                for job in jobs
            ],
            "dependencies": [
                {
                    "upstream": by_id[dep.upstream_program_job_id],
                    "downstream": by_id[dep.downstream_program_job_id],
                }
                for dep in deps
            ],
        }

    @staticmethod
    def _input_manifest_metadata(input_json: str | None) -> dict[str, object]:
        if not input_json:
            return {
                "input_manifest_present": False,
                "input_manifest_sha256": None,
                "input_manifest_keys": [],
            }
        try:
            value = json.loads(input_json)
        except json.JSONDecodeError:
            return {
                "input_manifest_present": True,
                "input_manifest_sha256": hashlib.sha256(input_json.encode()).hexdigest(),
                "input_manifest_keys": [],
                "input_manifest_invalid": True,
            }
        keys = sorted(str(key) for key in value) if isinstance(value, dict) else []
        return {
            "input_manifest_present": True,
            "input_manifest_sha256": hashlib.sha256(input_json.encode()).hexdigest(),
            "input_manifest_keys": keys,
        }

    def _refresh_program_status(self, program_id: str) -> None:
        program = self.db.get(CalyxProgram, program_id)
        if program is None:
            return
        jobs = self.db.scalars(
            select(CalyxProgramJob).where(CalyxProgramJob.program_id == program_id)
        ).all()
        if jobs and all(job.outcome in SUCCESSFUL_OUTCOMES for job in jobs):
            program.status = "completed"
            program.completed_at = utcnow()
        elif any(job.outcome in (TERMINAL_OUTCOMES - SUCCESSFUL_OUTCOMES) for job in jobs):
            unfinished = [job for job in jobs if job.outcome is None]
            if not unfinished:
                program.status = "blocked"

    def _owned(self, owner: str, program_id: str) -> CalyxProgram:
        program = self.db.get(CalyxProgram, program_id)
        if program is None or program.owner != owner:
            raise LookupError("PROGRAM_NOT_FOUND")
        return program
