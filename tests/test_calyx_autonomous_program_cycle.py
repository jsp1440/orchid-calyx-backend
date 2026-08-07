from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.autonomy_policy import (
    ProgramAutonomyPolicy,
    program_autonomy_status,
)
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
        # The dry-run executor is non-authoritative: its DELIVERED receipt is
        # reclassified as BLOCKED so that real engineering tasks are never
        # reported as delivered without genuine work.  Only job-0 is claimed;
        # the dependent jobs cascade to blocked via release_ready_jobs.
        assert result.stop_reason == "idle"
        assert result.attempted_jobs == 1
        assert result.completed_jobs == 1
        assert result.jobs[0].job_key == "job-0"
        assert result.jobs[0].outcome == "BLOCKED"
        assert result.jobs[0].receipt_state == "blocked"
        assert result.jobs[0].executor_key == "deterministic_dry_run_v1"

        db.refresh(program)
        assert program.status == "blocked"
        persisted = db.query(CalyxProgramJob).filter(CalyxProgramJob.program_id == program.program_id).all()
        by_key = {job.job_key: job for job in persisted}
        # job-0 was executed and reclassified; downstream jobs cascade via dependency resolution
        assert by_key["job-0"].status == "blocked"
        assert by_key["job-0"].outcome == "BLOCKED"
        assert by_key["job-0"].evidence_json and "deterministic_dry_run_v1" in by_key["job-0"].evidence_json
        assert by_key["job-0"].evidence_json and "DRY_RUN_REQUIRES_HUMAN_REVIEW" in by_key["job-0"].evidence_json


def test_dry_run_receipt_is_never_recorded_as_authoritative_delivered():
    """Confirm that a dry-run DELIVERED receipt is reclassified as BLOCKED and
    does NOT complete the program or release downstream jobs as if real work was done."""
    with _db() as db:
        program = _program(db, jobs=2)
        result = run_deterministic_program_cycle(
            db,
            owner="owner",
            worker_id="autonomy-worker",
            max_jobs=10,
        )
        assert result.stop_reason == "idle"
        # Only job-0 is attempted; downstream job-1 cascades to blocked
        assert result.attempted_jobs == 1
        job0 = result.jobs[0]
        assert job0.outcome == "BLOCKED"
        assert job0.receipt_state == "blocked"
        db.refresh(program)
        assert program.status == "blocked"


def test_cycle_enforces_job_budget_and_leaves_downstream_work_blocked_pending_human_review():
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
        # job-0 was reclassified as BLOCKED; job-1 cascades to blocked
        assert by_key["job-0"]["status"] == "blocked"
        assert by_key["job-1"]["status"] == "blocked"

        # A second cycle finds no claimable work because both jobs are already terminal
        second = run_deterministic_program_cycle(
            db,
            owner="owner",
            worker_id="autonomy-worker",
            max_jobs=1,
        )
        assert second.stop_reason == "idle"
        assert second.completed_jobs == 0


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
        assert own_job.status == "blocked"
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


def test_from_environ_empty_mapping_is_not_ambient_environment(monkeypatch):
    """from_environ({}) must use the explicit empty mapping, not os.environ.
    Even if the ambient environment has autonomy variables set, an explicit
    empty mapping must produce a disabled, fail-closed policy."""
    monkeypatch.setenv("CALYX_PROGRAM_AUTONOMY_ENABLED", "true")
    monkeypatch.setenv("CALYX_PROGRAM_AUTONOMY_OWNER", "injected-owner")
    # Passing {} explicitly: must NOT inherit the ambient env vars above
    policy = ProgramAutonomyPolicy.from_environ({})
    assert policy.enabled is False
    assert policy.owner == ""
    assert policy.status()["authorized"] is False


def test_autonomous_cycle_route_is_mounted_under_brain_orchestrator():
    from app.main import app

    paths = {route.path for route in app.routes}
    assert "/brain/orchestrator/programs/workers/run-cycle" in paths
