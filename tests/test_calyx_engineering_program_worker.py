from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.calyx_orchestrator.engineering_core import (
    AgentRole,
    EngineeringAdmissionPolicy,
    EngineeringWorkIdentity,
)
from app.calyx_orchestrator.models import utcnow
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


def test_diagnose_reports_idle_no_candidate_when_nothing_exists(db: Session) -> None:
    worker = PersistentProgramWorker(db)
    diagnostic = worker.diagnose()
    assert diagnostic.outcome == "IDLE_NO_CANDIDATE"
    assert diagnostic.program_job_id is None
    assert diagnostic.reason_code is None


def test_diagnose_reports_idle_no_candidate_when_role_filter_matches_nothing(db: Session) -> None:
    _start(db, [ProgramJobSpec("one", "backend_engineer", "one", "repo-a", "branch", True)])
    worker = PersistentProgramWorker(db)
    diagnostic = worker.diagnose(allowed_role_keys=frozenset({"github_coding_agent"}))
    assert diagnostic.outcome == "IDLE_NO_CANDIDATE"


def test_diagnose_surfaces_the_real_admission_rejection_reason(db: Session) -> None:
    """The exact previously-silent case: a mutating job with no branch is
    rejected by EngineeringAdmissionPolicy, and diagnose() must say so."""
    program = _start(
        db,
        [ProgramJobSpec("one", "github_coding_agent", "one", "repo-a", None, True)],
    )
    worker = PersistentProgramWorker(db)
    assert worker.claim(worker_id="w1", allowed_role_keys=frozenset({"github_coding_agent"})) is None

    diagnostic = worker.diagnose(allowed_role_keys=frozenset({"github_coding_agent"}))

    assert diagnostic.outcome == "REJECTED_ADMISSION"
    assert diagnostic.reason_code == "MUTATING_JOB_REQUIRES_BRANCH"
    assert diagnostic.reason_message
    jobs = db.scalars(select(CalyxProgramJob).where(CalyxProgramJob.program_id == program.program_id)).all()
    assert diagnostic.program_job_id == jobs[0].program_job_id


def test_diagnose_never_takes_a_lease_or_mutates_state(db: Session) -> None:
    """diagnose() must be safe to call repeatedly with zero side effects -
    it is meant to be called after every unsuccessful claim() without
    changing what a subsequent claim() attempt would see."""
    _start(db, [ProgramJobSpec("one", "github_coding_agent", "one", "repo-a", None, True)])
    worker = PersistentProgramWorker(db)

    before = db.scalars(select(CalyxProgramJob)).one()
    assert before.status == "queued"
    assert before.lease_owner is None

    worker.diagnose(allowed_role_keys=frozenset({"github_coding_agent"}))
    worker.diagnose(allowed_role_keys=frozenset({"github_coding_agent"}))

    db.expire_all()
    after = db.scalars(select(CalyxProgramJob)).one()
    assert after.status == "queued"
    assert after.lease_owner is None
    assert after.attempt_count == 0


def test_diagnose_reports_idle_when_claim_would_actually_succeed(db: Session) -> None:
    """If diagnose() is (unusually) called for a candidate that would
    actually be admitted, it must not falsely report a rejection."""
    _start(db, [ProgramJobSpec("one", "github_coding_agent", "one", "repo-a", "branch-1", True)])
    worker = PersistentProgramWorker(db)

    diagnostic = worker.diagnose(allowed_role_keys=frozenset({"github_coding_agent"}))

    assert diagnostic.outcome == "IDLE_NO_CANDIDATE"
    assert worker.recover_expired_leases() == 0


def test_diagnose_surfaces_repository_capacity_reached() -> None:
    """diagnose() must generalize to every EngineeringAdmissionPolicy
    rejection code, not just the one bug (MUTATING_JOB_REQUIRES_BRANCH)
    that originally motivated it. The scheduler layer (persisted_scheduler.py)
    independently caps runnable candidates per repository at 2 - the same
    as EngineeringAdmissionPolicy's own default - so a policy with a
    *tighter* limit than the scheduler's is required to prove the admission
    check itself still fires correctly, rather than always being preempted
    by the scheduler's own pre-filtering."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[CalyxProgram.__table__, CalyxProgramJob.__table__, CalyxProgramDependency.__table__],
    )
    with Session(engine) as db:
        _start(
            db,
            [
                ProgramJobSpec("one", "role-a", "one", "repo-a", "branch-1", True),
                ProgramJobSpec("two", "role-b", "two", "repo-a", "branch-2", True),
            ],
        )
        worker = PersistentProgramWorker(db, policy=EngineeringAdmissionPolicy(max_repository_active=1))
        assert worker.claim(worker_id="w1") is not None

        diagnostic = worker.diagnose()

        assert diagnostic.outcome == "REJECTED_ADMISSION"
        assert diagnostic.reason_code == "REPOSITORY_CAPACITY_REACHED"
        assert diagnostic.reason_message


def test_diagnose_surfaces_global_capacity_reached() -> None:
    """Same reasoning as the repository-capacity test above: the scheduler's
    own GLOBAL_PROGRAM_JOB_LIMIT (6) matches the admission policy's default,
    so a tighter injected policy is needed to prove the admission check
    itself, not the scheduler's pre-filter."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[CalyxProgram.__table__, CalyxProgramJob.__table__, CalyxProgramDependency.__table__],
    )
    with Session(engine) as db:
        _start(
            db,
            [
                ProgramJobSpec("one", "role-a", "one", "repo-a", "branch-1", True),
                ProgramJobSpec("two", "role-b", "two", "repo-b", "branch-2", True),
            ],
        )
        worker = PersistentProgramWorker(db, policy=EngineeringAdmissionPolicy(max_global_active=1))
        assert worker.claim(worker_id="w1") is not None

        diagnostic = worker.diagnose()

        assert diagnostic.outcome == "REJECTED_ADMISSION"
        assert diagnostic.reason_code == "GLOBAL_CAPACITY_REACHED"
        assert diagnostic.reason_message


def test_branch_mutation_locked_is_unreachable_through_diagnose_by_scheduler_design() -> None:
    """Genuine architectural finding, recorded as a test rather than left as
    a comment: unlike the capacity checks above, BRANCH_MUTATION_LOCKED
    cannot be reached through claim()/diagnose() at all, regardless of the
    injected admission policy. persisted_scheduler.py's DependencyScheduler
    independently tracks "mutating_branches" and excludes a second
    same-branch mutator from ever being runnable - a hardcoded mechanism,
    not configurable via EngineeringAdmissionPolicy. So the admission
    policy's own BRANCH_MUTATION_LOCKED check is real defense-in-depth
    (protects against a scheduler bug), not dead code - but it is not
    exercisable via the integrated worker/scheduler path. Proven directly
    against the policy instead, and the scheduler's independent
    unreachability documented by the first half of this test."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[CalyxProgram.__table__, CalyxProgramJob.__table__, CalyxProgramDependency.__table__],
    )
    with Session(engine) as db:
        _start(
            db,
            [
                ProgramJobSpec("one", "role-a", "one", "repo-a", "shared", True),
                ProgramJobSpec("two", "role-b", "two", "repo-a", "shared", True),
            ],
        )
        worker = PersistentProgramWorker(db)
        first = worker.claim(worker_id="w1")
        assert first is not None and first.branch == "shared"

        diagnostic = worker.diagnose()
        assert diagnostic.outcome == "IDLE_NO_CANDIDATE", (
            "the scheduler's own branch-lock excluded the second mutator "
            "before the admission policy ever saw it - not a rejection"
        )

    # The admission-policy check itself, proven directly and in isolation:
    policy = EngineeringAdmissionPolicy()
    locked_candidate = EngineeringWorkIdentity(
        job_id="two", role=AgentRole.BACKEND_ENGINEER, repository="repo-a", branch="shared", mutates_code=True
    )
    already_active = EngineeringWorkIdentity(
        job_id="one",
        role=AgentRole.BACKEND_ENGINEER,
        repository="repo-a",
        branch="shared",
        mutates_code=True,
        status="running",
    )
    decision = policy.evaluate(locked_candidate, [already_active])
    assert decision.admitted is False
    assert decision.code == "BRANCH_MUTATION_LOCKED"


def _jobs_of(db: Session, program_id: str) -> dict[str, CalyxProgramJob]:
    rows = db.scalars(select(CalyxProgramJob).where(CalyxProgramJob.program_id == program_id)).all()
    return {row.job_key: row for row in rows}


def _repair_jobs(db: Session, program_id: str) -> list[CalyxProgramJob]:
    return [
        job
        for key, job in _jobs_of(db, program_id).items()
        if key.startswith("dead-letter-repair:")
    ]


def test_dead_letter_blocks_program_and_writes_exactly_one_repair_job(db: Session) -> None:
    program = _start(
        db,
        [
            ProgramJobSpec("one", "backend_engineer", "one", "repo-a", "branch", True),
            ProgramJobSpec("two", "backend_engineer", "two", "repo-a", "branch", True),
        ],
        dependencies=[("one", "two")],
    )
    worker = PersistentProgramWorker(db)
    claimed = worker.claim(worker_id="w1")
    assert claimed is not None and claimed.job_key == "one"
    claimed.attempt_count = claimed.max_attempts
    claimed.lease_expires_at = utcnow() - timedelta(seconds=1)
    db.commit()

    assert worker.recover_expired_leases() == 1
    db.refresh(program)
    assert program.status == "blocked"
    jobs = _jobs_of(db, program.program_id)
    assert jobs["one"].outcome == "DEAD_LETTER"
    assert jobs["one"].blocker == "PROGRAM_JOB_ATTEMPTS_EXHAUSTED"
    # The dependant is settled rather than left waiting forever.
    assert jobs["two"].status == "blocked"
    assert jobs["two"].blocker == "UPSTREAM_JOB_FAILED"

    repairs = _repair_jobs(db, program.program_id)
    assert len(repairs) == 1
    repair = repairs[0]
    assert repair.job_key == f"dead-letter-repair:{claimed.program_job_id}"
    assert repair.status == "waiting"
    assert repair.outcome is None
    manifest = json.loads(repair.input_json or "{}")
    assert manifest["schema"] == "calyx.program-dead-letter-repair.v1"
    assert manifest["reason"] == "PROGRAM_JOB_ATTEMPTS_EXHAUSTED:one"
    assert manifest["dead_letter_program_job_id"] == claimed.program_job_id
    assert manifest["automatic_retry"] is False

    # Idempotent on re-run: recovery finds nothing new, re-blocking is a no-op,
    # and the blocked program exposes nothing claimable.
    assert worker.recover_expired_leases() == 0
    again = worker.block_program_for_dead_letter(jobs["one"])
    db.commit()
    assert again is not None and again.program_job_id == repair.program_job_id
    assert len(_repair_jobs(db, program.program_id)) == 1
    assert len(_jobs_of(db, program.program_id)) == 3
    assert worker.claim(worker_id="w2") is None


def test_dead_letter_in_cancelled_program_writes_no_repair_job(db: Session) -> None:
    program = _start(db, [ProgramJobSpec("one", "backend_engineer", "one", "repo-a", "branch", True)])
    worker = PersistentProgramWorker(db)
    claimed = worker.claim(worker_id="w1")
    assert claimed is not None
    PersistentProgramRepository(db).cancel(owner="owner", program_id=program.program_id, reason="owner stop")
    claimed.attempt_count = claimed.max_attempts
    claimed.lease_expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert worker.recover_expired_leases() == 1
    db.refresh(program)
    assert program.status == "cancelled"
    assert _repair_jobs(db, program.program_id) == []


def test_failed_attempt_releases_lease_with_backoff_before_retry(db: Session, monkeypatch) -> None:
    import app.calyx_orchestrator.program_worker as program_worker_module

    _start(db, [ProgramJobSpec("one", "backend_engineer", "one", "repo-a", "branch", True)])
    worker = PersistentProgramWorker(db)
    claimed = worker.claim(worker_id="w1")
    assert claimed is not None
    token = claimed.lease_token
    failed_at = utcnow()

    released = worker.release_failed_attempt(
        program_job_id=claimed.program_job_id,
        worker_id="w1",
        lease_token=token,
        error_code="SYNTHETIC_EXECUTOR_FAILURE",
        exception_type="RuntimeError",
        now=failed_at,
    )
    assert released.status == "queued"
    assert released.lease_owner is None
    assert released.lease_token is None
    assert released.lease_expires_at is None
    assert released.attempt_count == 1
    record = json.loads(released.evidence_json or "{}")
    assert record["schema"] == "calyx.program-job-retry-backoff.v1"
    assert record["backoff_seconds"] == 60
    assert record["failures"][0]["error_code"] == "SYNTHETIC_EXECUTOR_FAILURE"

    # The same token cannot release twice.
    with pytest.raises(PermissionError, match="STALE_PROGRAM_JOB_LEASE"):
        worker.release_failed_attempt(
            program_job_id=claimed.program_job_id,
            worker_id="w1",
            lease_token=token,
            error_code="again",
            exception_type="RuntimeError",
        )

    monkeypatch.setattr(program_worker_module, "utcnow", lambda: failed_at + timedelta(seconds=59))
    assert worker.claim(worker_id="w2") is None
    assert worker.diagnose().outcome == "IDLE_NO_CANDIDATE"

    monkeypatch.setattr(program_worker_module, "utcnow", lambda: failed_at + timedelta(seconds=61))
    retried = worker.claim(worker_id="w2")
    assert retried is not None
    assert retried.program_job_id == claimed.program_job_id
    assert retried.attempt_count == 2


def test_failed_attempt_at_ceiling_dead_letters_and_blocks_program(db: Session) -> None:
    program = _start(db, [ProgramJobSpec("one", "backend_engineer", "one", "repo-a", "branch", True)])
    worker = PersistentProgramWorker(db)
    claimed = worker.claim(worker_id="w1")
    assert claimed is not None
    claimed.attempt_count = claimed.max_attempts
    db.commit()
    released = worker.release_failed_attempt(
        program_job_id=claimed.program_job_id,
        worker_id="w1",
        lease_token=claimed.lease_token,
        error_code="SYNTHETIC_EXECUTOR_FAILURE",
        exception_type="RuntimeError",
    )
    assert released.outcome == "DEAD_LETTER"
    assert released.status == "blocked"
    assert released.lease_token is None
    db.refresh(program)
    assert program.status == "blocked"
    assert len(_repair_jobs(db, program.program_id)) == 1
