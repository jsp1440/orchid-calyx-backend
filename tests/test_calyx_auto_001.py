from __future__ import annotations

from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.auto_mission import GovernanceAwarePrioritySelector
from app.calyx_orchestrator.auto_mission_models import (
    CalyxBrainCompletionWriteback,
    CalyxProgramValidationEvent,
)
from app.calyx_orchestrator.auto_mission_service import (
    AutoMissionCoordinator,
    GovernedAutoMissionWorker,
)
from app.calyx_orchestrator.engineering_core import TerminalOutcome
from app.calyx_orchestrator.executor import (
    ExecutionReceipt,
    ExecutionState,
    canonical_checksum,
)
from app.calyx_orchestrator.executor_registry import (
    AUTONOMY_PROBE_ROLE,
    RegisteredExecutor,
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
from app.database import Base


class FeedbackExecutor:
    executor_key = "feedback-executor-v1"

    def __init__(self):
        self.calls = []

    def execute(self, assignment):
        self.calls.append(assignment)
        feedback = assignment.inputs.get("validator_feedback")
        if assignment.job_key == "first" and feedback is None:
            output = {
                "status": "delivered",
                "validation_errors": ["add exact provenance"],
            }
        else:
            output = {"status": "delivered", "accepted": True}
        receipt = ExecutionReceipt(
            assignment_id=assignment.assignment_id,
            program_id=assignment.program_id,
            job_key=assignment.job_key,
            executor_key=self.executor_key,
            state=ExecutionState.DELIVERED,
            outcome=TerminalOutcome.DELIVERED,
            input_checksum=assignment.verified_input_checksum(),
            output_checksum=canonical_checksum(output),
            output=output,
            evidence_uris=assignment.evidence_uris,
        )
        receipt.verify()
        return receipt


class FinalizeOnceExecutor(FeedbackExecutor):
    executor_key = "finalize-once-executor-v1"

    def __init__(self):
        super().__init__()
        self.finalize_calls = 0
        self.rollback_calls = 0

    def finalize(self, assignment_id):
        del assignment_id
        self.finalize_calls += 1
        if self.finalize_calls == 1:
            raise OSError("fixture finalize cleanup unavailable")

    def rollback(self, assignment_id):
        del assignment_id
        self.rollback_calls += 1
        return True


class Registry:
    def __init__(self, executor, *, workspace_mutation=False):
        self.executor = executor
        self.workspace_mutation = workspace_mutation
        self.eligible_role_keys = frozenset({AUTONOMY_PROBE_ROLE})

    def require_authoritative(self, role_key):
        assert role_key == AUTONOMY_PROBE_ROLE
        return RegisteredExecutor(
            role_key,
            self.executor,
            True,
            False,
            self.workspace_mutation,
        )


def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CalyxProgram.__table__,
            CalyxProgramJob.__table__,
            CalyxProgramDependency.__table__,
            CalyxProgramValidationEvent.__table__,
            CalyxBrainCompletionWriteback.__table__,
        ],
    )
    return Session(engine)


def program(session, specs, dependencies=(), *, max_active_jobs=6):
    repo = PersistentProgramRepository(session)
    item = repo.create_program(
        owner="owner",
        title="auto",
        objective="test",
        jobs=specs,
        dependencies=dependencies,
        max_active_jobs=max_active_jobs,
    )
    repo.start(owner="owner", program_id=item.program_id)
    return item


def spec(key, priority=100, action=None):
    inputs = {"priority": priority}
    if action:
        inputs["action"] = action
    return ProgramJobSpec(
        key,
        AUTONOMY_PROBE_ROLE,
        key,
        "jsp1440/orchid-calyx-backend",
        None,
        False,
        inputs,
    )


def test_validator_feedback_brain_writeback_and_auto_continuation():
    with db() as session:
        item = program(
            session,
            [spec("first", 10), spec("second", 20)],
            [("first", "second")],
        )
        executor = FeedbackExecutor()
        result = AutoMissionCoordinator(
            session,
            registry=Registry(executor),
        ).run_cycle(owner="owner", worker_id="w", max_jobs=5)
        assert result.stop_reason == "idle"
        assert result.attempted_jobs == 3
        assert result.completed_jobs == 2
        assert result.validator_retries == 1
        assert [row.job_key for row in result.jobs] == ["first", "first", "second"]
        assert executor.calls[1].inputs["validator_feedback"]["feedback"] == [
            "add exact provenance"
        ]
        rows = session.query(CalyxProgramValidationEvent).all()
        assert len(rows) == 3
        assert [row.disposition for row in rows].count("retry") == 1
        writebacks = session.query(CalyxBrainCompletionWriteback).all()
        assert len(writebacks) == 2
        jobs = (
            session.query(CalyxProgramJob)
            .filter(CalyxProgramJob.program_id == item.program_id)
            .all()
        )
        by_key = {job.job_key: job for job in jobs}
        assert by_key["first"].attempt_count == 2
        assert by_key["second"].attempt_count == 1
        assert all(job.status == "completed" for job in jobs)
        session.refresh(item)
        assert item.status == "completed"
        assert result.jobs[1].continuation_released == (
            by_key["second"].program_job_id,
        )


def test_governance_owner_only_action_is_held_without_consuming_mission():
    with db() as session:
        item = program(session, [spec("merge-me", 0, "merge")])
        executor = FeedbackExecutor()
        result = AutoMissionCoordinator(
            session,
            registry=Registry(executor),
        ).run_cycle(owner="owner", worker_id="w")
        assert result.stop_reason == "governance_boundary"
        assert result.governance_holds == 1
        assert result.attempted_jobs == 0
        assert executor.calls == []
        job = (
            session.query(CalyxProgramJob)
            .filter_by(program_id=item.program_id)
            .one()
        )
        assert job.status == "queued"
        assert job.outcome is None
        assert job.lease_owner is None
        assert job.lease_token is None
        assert job.attempt_count == 0
        assert session.query(CalyxBrainCompletionWriteback).count() == 0


def test_priority_selector_runs_lower_numeric_priority_first():
    with db() as session:
        program(session, [spec("later", 50), spec("urgent", 5)])
        executor = FeedbackExecutor()
        result = AutoMissionCoordinator(
            session,
            registry=Registry(executor),
        ).run_cycle(owner="owner", worker_id="w", max_jobs=1)
        assert result.jobs[0].job_key == "urgent"


def test_active_job_limit_prevents_second_claim():
    with db() as session:
        program(
            session,
            [spec("one", 1), spec("two", 2)],
            max_active_jobs=1,
        )
        worker = GovernedAutoMissionWorker(
            session,
            GovernanceAwarePrioritySelector(),
        )
        first = worker.claim(
            worker_id="one",
            owner="owner",
            roles=frozenset({AUTONOMY_PROBE_ROLE}),
            lease_seconds=60,
        )
        assert first is not None
        second = worker.claim(
            worker_id="two",
            owner="owner",
            roles=frozenset({AUTONOMY_PROBE_ROLE}),
            lease_seconds=60,
        )
        assert second is None


def test_expired_lease_is_reclaimed_with_new_token_and_attempt():
    with db() as session:
        program(session, [spec("lease")])
        worker = GovernedAutoMissionWorker(
            session,
            GovernanceAwarePrioritySelector(),
        )
        first = worker.claim(
            worker_id="one",
            owner="owner",
            roles=frozenset({AUTONOMY_PROBE_ROLE}),
            lease_seconds=60,
        )
        assert first is not None and first.lease_token
        old_token = first.lease_token
        first.lease_expires_at = utcnow() - timedelta(seconds=1)
        session.commit()
        second = worker.claim(
            worker_id="two",
            owner="owner",
            roles=frozenset({AUTONOMY_PROBE_ROLE}),
            lease_seconds=60,
        )
        assert second is not None
        assert second.program_job_id == first.program_job_id
        assert second.lease_token != old_token
        assert second.lease_owner == "two"
        assert second.attempt_count == 2


def test_post_commit_finalize_failure_never_rolls_back_accepted_workspace():
    with db() as session:
        item = program(session, [spec("workspace")])
        executor = FinalizeOnceExecutor()
        coordinator = AutoMissionCoordinator(
            session,
            registry=Registry(executor, workspace_mutation=True),
        )

        first = coordinator.run_cycle(owner="owner", worker_id="w")
        assert first.stop_reason == "finalization_pending"
        assert first.completed_jobs == 1
        assert first.error is not None
        assert first.error["code"] == "WORKSPACE_FINALIZE_PENDING"
        assert executor.rollback_calls == 0
        assert executor.finalize_calls == 1
        assert len(executor.calls) == 1

        job = (
            session.query(CalyxProgramJob)
            .filter_by(program_id=item.program_id)
            .one()
        )
        assert job.status == "completed"
        assert job.outcome == TerminalOutcome.DELIVERED.value
        assert session.query(CalyxBrainCompletionWriteback).count() == 1

        second = coordinator.run_cycle(owner="owner", worker_id="w")
        assert second.stop_reason == "idle"
        assert second.attempted_jobs == 0
        assert executor.finalize_calls == 2
        assert executor.rollback_calls == 0
        assert len(executor.calls) == 1
        assert session.query(CalyxBrainCompletionWriteback).count() == 1


def test_timeout_cannot_exceed_lease():
    with db() as session:
        program(session, [spec("lease")])
        coordinator = AutoMissionCoordinator(
            session,
            registry=Registry(FeedbackExecutor()),
        )
        try:
            coordinator.run_cycle(
                owner="owner",
                worker_id="w",
                lease_seconds=60,
                timeout_seconds=61,
            )
        except ValueError as exc:
            assert str(exc) == "AUTONOMY_TIMEOUT_EXCEEDS_LEASE"
        else:
            raise AssertionError("timeout/lease guard did not fail closed")
