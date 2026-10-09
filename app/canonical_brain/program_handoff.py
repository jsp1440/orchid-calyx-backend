"""Durable handoff adapted from the preserved canonical Brain queue repair."""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import select, text

from app.calyx_orchestrator.executor_registry import AUTONOMY_PROBE_ROLE, AuthoritativeExecutorRegistry
from app.calyx_orchestrator.program_models import CalyxProgram, CalyxProgramJob
from app.calyx_orchestrator.program_repository import PersistentProgramRepository, ProgramJobSpec

from .build_queue import BuildQueueSnapshot
from .scheduler_bridge import SchedulerJobMetadata, project_governed_queue


def persist_governed_queue(
    db, *, owner: str, queue: BuildQueueSnapshot,
    metadata: tuple[SchedulerJobMetadata, ...],
    dependencies: tuple[tuple[str, str], ...], inputs: dict[str, dict[str, object]],
):
    """Use native program/lease/dependency workers; never infer executor roles."""
    owner = owner.strip()
    if not owner:
        raise ValueError("BRAIN_HANDOFF_OWNER_REQUIRED")
    if not queue.items:
        raise ValueError("BRAIN_HANDOFF_EMPTY")
    project_governed_queue(queue=queue, metadata=metadata, dependencies=dependencies)
    if any(item.status != "admitted" or item.admission.status != "admitted"
           for item in queue.items):
        raise PermissionError("BRAIN_HANDOFF_NOT_ADMITTED")
    ids = {item.build_id for item in queue.items}
    if set(inputs) != ids:
        raise ValueError("BRAIN_HANDOFF_INPUT_IDENTITIES_MISMATCH")
    if any(up not in ids or down not in ids for up, down in dependencies):
        raise ValueError("BRAIN_HANDOFF_DEPENDENCY_IDENTITIES_MISMATCH")
    by_id = {item.build_id: item for item in queue.items}
    registry = AuthoritativeExecutorRegistry()
    specs = []
    for record in sorted(metadata, key=lambda item: item.build_id):
        if record.role_key == AUTONOMY_PROBE_ROLE:
            raise PermissionError("BRAIN_HANDOFF_TEST_EXECUTOR_PROHIBITED")
        executor = registry.require_authoritative(record.role_key)
        if record.mutating or executor.workspace_mutation:
            raise PermissionError("BRAIN_HANDOFF_READ_ONLY_REQUIRED")
        specs.append(ProgramJobSpec(
            job_key=record.build_id, role_key=record.role_key,
            title=f"Governed Brain build: {record.build_id}",
            repository=record.repository, branch=record.branch,
            inputs={
                **inputs[record.build_id],
                "brain_provenance": {
                    "build_id": record.build_id,
                    "architecture_id": by_id[record.build_id].architecture_id,
                    "admission": by_id[record.build_id].admission.model_dump(mode="json"),
                },
            },
        ))
    PersistentProgramRepository._assert_acyclic(
        {spec.job_key: spec for spec in specs}, list(dependencies),
    )
    keys = hashlib.sha256(json.dumps(sorted(ids)).encode()).hexdigest()
    manifest = hashlib.sha256(json.dumps({
        "jobs": [spec.fingerprint for spec in specs],
        "dependencies": sorted(set(dependencies)),
    }, sort_keys=True).encode()).hexdigest()
    prefix = f"canonical-brain-queue.v1:{keys}:"
    objective = prefix + manifest
    if db.get_bind().dialect.name != "postgresql":
        raise PermissionError("BRAIN_HANDOFF_POSTGRESQL_REQUIRED")
    # Owner-wide serialization also prevents overlap between different batches.
    lock_key = int.from_bytes(
        hashlib.sha256(f"canonical-brain-queue.v1:{owner}".encode()).digest()[:8],
        "big", signed=True,
    )

    def locked_existing():
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})
        matches = db.scalars(select(CalyxProgram).where(
            CalyxProgram.owner == owner, CalyxProgram.objective.startswith(prefix),
        ).execution_options(populate_existing=True)).all()
        if len(matches) > 1 or (matches and matches[0].objective != objective):
            raise ValueError("BRAIN_HANDOFF_IDENTITY_CONFLICT")
        if not matches:
            overlap = db.scalar(select(CalyxProgramJob.program_job_id).join(
                CalyxProgram, CalyxProgram.program_id == CalyxProgramJob.program_id,
            ).where(
                CalyxProgram.owner == owner,
                CalyxProgram.objective.startswith("canonical-brain-queue.v1:"),
                CalyxProgramJob.job_key.in_(ids),
            ).limit(1))
            if overlap is not None:
                raise ValueError("BRAIN_HANDOFF_BUILD_ALREADY_QUEUED")
        return matches[0] if matches else None

    repo = PersistentProgramRepository(db)
    program = locked_existing()
    if program is None:
        program = repo.create_program(
            owner=owner, title="Governed Brain queue", objective=objective, jobs=specs,
            dependencies=sorted(set(dependencies)), max_active_jobs=1,
        )
        program = locked_existing()
    if program.status == "draft":
        program = repo.start(owner=owner, program_id=program.program_id)
    else:
        # Replays do not resume paused/cancelled jobs or repeat completed work.
        db.commit()
    return program
