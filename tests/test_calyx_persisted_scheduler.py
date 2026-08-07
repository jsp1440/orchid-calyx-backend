from __future__ import annotations

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.calyx_orchestrator.persisted_scheduler import (
    persisted_schedule_status,
    project_persisted_schedule,
)
from app.calyx_orchestrator.program_models import (
    CalyxProgram,
    CalyxProgramDependency,
    CalyxProgramJob,
)
from app.calyx_orchestrator.program_repository import (
    PersistentProgramRepository,
    ProgramJobSpec,
)
from app.calyx_orchestrator.program_worker import PersistentProgramWorker
from app.database import Base


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[CalyxProgram.__table__, CalyxProgramJob.__table__, CalyxProgramDependency.__table__],
    )
    return Session(engine)


def _program(
    db: Session,
    *,
    title: str,
    jobs: list[ProgramJobSpec],
    dependencies=(),
    max_active_jobs: int = 6,
) -> CalyxProgram:
    repository = PersistentProgramRepository(db)
    program = repository.create_program(
        owner="owner",
        title=title,
        objective="persisted scheduler integration",
        jobs=jobs,
        dependencies=dependencies,
    )
    program.max_active_jobs = max_active_jobs
    db.commit()
    repository.start(owner="owner", program_id=program.program_id)
    return program


def test_duplicate_job_keys_across_programs_remain_distinct():
    with _db() as db:
        _program(db, title="one", jobs=[ProgramJobSpec("source", "brain_engineer", "one", "repo-a")])
        _program(db, title="two", jobs=[ProgramJobSpec("source", "atlas_engineer", "two", "repo-b")])
        schedule = project_persisted_schedule(db, owner="owner")
        assert len(schedule.runnable_program_job_ids) == 2
        assert len(set(schedule.snapshot.runnable_order)) == 2
        assert all(key.endswith(":source") for key in schedule.snapshot.runnable_order)


def test_per_program_capacity_is_enforced_in_shared_projection():
    with _db() as db:
        program = _program(
            db,
            title="bounded",
            max_active_jobs=1,
            jobs=[
                ProgramJobSpec("one", "brain_engineer", "one", "repo-a"),
                ProgramJobSpec("two", "atlas_engineer", "two", "repo-b"),
            ],
        )
        first = db.scalar(
            select(CalyxProgramJob).where(
                CalyxProgramJob.program_id == program.program_id,
                CalyxProgramJob.job_key == "one",
            )
        )
        assert first is not None
        first.status = "running"
        first.lease_owner = "worker"
        first.lease_token = "token"
        db.commit()

        schedule = project_persisted_schedule(db, owner="owner")
        second_key = next(key for key in schedule.snapshot.decisions if key.job_key.endswith(":two"))
        assert second_key.code == "ARCHITECTURE_CAPACITY_REACHED"
        assert schedule.runnable_program_job_ids == ()


def test_worker_claim_uses_critical_path_order_not_creation_order():
    with _db() as db:
        _program(
            db,
            title="critical path",
            jobs=[
                ProgramJobSpec("short", "atlas_engineer", "short", "repo-b"),
                ProgramJobSpec("root", "brain_engineer", "root", "repo-a"),
                ProgramJobSpec("middle", "engineering_director", "middle", "repo-c"),
                ProgramJobSpec("report", "frontend_engineer", "report", "repo-d"),
            ],
            dependencies=[("root", "middle"), ("middle", "report")],
        )
        claimed = PersistentProgramWorker(db).claim(worker_id="worker")
        assert claimed is not None
        assert claimed.job_key == "root"


def test_mission_control_payload_matches_worker_admission():
    with _db() as db:
        _program(
            db,
            title="mission control",
            jobs=[ProgramJobSpec("source", "brain_engineer", "source", "repo-a")],
        )
        status = persisted_schedule_status(db, owner="owner")
        assert status["ready"] is True
        assert status["worker_claim_enforced"] is True
        assert status["production_activation"] is False
        assert status["runnable_order"][0]["job_key"] == "source"
        claimed = PersistentProgramWorker(db).claim(worker_id="worker")
        assert claimed is not None
        assert claimed.program_job_id == status["runnable_order"][0]["program_job_id"]
