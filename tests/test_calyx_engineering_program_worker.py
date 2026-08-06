from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.database import Base
from app.calyx_orchestrator.models import utcnow
from app.calyx_orchestrator.program_models import CalyxProgram, CalyxProgramDependency, CalyxProgramJob
from app.calyx_orchestrator.program_repository import PersistentProgramRepository, ProgramJobSpec
from app.calyx_orchestrator.program_worker import PersistentProgramWorker


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[CalyxProgram.__table__, CalyxProgramJob.__table__, CalyxProgramDependency.__table__],
    )
    with Session(engine) as session:
        yield session


def _start(db: Session, jobs: list[ProgramJobSpec], dependencies=()) -> CalyxProgram:
    repository = PersistentProgramRepository(db)
    program = repository.create_program(
        owner="owner",
        title="worker test",
        objective="prove governed worker admission",
        jobs=jobs,
        dependencies=dependencies,
    )
    repository.start(owner="owner", program_id=program.program_id)
    return program


def test_claim_enforces_two_jobs_per_repository(db: Session) -> None:
    _start(
        db,
        [
            ProgramJobSpec("one", "backend_engineer", "one", "repo-a", "branch-1", True),
            ProgramJobSpec("two", "brain_engineer", "two", "repo-a", "branch-2", True),
            ProgramJobSpec("three", "knowledge_graph_engineer", "three", "repo-a", "branch-3", True),
            ProgramJobSpec("four", "frontend_engineer", "four", "repo-b", "branch-4", True),
        ],
    )
    worker = PersistentProgramWorker(db)
    first = worker.claim(worker_id="w1")
    second = worker.claim(worker_id="w2")
    third = worker.claim(worker_id="w3")
    assert first and second and third
    assert {first.repository, second.repository} == {"repo-a"}
    assert third.repository == "repo-b"


def test_claim_locks_one_mutator_per_branch(db: Session) -> None:
    _start(
        db,
        [
            ProgramJobSpec("one", "backend_engineer", "one", "repo-a", "shared", True),
            ProgramJobSpec("two", "brain_engineer", "two", "repo-a", "shared", True),
            ProgramJobSpec("three", "engineering_director", "three", "repo-a", None, False),
        ],
    )
    worker = PersistentProgramWorker(db)
    first = worker.claim(worker_id="w1")
    second = worker.claim(worker_id="w2")
    assert first and second
    assert first.branch == "shared"
    assert second.job_key == "three"


def test_completion_releases_downstream_job(db: Session) -> None:
    program = _start(
        db,
        [
            ProgramJobSpec("source", "backend_engineer", "source", "repo-a", "source", True),
            ProgramJobSpec("report", "engineering_director", "report", "repo-a"),
        ],
        dependencies=[("source", "report")],
    )
    worker = PersistentProgramWorker(db)
    source = worker.claim(worker_id="w1")
    assert source and source.lease_token
    worker.complete(
        program_job_id=source.program_job_id,
        worker_id="w1",
        lease_token=source.lease_token,
        outcome="DELIVERED",
        evidence={"test": True},
    )
    report = db.scalar(
        select(CalyxProgramJob).where(
            CalyxProgramJob.program_id == program.program_id,
            CalyxProgramJob.job_key == "report",
        )
    )
    assert report is not None
    assert report.status == "queued"
    assert worker.claim(worker_id="director").job_key == "report"


def test_expired_lease_requeues_without_duplicate_completion(db: Session) -> None:
    _start(db, [ProgramJobSpec("one", "backend_engineer", "one", "repo-a", "branch", True)])
    worker = PersistentProgramWorker(db)
    claimed = worker.claim(worker_id="w1", lease_seconds=60)
    assert claimed is not None
    claimed.lease_expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert worker.recover_expired_leases() == 1
    reclaimed = worker.claim(worker_id="w2")
    assert reclaimed is not None
    assert reclaimed.program_job_id == claimed.program_job_id
    assert reclaimed.attempt_count == 2
    with pytest.raises(PermissionError, match="STALE_PROGRAM_JOB_LEASE"):
        worker.complete(
            program_job_id=claimed.program_job_id,
            worker_id="w1",
            lease_token=claimed.lease_token or "stale",
            outcome="DELIVERED",
        )


def test_exhausted_expired_lease_dead_letters_once(db: Session) -> None:
    _start(db, [ProgramJobSpec("one", "backend_engineer", "one", "repo-a", "branch", True)])
    worker = PersistentProgramWorker(db)
    claimed = worker.claim(worker_id="w1")
    assert claimed is not None
    claimed.attempt_count = claimed.max_attempts
    claimed.lease_expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert worker.recover_expired_leases() == 1
    db.refresh(claimed)
    assert claimed.outcome == "DEAD_LETTER"
    assert claimed.status == "blocked"
    assert worker.recover_expired_leases() == 0
