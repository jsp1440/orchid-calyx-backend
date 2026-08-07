from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.assignment_factory import (
    SAFE_ASSIGNMENT_CAPABILITIES,
    assignment_payload,
    governed_assignment_from_claimed_job,
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


def _program(db: Session, *, owner: str, title: str):
    repository = PersistentProgramRepository(db)
    program = repository.create_program(
        owner=owner,
        title=title,
        objective=f"Objective for {title}",
        jobs=[ProgramJobSpec("source", "brain_engineer", "Analyze source", "repo", "branch", True)],
        dependencies=[],
    )
    repository.start(owner=owner, program_id=program.program_id)
    return program


def test_claim_is_owner_scoped_and_returns_deterministic_safe_assignment():
    with _db() as db:
        other = _program(db, owner="other-owner", title="other")
        owned = _program(db, owner="owner", title="owned")
        worker = PersistentProgramWorker(db)

        claimed = worker.claim(worker_id="worker", owner="owner")
        assert claimed is not None
        assert claimed.program_id == owned.program_id
        assert claimed.program_id != other.program_id

        assignment = governed_assignment_from_claimed_job(db, owner="owner", job=claimed)
        payload = assignment_payload(assignment)
        assert payload["assignment_id"] == claimed.program_job_id
        assert tuple(payload["requested_capabilities"]) == SAFE_ASSIGNMENT_CAPABILITIES
        assert payload["inputs"]["job"]["mutating_intent"] is True
        assert payload["inputs"]["governance"]["deployment_authorized"] is False
        assert payload["inputs"]["governance"]["publication_authorized"] is False
        assert payload["inputs"]["governance"]["production_graph_mutation_authorized"] is False
        assert payload["external_execution_authorized"] is False
        assert payload["input_checksum"] == assignment.verified_input_checksum()
        assert assignment_payload(assignment) == payload


def test_assignment_requires_matching_owner_and_live_lease():
    with _db() as db:
        _program(db, owner="owner", title="owned")
        claimed = PersistentProgramWorker(db).claim(worker_id="worker", owner="owner")
        assert claimed is not None

        try:
            governed_assignment_from_claimed_job(db, owner="wrong-owner", job=claimed)
        except LookupError as exc:
            assert str(exc) == "PROGRAM_NOT_FOUND"
        else:
            raise AssertionError("cross-owner assignment was created")

        claimed.lease_token = None
        db.commit()
        try:
            governed_assignment_from_claimed_job(db, owner="owner", job=claimed)
        except PermissionError as exc:
            assert str(exc) == "LIVE_PROGRAM_JOB_LEASE_REQUIRED"
        else:
            raise AssertionError("assignment without live lease was created")


def test_owner_scoped_claim_does_not_recover_other_owner_expired_lease():
    with _db() as db:
        _program(db, owner="other-owner", title="other")
        other_job = PersistentProgramWorker(db).claim(worker_id="other-worker", owner="other-owner")
        assert other_job is not None
        other_job.lease_expires_at = other_job.created_at
        db.commit()

        assert PersistentProgramWorker(db).recover_expired_leases(owner="owner") == 0
        db.refresh(other_job)
        assert other_job.status == "running"
