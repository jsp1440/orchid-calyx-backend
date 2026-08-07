from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.dry_run_service import execute_deterministic_dry_run
from app.calyx_orchestrator.execution_bridge import decode_receipt_evidence
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


def _claimed(db: Session, *, owner: str = "owner"):
    repository = PersistentProgramRepository(db)
    program = repository.create_program(
        owner=owner,
        title="dry-run program",
        objective="prove the bounded execution loop",
        jobs=[ProgramJobSpec("source", "brain_engineer", "Inspect source", "repo", "branch", True)],
        dependencies=[],
    )
    repository.start(owner=owner, program_id=program.program_id)
    job = PersistentProgramWorker(db).claim(worker_id="worker", owner=owner)
    assert job is not None and job.lease_token
    return program, job


def test_deterministic_dry_run_executes_and_records_verified_receipt():
    with _db() as db:
        program, job = _claimed(db)
        token = job.lease_token
        result = execute_deterministic_dry_run(
            db,
            owner="owner",
            program_job_id=job.program_job_id,
            worker_id="worker",
            lease_token=token,
        )
        assert result.assignment["assignment_id"] == job.program_job_id
        assert result.receipt["executor_key"] == "deterministic_dry_run_v1"
        assert result.receipt["state"] == "delivered"
        assert result.receipt["output"]["side_effects"] == []
        assert result.completed_job["outcome"] == "DELIVERED"

        completed = db.get(CalyxProgramJob, job.program_job_id)
        assert completed is not None
        assert completed.status == "completed"
        assert completed.lease_token is None
        evidence = decode_receipt_evidence(completed)
        assert evidence["receipt_type"] == "execution"
        assert evidence["output_checksum"] == result.receipt["output_checksum"]
        db.refresh(program)
        assert program.status == "completed"


def test_dry_run_rejects_cross_owner_and_stale_lease_without_consuming_job():
    with _db() as db:
        _, job = _claimed(db)
        token = job.lease_token
        try:
            execute_deterministic_dry_run(
                db,
                owner="wrong-owner",
                program_job_id=job.program_job_id,
                worker_id="worker",
                lease_token=token,
            )
        except LookupError as exc:
            assert str(exc) == "PROGRAM_JOB_NOT_FOUND"
        else:
            raise AssertionError("cross-owner dry run was accepted")

        try:
            execute_deterministic_dry_run(
                db,
                owner="owner",
                program_job_id=job.program_job_id,
                worker_id="worker",
                lease_token="stale-token",
            )
        except PermissionError as exc:
            assert str(exc) == "STALE_PROGRAM_JOB_LEASE"
        else:
            raise AssertionError("stale lease was accepted")

        db.refresh(job)
        assert job.status == "running"
        assert job.outcome is None
        assert job.lease_token == token


def test_dry_run_replay_is_rejected_after_receipt_completion():
    with _db() as db:
        _, job = _claimed(db)
        token = job.lease_token
        execute_deterministic_dry_run(
            db,
            owner="owner",
            program_job_id=job.program_job_id,
            worker_id="worker",
            lease_token=token,
        )
        try:
            execute_deterministic_dry_run(
                db,
                owner="owner",
                program_job_id=job.program_job_id,
                worker_id="worker",
                lease_token=token,
            )
        except PermissionError as exc:
            assert str(exc) == "STALE_PROGRAM_JOB_LEASE"
        else:
            raise AssertionError("completed dry run was replayed")
