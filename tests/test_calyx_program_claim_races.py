"""Two-session races on the program-job claim, release and recovery paths.

Each race is interleaved deterministically: one worker is paused at the exact
point between reading a row and writing it, and the other worker commits a
conflicting change in a separate session in that window. The second write must
then be fenced out, not applied by primary key.

Runs on a SQLite file and, when a test database is available, on PostgreSQL
(a disposable schema, dropped afterwards).
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
from app.calyx_orchestrator.engineering_core import EngineeringAdmissionPolicy
from app.calyx_orchestrator.models import CalyxJob, utcnow
from app.calyx_orchestrator.program_models import (
    CalyxProgram,
    CalyxProgramDependency,
    CalyxProgramJob,
)
from app.database import Base
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.calyx_orchestrator.program_repository import (
    PersistentProgramRepository,
    ProgramJobSpec,
)
from app.calyx_orchestrator.program_worker import PersistentProgramWorker

TABLES = [
    CalyxJob.__table__,
    CalyxProgram.__table__,
    CalyxProgramJob.__table__,
    CalyxProgramDependency.__table__,
]


@pytest.fixture(
    params=[
        "sqlite_file",
        pytest.param("postgres", marks=pytest.mark.requires_postgres),
    ]
)
def sessions(request, tmp_path):
    if request.param == "sqlite_file":
        engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'races.db'}")
        Base.metadata.create_all(engine, tables=TABLES)
        try:
            yield sessionmaker(engine)
        finally:
            engine.dispose()
        return
    from tests.acquisition_ledger_backends import disposable_postgres_schema

    with disposable_postgres_schema() as (engine, _schema):
        Base.metadata.create_all(engine, tables=TABLES)
        yield sessionmaker(engine)


def _one_job_program(db) -> CalyxProgram:
    repository = PersistentProgramRepository(db)
    program = repository.create_program(
        owner="owner",
        title="race",
        objective="prove fenced claim, release and recovery",
        jobs=[ProgramJobSpec("one", "backend_engineer", "one", "repo-a", "b", True)],
        dependencies=[],
    )
    repository.start(owner="owner", program_id=program.program_id)
    return program


class _InterleavingPolicy(EngineeringAdmissionPolicy):
    """Runs ``interleave`` once, after the candidate was read, before its UPDATE."""

    def __init__(self, interleave) -> None:
        super().__init__()
        self._interleave = interleave
        self.fired = False

    def evaluate(self, candidate, active):
        if not self.fired:
            self.fired = True
            self._interleave()
        return super().evaluate(candidate, active)


def test_claim_cannot_take_a_job_through_a_concurrent_backoff(sessions):
    # Worker A reads the queued job (attempt 0). Before A's claim UPDATE,
    # worker B claims it, fails, and releases it with a 60 s backoff. A must
    # not then claim attempt 2 inside that backoff.
    with sessions() as a_db, sessions() as b_db:
        _one_job_program(a_db)
        worker_b = PersistentProgramWorker(b_db)
        released: dict[str, object] = {}

        def b_fails_and_backs_off() -> None:
            job = worker_b.claim(worker_id="worker-b")
            assert job is not None and job.attempt_count == 1
            back = worker_b.release_failed_attempt(
                program_job_id=job.program_job_id,
                worker_id="worker-b",
                lease_token=job.lease_token,
                error_code="SYNTHETIC_EXECUTOR_FAILURE",
                exception_type="RuntimeError",
            )
            released["evidence"] = back.evidence_json
            released["id"] = back.program_job_id

        policy = _InterleavingPolicy(b_fails_and_backs_off)
        claimed = PersistentProgramWorker(a_db, policy=policy).claim(worker_id="worker-a")
        assert policy.fired
        assert claimed is None

        with sessions() as check_db:
            job = check_db.get(CalyxProgramJob, released["id"])
            assert job.status == "queued"
            assert job.attempt_count == 1
            assert job.lease_token is None
            assert job.evidence_json == released["evidence"]
            record = json.loads(job.evidence_json)
            assert record["schema"] == "calyx.program-job-retry-backoff.v1"


def test_recovery_does_not_erase_a_concurrent_release(sessions):
    # Recovery reads an expired lease; before it writes, the lease holder
    # releases the attempt with a backoff record. The recovery UPDATE must
    # match nothing and leave the failure history in place.
    with sessions() as holder_db, sessions() as recovery_db:
        _one_job_program(holder_db)
        holder = PersistentProgramWorker(holder_db)
        claimed = holder.claim(worker_id="holder", lease_seconds=60)
        assert claimed is not None
        job_id, token = claimed.program_job_id, claimed.lease_token
        claimed.lease_expires_at = utcnow() - timedelta(seconds=1)
        holder_db.commit()

        class RacingRecovery(PersistentProgramWorker):
            def _select_expired_leases(self, *, now, owner):
                rows = super()._select_expired_leases(now=now, owner=owner)
                assert [row.program_job_id for row in rows] == [job_id]
                holder.release_failed_attempt(
                    program_job_id=job_id,
                    worker_id="holder",
                    lease_token=token,
                    error_code="SYNTHETIC_EXECUTOR_FAILURE",
                    exception_type="RuntimeError",
                )
                return rows

        assert RacingRecovery(recovery_db).recover_expired_leases() == 0

        with sessions() as check_db:
            job = check_db.get(CalyxProgramJob, job_id)
            assert job.status == "queued"
            record = json.loads(job.evidence_json or "{}")
            assert record["schema"] == "calyx.program-job-retry-backoff.v1"
            assert record["failures"][0]["error_code"] == "SYNTHETIC_EXECUTOR_FAILURE"


def test_release_after_recovery_is_refused_not_double_applied(sessions):
    # The other order: recovery commits first, then the old holder's release
    # arrives with a lease token that no longer exists.
    with sessions() as holder_db, sessions() as recovery_db:
        _one_job_program(holder_db)
        holder = PersistentProgramWorker(holder_db)
        claimed = holder.claim(worker_id="holder", lease_seconds=60)
        assert claimed is not None
        job_id, token = claimed.program_job_id, claimed.lease_token
        claimed.lease_expires_at = utcnow() - timedelta(seconds=1)
        holder_db.commit()

        assert PersistentProgramWorker(recovery_db).recover_expired_leases() == 1
        with pytest.raises(PermissionError, match="STALE_PROGRAM_JOB_LEASE"):
            holder.release_failed_attempt(
                program_job_id=job_id,
                worker_id="holder",
                lease_token=token,
                error_code="late",
                exception_type="RuntimeError",
            )
        with sessions() as check_db:
            job = check_db.get(CalyxProgramJob, job_id)
            assert job.status == "queued"
            assert job.attempt_count == 1
            assert job.evidence_json is None

