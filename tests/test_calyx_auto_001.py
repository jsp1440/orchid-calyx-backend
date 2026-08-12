from __future__ import annotations

from datetime import timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.auto_mission import GovernanceAwarePrioritySelector
from app.calyx_orchestrator.auto_mission_models import CalyxBrainCompletionWriteback, CalyxProgramValidationEvent
from app.calyx_orchestrator.auto_mission_service import AutoMissionCoordinator, GovernedAutoMissionWorker
from app.calyx_orchestrator.executor import ExecutionReceipt, ExecutionState, canonical_checksum
from app.calyx_orchestrator.executor_registry import AUTONOMY_PROBE_ROLE, RegisteredExecutor
from app.calyx_orchestrator.engineering_core import TerminalOutcome
from app.calyx_orchestrator.models import utcnow
from app.calyx_orchestrator.program_models import CalyxProgram, CalyxProgramDependency, CalyxProgramJob
from app.calyx_orchestrator.program_repository import PersistentProgramRepository, ProgramJobSpec
from app.database import Base


class FeedbackExecutor:
    executor_key = "feedback-executor-v1"

    def __init__(self):
        self.calls = []

    def execute(self, assignment):
        self.calls.append(assignment)
        feedback = assignment.inputs.get("validator_feedback")
        if assignment.job_key == "first" and feedback is None:
            output = {"status": "delivered", "validation_errors": ["add exact provenance"]}
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


class Registry:
    def __init__(self, executor):
        self.executor = executor
        self.eligible_role_keys = frozenset({AUTONOMY_PROBE_ROLE})

    def require_authoritative(self, role_key):
        assert role_key == AUTONOMY_PROBE_ROLE
        return RegisteredExecutor(role_key, self.executor, True, False)


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


def program(session, specs, dependencies=()):
    repo = PersistentProgramRepository(session)
    item = repo.create_program(
        owner="owner",
        title="auto",
        objective="test",
        jobs=specs,
        dependencies=dependencies,
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
        item = program(session, [spec("first", 10), spec("second", 20)], [("first", "second")])
        executor = FeedbackExecutor()
        result = AutoMissionCoordinator(session, registry=Registry(executor)).run_cycle(
            owner="owner", worker_id="w", max_jobs=5
        )
        assert result.stop_reason == "idle"
        assert result.attempted_jobs == 3
        assert result.completed_jobs == 2
        assert result.validator_retries == 1
        assert [row.job_key for row in result.jobs] == ["first", "first", "second"]
        assert executor.calls[1].inputs["validator_feedback"]["feedback"] == ["add exact provenance"]
        rows = session.query(CalyxProgramValidationEvent).all()
        assert len(rows) == 3
        assert [row.disposition for row in rows].count("retry") == 1
        writebacks = session.query(CalyxBrainCompletionWriteback).all()
        assert len(writebacks) == 2
        jobs = session.query(CalyxProgramJob).filter(CalyxProgramJob.program_id == item.program_id).all()
        by_key = {job.job_key: job for job in jobs}
        assert by_key["first"].attempt_count == 2
        assert by_key["second"].attempt_count == 1
        assert all(job.status == "completed" for job in jobs)
        session.refresh(item)
        assert item.status == "completed"
        assert result.jobs[1].continuation_released == (by_key["second"].program_job_id,)


def test_governance_owner_only_action_is_held_before_executor_claim():
    with db() as session:
        item = program(session, [spec("merge-me", 0, "merge")])
        executor = FeedbackExecutor()
        result = AutoMissionCoordinator(session, registry=Registry(executor)).run_cycle(
            owner="owner", worker_id="w"
        )
        assert result.governance_holds == 1
        assert result.attempted_jobs == 0
        assert executor.calls == []
        job = session.query(CalyxProgramJob).filter_by(program_id=item.program_id).one()
        assert job.outcome == "BLOCKED"
        assert job.blocker == "OWNER_ONLY_ACTION:merge"
        assert "Owner approval" in job.human_action
        assert session.query(CalyxBrainCompletionWriteback).count() == 0


def test_priority_selector_runs_lower_numeric_priority_first():
    with db() as session:
        program(session, [spec("later", 50), spec("urgent", 5)])
        executor = FeedbackExecutor()
        result = AutoMissionCoordinator(session, registry=Registry(executor)).run_cycle(
            owner="owner", worker_id="w", max_jobs=1
        )
        assert result.jobs[0].job_key == "urgent"


def test_expired_lease_is_reclaimed_with_new_token_and_attempt():
    with db() as session:
        program(session, [spec("lease")])
        worker = GovernedAutoMissionWorker(session, GovernanceAwarePrioritySelector())
        first = worker.claim(
            worker_id="one", owner="owner", roles=frozenset({AUTONOMY_PROBE_ROLE}), lease_seconds=60
        )
        assert first is not None and first.lease_token
        old_token = first.lease_token
        first.lease_expires_at = utcnow() - timedelta(seconds=1)
        session.commit()
        second = worker.claim(
            worker_id="two", owner="owner", roles=frozenset({AUTONOMY_PROBE_ROLE}), lease_seconds=60
        )
        assert second is not None
        assert second.program_job_id == first.program_job_id
        assert second.lease_token != old_token
        assert second.lease_owner == "two"
        assert second.attempt_count == 2


def test_timeout_cannot_exceed_lease():
    with db() as session:
        program(session, [spec("lease")])
        coordinator = AutoMissionCoordinator(session, registry=Registry(FeedbackExecutor()))
        try:
            coordinator.run_cycle(owner="owner", worker_id="w", lease_seconds=60, timeout_seconds=61)
        except ValueError as exc:
            assert str(exc) == "AUTONOMY_TIMEOUT_EXCEEDS_LEASE"
        else:
            raise AssertionError("timeout/lease guard did not fail closed")
