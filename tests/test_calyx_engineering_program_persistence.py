from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.calyx_orchestrator.program_models import (
    CalyxProgram,
    CalyxProgramDependency,
    CalyxProgramJob,
)
from app.calyx_orchestrator.program_repository import (
    PersistentProgramRepository,
    ProgramJobSpec,
)


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CalyxProgram.__table__,
            CalyxProgramJob.__table__,
            CalyxProgramDependency.__table__,
        ],
    )
    with Session(engine) as session:
        yield session


def _six_job_program(repository: PersistentProgramRepository):
    jobs = [
        ProgramJobSpec("ci", "build_devops_engineer", "CI repair audit", "jsp1440/orchid-calyx-backend"),
        ProgramJobSpec("api", "backend_engineer", "Protected API verification", "jsp1440/orchid-calyx-backend"),
        ProgramJobSpec("frontend", "frontend_engineer", "Frontend live-data plan", "jsp1440/orchid-continuum-frontend"),
        ProgramJobSpec("graph", "knowledge_graph_engineer", "Graph staging proof", "jsp1440/orchid-calyx-backend"),
        ProgramJobSpec("brain", "brain_engineer", "Brain retrieval mission", "jsp1440/orchid-calyx-backend"),
        ProgramJobSpec("report", "engineering_director", "Consolidated report", "jsp1440/orchid-calyx-backend"),
    ]
    dependencies = [(key, "report") for key in ("ci", "api", "frontend", "graph", "brain")]
    return repository.create_program(
        owner="owner",
        title="Phase 1 demonstration",
        objective="Prove automatic downstream release.",
        jobs=jobs,
        dependencies=dependencies,
    )


def test_five_roots_release_and_director_waits(db: Session) -> None:
    repository = PersistentProgramRepository(db)
    program = _six_job_program(repository)
    repository.start(owner="owner", program_id=program.program_id)

    snapshot = repository.snapshot(owner="owner", program_id=program.program_id)
    statuses = {job["job_key"]: job["status"] for job in snapshot["jobs"]}
    assert statuses["report"] == "waiting"
    assert {statuses[key] for key in ("ci", "api", "frontend", "graph", "brain")} == {"queued"}


def test_director_releases_only_after_all_prerequisites_succeed(db: Session) -> None:
    repository = PersistentProgramRepository(db)
    program = _six_job_program(repository)
    repository.start(owner="owner", program_id=program.program_id)

    for key in ("ci", "api", "frontend", "graph"):
        repository.record_outcome(
            owner="owner",
            program_id=program.program_id,
            job_key=key,
            outcome="DELIVERED",
            evidence={"fixture": key},
        )
    interim = repository.snapshot(owner="owner", program_id=program.program_id)
    assert next(job for job in interim["jobs"] if job["job_key"] == "report")["status"] == "waiting"

    repository.record_outcome(
        owner="owner",
        program_id=program.program_id,
        job_key="brain",
        outcome="NO_OP",
        evidence={"fixture": "brain"},
    )
    final = repository.snapshot(owner="owner", program_id=program.program_id)
    assert next(job for job in final["jobs"] if job["job_key"] == "report")["status"] == "queued"


def test_failed_prerequisite_blocks_director_with_human_action(db: Session) -> None:
    repository = PersistentProgramRepository(db)
    program = _six_job_program(repository)
    repository.start(owner="owner", program_id=program.program_id)
    repository.record_outcome(
        owner="owner",
        program_id=program.program_id,
        job_key="ci",
        outcome="BLOCKED",
        blocker="CI_CONFIGURATION_INVALID",
        human_action="Repair the workflow configuration.",
    )
    snapshot = repository.snapshot(owner="owner", program_id=program.program_id)
    report = next(job for job in snapshot["jobs"] if job["job_key"] == "report")
    assert report["status"] == "blocked"
    assert report["outcome"] == "BLOCKED"
    assert report["human_action"]


def test_duplicate_authoritative_outcome_is_rejected(db: Session) -> None:
    repository = PersistentProgramRepository(db)
    program = _six_job_program(repository)
    repository.start(owner="owner", program_id=program.program_id)
    repository.record_outcome(
        owner="owner",
        program_id=program.program_id,
        job_key="ci",
        outcome="DELIVERED",
    )
    with pytest.raises(ValueError, match="AUTHORITATIVE_OUTCOME_ALREADY_RECORDED"):
        repository.record_outcome(
            owner="owner",
            program_id=program.program_id,
            job_key="ci",
            outcome="DELIVERED",
        )


def test_cycle_is_rejected(db: Session) -> None:
    repository = PersistentProgramRepository(db)
    with pytest.raises(ValueError, match="CYCLIC_DEPENDENCY"):
        repository.create_program(
            owner="owner",
            title="invalid",
            objective="cycle",
            jobs=[
                ProgramJobSpec("a", "backend_engineer", "A", "repo"),
                ProgramJobSpec("b", "frontend_engineer", "B", "repo"),
            ],
            dependencies=[("a", "b"), ("b", "a")],
        )
