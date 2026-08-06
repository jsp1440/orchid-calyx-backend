from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.calyx_orchestrator.execution_bridge import LeaseExecutionBridge, decode_receipt_evidence
from app.calyx_orchestrator.executor import DeterministicDryRunExecutor, GovernedAssignment
from app.calyx_orchestrator.program_models import CalyxProgram, CalyxProgramDependency, CalyxProgramJob
from app.calyx_orchestrator.program_repository import PersistentProgramRepository, ProgramJobSpec
from app.calyx_orchestrator.program_worker import PersistentProgramWorker


def _db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[CalyxProgram.__table__, CalyxProgramJob.__table__, CalyxProgramDependency.__table__],
    )
    return Session(engine)


def _claimed(db: Session, *, with_downstream: bool = False):
    repository = PersistentProgramRepository(db)
    jobs = [ProgramJobSpec("source", "brain_engineer", "source", "repo", "branch", True)]
    dependencies = []
    if with_downstream:
        jobs.append(ProgramJobSpec("report", "engineering_director", "report", "repo"))
        dependencies.append(("source", "report"))
    program = repository.create_program(
        owner="owner",
        title="receipt bridge",
        objective="verify lease execution receipts",
        jobs=jobs,
        dependencies=dependencies,
    )
    repository.start(owner="owner", program_id=program.program_id)
    claimed = PersistentProgramWorker(db).claim(worker_id="worker")
    assert claimed is not None and claimed.lease_token
    return program, claimed


def _receipt(program_id: str, job: CalyxProgramJob, **overrides):
    values = {
        "assignment_id": job.program_job_id,
        "program_id": program_id,
        "job_key": job.job_key,
        "role_key": job.role_key,
        "objective": "bounded receipt execution",
        "inputs": {"job": job.job_key},
        "requested_capabilities": ("validate_input", "produce_receipt"),
        "evidence_uris": ("github:issue/438",),
    }
    values.update(overrides)
    return DeterministicDryRunExecutor().execute(GovernedAssignment(**values))


def test_delivered_receipt_completes_lease_and_releases_dependency():
    with _db() as db:
        program, claimed = _claimed(db, with_downstream=True)
        completed = LeaseExecutionBridge(db).complete_from_receipt(
            program_job_id=claimed.program_job_id,
            worker_id="worker",
            lease_token=claimed.lease_token,
            receipt=_receipt(program.program_id, claimed),
        )
        assert completed.outcome == "DELIVERED"
        assert completed.lease_token is None
        evidence = decode_receipt_evidence(completed)
        assert evidence["receipt_type"] == "execution"
        assert evidence["output_checksum"]
        next_job = PersistentProgramWorker(db).claim(worker_id="director")
        assert next_job is not None and next_job.job_key == "report"


def test_receipt_identity_mismatch_is_rejected_without_consuming_lease():
    with _db() as db:
        program, claimed = _claimed(db)
        bridge = LeaseExecutionBridge(db)
        receipt = _receipt(program.program_id, claimed, assignment_id="wrong")
        try:
            bridge.complete_from_receipt(
                program_job_id=claimed.program_job_id,
                worker_id="worker",
                lease_token=claimed.lease_token,
                receipt=receipt,
            )
        except ValueError as exc:
            assert str(exc) == "RECEIPT_ASSIGNMENT_MISMATCH"
        else:
            raise AssertionError("mismatched receipt was accepted")
        db.refresh(claimed)
        assert claimed.status == "running"
        assert claimed.outcome is None


def test_cancellation_persists_explicit_receipt_and_rejects_stale_replay():
    with _db() as db:
        _, claimed = _claimed(db)
        token = claimed.lease_token
        bridge = LeaseExecutionBridge(db)
        completed = bridge.cancel(
            program_job_id=claimed.program_job_id,
            worker_id="worker",
            lease_token=token,
            reason="Superseded by a corrected governed assignment.",
        )
        assert completed.outcome == "CANCELLED"
        assert decode_receipt_evidence(completed)["reason"].startswith("Superseded")
        try:
            bridge.cancel(
                program_job_id=claimed.program_job_id,
                worker_id="worker",
                lease_token=token,
                reason="duplicate",
            )
        except PermissionError as exc:
            assert str(exc) == "STALE_PROGRAM_JOB_LEASE"
        else:
            raise AssertionError("stale cancellation replay was accepted")


def test_timeout_receipt_is_persisted_as_blocked_with_action():
    with _db() as db:
        program, claimed = _claimed(db)
        completed = LeaseExecutionBridge(db).complete_from_receipt(
            program_job_id=claimed.program_job_id,
            worker_id="worker",
            lease_token=claimed.lease_token,
            receipt=_receipt(program.program_id, claimed, timeout_seconds=0),
        )
        assert completed.outcome == "BLOCKED"
        assert completed.blocker == "INVALID_OR_EXPIRED_TIMEOUT"
        assert "bounded governed retry" in completed.human_action
