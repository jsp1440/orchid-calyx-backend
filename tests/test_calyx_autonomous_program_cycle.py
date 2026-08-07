from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.autonomy_policy import ProgramAutonomyPolicy, program_autonomy_status
from app.calyx_orchestrator.program_cycle import run_deterministic_program_cycle
from app.calyx_orchestrator.program_models import (
    CalyxProgram,
    CalyxProgramDependency,
    CalyxProgramJob,
)
from app.calyx_orchestrator.program_repository import (
    PersistentProgramRepository,
    ProgramJobSpec,
)
from app.database import Base
from runtime.program_autonomy_worker import run_once


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[CalyxProgram.__table__, CalyxProgramJob.__table__, CalyxProgramDependency.__table__],
    )
    return Session(engine)


def _program(db: Session, *, owner: str = "owner", jobs: int = 2) -> CalyxProgram:
    specs = [
        ProgramJobSpec(
            f"job-{index}",
            "brain_engineer",
            f"Autonomous job {index}",
            "jsp1440/orchid-calyx-backend",
            f"autonomy-{index}",
            False,
        )
        for index in range(jobs)
    ]
    dependencies = [
        (f"job-{index}", f"job-{index + 1}") for index in range(max(0, jobs - 1))
    ]
    repository = PersistentProgramRepository(db)
    program = repository.create_program(
        owner=owner,
        title="Autonomous deterministic cycle",
        objective="Prove automatic claim, execution, receipt completion, and dependency release.",
        jobs=specs,
        dependencies=dependencies,
    )
    repository.start(owner=owner, program_id=program.program_id)
    return program


def test_cycle_runs_dependency_chain_to_completion_without_manual_claim_or_execute():
    with _db() as db:
        program = _program(db, jobs=3)
        result = run_deterministic_program_cycle(
            db,
            owner="owner",
            worker_id="autonomy-worker",
            max_jobs=10,
        )
        assert result.stop_reason == "idle"
        assert result.attempted_jobs == 3
        assert result.completed_jobs == 3
        assert [item.job_key for item in result.jobs] == ["job-0", "job-1", "job-2"]
        assert all(item.outcome == "DELIVERED" for item in result.jobs)
        assert all(item.receipt_state == "delivered" for item in result.jobs)
        assert all(item.executor_key == "deterministic_dry_run_v1" for item in result.jobs)

        db.refresh(program)
        assert program.status == "completed"
        persisted = db.query(CalyxProgramJob).filter(CalyxProgramJob.program_id == program.program_id).all()
        assert all(job.status == "completed" for job in persisted)
        assert all(job.outcome == "DELIVERED" for job in persisted)
        assert all(job.lease_token is None for job in persisted)
        assert all(job.evidence_json and "deterministic_dry_run_v1" in job.evidence_json for job in persisted)


def test_cycle_enforces_job_budget_and_leaves_downstream_work_released_for_next_cycle():
    with _db() as db:
        program = _program(db, jobs=2)
        first = run_deterministic_program_cycle(
            db,
            owner="owner",
            worker_id="autonomy-worker",
            max_jobs=1,
        )
        assert first.stop_reason == "budget_exhausted"
        assert first.completed_jobs == 1
        snapshot = PersistentProgramRepository(db).snapshot(owner="owner", program_id=program.program_id)
        by_key = {job["job_key"]: job for job in snapshot["jobs"]}
        assert by_key["job-0"]["status"] == "completed"
        assert by_key["job-1"]["status"] == "queued"

        second = run_deterministic_program_cycle(
            db,
            owner="owner",
            worker_id="autonomy-worker",
            max_jobs=1,
        )
        assert second.completed_jobs == 1
        assert second.jobs[0].job_key == "job-1"


def test_cycle_is_owner_scoped_and_does_not_claim_other_owner_programs():
    with _db() as db:
        own = _program(db, owner="owner", jobs=1)
        other = _program(db, owner="other", jobs=1)
        result = run_deterministic_program_cycle(
            db,
            owner="owner",
            worker_id="owner-worker",
            max_jobs=10,
        )
        assert result.completed_jobs == 1
        assert result.jobs[0].program_id == own.program_id
        own_job = db.query(CalyxProgramJob).filter(CalyxProgramJob.program_id == own.program_id).one()
        other_job = db.query(CalyxProgramJob).filter(CalyxProgramJob.program_id == other.program_id).one()
        assert own_job.status == "completed"
        assert other_job.status == "queued"
        assert other_job.attempt_count == 0


def test_idle_cycle_is_clean_and_non_mutating():
    with _db() as db:
        result = run_deterministic_program_cycle(
            db,
            owner="owner",
            worker_id="autonomy-worker",
            max_jobs=3,
        )
        assert result.stop_reason == "idle"
        assert result.attempted_jobs == 0
        assert result.completed_jobs == 0
        assert result.jobs == ()
        assert result.error is None


def test_continuous_worker_policy_fails_closed_until_enabled_with_owner():
    disabled = ProgramAutonomyPolicy.from_environ({})
    assert disabled.status()["authorized"] is False
    assert run_once(disabled)["executed"] is False

    status = program_autonomy_status({"CALYX_PROGRAM_AUTONOMY_ENABLED": "true"})
    assert status["valid"] is False
    assert status["authorized"] is False
    assert status["error"] == "CALYX_PROGRAM_AUTONOMY_OWNER_REQUIRED"

    enabled = ProgramAutonomyPolicy.from_environ(
        {
            "CALYX_PROGRAM_AUTONOMY_ENABLED": "true",
            "CALYX_PROGRAM_AUTONOMY_OWNER": "owner",
            "CALYX_PROGRAM_AUTONOMY_MAX_JOBS_PER_CYCLE": "4",
            "CALYX_PROGRAM_AUTONOMY_POLL_SECONDS": "30",
        }
    )
    state = enabled.status()
    assert state["authorized"] is True
    assert state["automatic_claim"] is True
    assert state["automatic_execution"] is True
    assert state["automatic_merge"] is False
    assert state["automatic_deployment"] is False
    assert state["automatic_publication"] is False


def test_autonomous_cycle_route_is_mounted_under_brain_orchestrator():
    from app.main import app

    paths = {route.path for route in app.routes}
    assert "/brain/orchestrator/programs/workers/run-cycle" in paths
