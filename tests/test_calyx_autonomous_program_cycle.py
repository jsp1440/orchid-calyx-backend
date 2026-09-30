from __future__ import annotations

from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.autonomy_policy import (
    ProgramAutonomyPolicy,
    program_autonomy_status,
)
from app.calyx_orchestrator.executor_registry import (
    AUTONOMY_PROBE_ROLE,
    AuthoritativeExecutorRegistry,
    AutonomyProbeExecutor,
    RegisteredExecutor,
)
from app.calyx_orchestrator.models import utcnow
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


def _program(
    db: Session,
    *,
    owner: str = "owner",
    jobs: int = 2,
    role_key: str = AUTONOMY_PROBE_ROLE,
) -> CalyxProgram:
    specs = [
        ProgramJobSpec(
            f"job-{index}",
            role_key,
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
        title="Autonomous authoritative probe cycle",
        objective="Prove automatic claim, authoritative receipt completion, and dependency release.",
        jobs=specs,
        dependencies=dependencies,
    )
    repository.start(owner=owner, program_id=program.program_id)
    return program


def test_cycle_runs_registered_authoritative_dependency_chain_without_manual_claim():
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
        assert all(item.executor_key == "autonomy_probe_v1" for item in result.jobs)

        db.refresh(program)
        assert program.status == "completed"
        persisted = db.query(CalyxProgramJob).filter(CalyxProgramJob.program_id == program.program_id).all()
        assert all(job.status == "completed" for job in persisted)
        assert all(job.outcome == "DELIVERED" for job in persisted)
        assert all(job.lease_token is None for job in persisted)
        assert all(job.evidence_json and "autonomy_probe_v1" in job.evidence_json for job in persisted)


def test_cycle_does_not_claim_unregistered_real_engineering_roles():
    with _db() as db:
        program = _program(db, jobs=2, role_key="brain_engineer")
        result = run_deterministic_program_cycle(
            db,
            owner="owner",
            worker_id="autonomy-worker",
            max_jobs=10,
        )
        assert result.stop_reason == "idle"
        assert result.attempted_jobs == 0
        assert result.completed_jobs == 0
        db.refresh(program)
        assert program.status == "running"
        persisted = db.query(CalyxProgramJob).filter(CalyxProgramJob.program_id == program.program_id).all()
        by_key = {job.job_key: job for job in persisted}
        assert by_key["job-0"].status == "queued"
        assert by_key["job-0"].outcome is None
        assert by_key["job-0"].attempt_count == 0
        assert by_key["job-1"].status == "waiting"
        assert by_key["job-1"].outcome is None


def test_cycle_enforces_job_budget_and_releases_downstream_probe_for_next_cycle():
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


def test_from_environ_empty_mapping_is_not_ambient_environment(monkeypatch):
    monkeypatch.setenv("CALYX_PROGRAM_AUTONOMY_ENABLED", "true")
    monkeypatch.setenv("CALYX_PROGRAM_AUTONOMY_OWNER", "injected-owner")
    policy = ProgramAutonomyPolicy.from_environ({})
    assert policy.enabled is False
    assert policy.owner == ""
    assert policy.status()["authorized"] is False


def test_autonomous_cycle_route_is_mounted_under_brain_orchestrator():
    from app.main import app

    paths = {route.path for route in app.routes}
    assert "/brain/orchestrator/programs/workers/run-cycle" in paths


class _FailingForJobKey:
    """Probe executor that raises for one job key and delegates otherwise."""

    executor_key = "autonomy_probe_v1"

    def __init__(self, failing_job_key: str) -> None:
        self.failing_job_key = failing_job_key
        self.delegate = AutonomyProbeExecutor()
        self.calls: list[str] = []

    def execute(self, assignment):
        self.calls.append(assignment.job_key)
        if assignment.job_key == self.failing_job_key:
            raise RuntimeError("SYNTHETIC_EXECUTOR_FAILURE")
        return self.delegate.execute(assignment)


def _independent_program(db: Session, *, jobs: int) -> CalyxProgram:
    repository = PersistentProgramRepository(db)
    program = repository.create_program(
        owner="owner",
        title="Independent probe jobs",
        objective="Prove one failing job does not abort the cycle.",
        jobs=[
            ProgramJobSpec(
                f"job-{index}",
                AUTONOMY_PROBE_ROLE,
                f"Independent job {index}",
                "jsp1440/orchid-calyx-backend",
                f"autonomy-{index}",
                False,
            )
            for index in range(jobs)
        ],
        dependencies=[],
    )
    repository.start(owner="owner", program_id=program.program_id)
    return program


def _registry_failing(job_key: str) -> tuple[AuthoritativeExecutorRegistry, _FailingForJobKey]:
    registry = AuthoritativeExecutorRegistry()
    executor = _FailingForJobKey(job_key)
    registry._by_role[AUTONOMY_PROBE_ROLE] = RegisteredExecutor(
        role_key=AUTONOMY_PROBE_ROLE,
        executor=executor,
        authoritative=True,
        external_side_effects=False,
    )
    return registry, executor


def test_one_failing_job_does_not_abort_the_cycle_and_retries_only_after_backoff(monkeypatch):
    import app.calyx_orchestrator.program_worker as program_worker_module

    with _db() as db:
        program = _independent_program(db, jobs=3)
        registry, executor = _registry_failing("job-0")
        start = utcnow()
        clock = {"now": start}
        monkeypatch.setattr(program_worker_module, "utcnow", lambda: clock["now"])

        first = run_deterministic_program_cycle(
            db, owner="owner", worker_id="autonomy-worker", max_jobs=10, registry=registry
        )
        # The two good jobs complete in the same cycle as the failure.
        assert first.stop_reason == "idle"
        assert first.attempted_jobs == 3
        assert first.completed_jobs == 2
        assert sorted(item.job_key for item in first.jobs) == ["job-1", "job-2"]
        assert first.error is None
        assert len(first.failures) == 1
        failure = first.failures[0]
        assert failure["job_key"] == "job-0"
        assert failure["code"] == "SYNTHETIC_EXECUTOR_FAILURE"
        assert failure["disposition"] == "retry_backoff"
        assert first.as_dict()["failed_jobs"] == 1

        failed = db.query(CalyxProgramJob).filter(CalyxProgramJob.job_key == "job-0").one()
        assert failed.status == "queued"
        assert failed.lease_token is None
        assert failed.lease_expires_at is None
        assert failed.attempt_count == 1

        # Not retried before its backoff elapses.
        clock["now"] = start + timedelta(seconds=30)
        waiting = run_deterministic_program_cycle(
            db, owner="owner", worker_id="autonomy-worker", max_jobs=10, registry=registry
        )
        assert waiting.attempted_jobs == 0
        assert executor.calls.count("job-0") == 1

        # Retried after the first backoff (60s), then after the doubled one (120s).
        clock["now"] = start + timedelta(seconds=61)
        second = run_deterministic_program_cycle(
            db, owner="owner", worker_id="autonomy-worker", max_jobs=10, registry=registry
        )
        assert second.attempted_jobs == 1
        assert second.failures[0]["disposition"] == "retry_backoff"
        clock["now"] = start + timedelta(seconds=61 + 119)
        assert run_deterministic_program_cycle(
            db, owner="owner", worker_id="autonomy-worker", max_jobs=10, registry=registry
        ).attempted_jobs == 0

        # The third failure hits the unchanged 3-attempt ceiling: dead letter,
        # blocked program, and exactly one follow-up repair job.
        clock["now"] = start + timedelta(seconds=61 + 121)
        third = run_deterministic_program_cycle(
            db, owner="owner", worker_id="autonomy-worker", max_jobs=10, registry=registry
        )
        assert third.attempted_jobs == 1
        assert third.failures[0]["disposition"] == "dead_letter"
        assert executor.calls.count("job-0") == 3
        db.refresh(program)
        assert program.status == "blocked"
        repairs = (
            db.query(CalyxProgramJob)
            .filter(CalyxProgramJob.job_key.like("dead-letter-repair:%"))
            .all()
        )
        assert len(repairs) == 1

        clock["now"] = start + timedelta(hours=2)
        after = run_deterministic_program_cycle(
            db, owner="owner", worker_id="autonomy-worker", max_jobs=10, registry=registry
        )
        assert after.attempted_jobs == 0
        assert executor.calls.count("job-0") == 3
