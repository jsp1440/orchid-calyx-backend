from __future__ import annotations

from dataclasses import replace

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.auto_mission_models import (
    CalyxBrainCompletionWriteback,
    CalyxProgramValidationEvent,
)
from app.calyx_orchestrator.auto_mission_service import AutoMissionCoordinator
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


class MisboundReceiptExecutor:
    executor_key = "misbound-receipt-executor-v1"

    def __init__(self, mutation: str):
        self.mutation = mutation

    def execute(self, assignment):
        output = {
            "status": "delivered",
            "validation_errors": ["this must never reach the validator"],
        }
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
        if self.mutation == "assignment_id":
            return replace(receipt, assignment_id="wrong-assignment")
        if self.mutation == "program_id":
            return replace(receipt, program_id="wrong-program")
        if self.mutation == "job_key":
            return replace(receipt, job_key="wrong-job")
        if self.mutation == "executor_key":
            return replace(receipt, executor_key="wrong-executor")
        if self.mutation == "input_checksum":
            return replace(receipt, input_checksum="0" * 64)
        raise AssertionError(f"unsupported mutation fixture: {self.mutation}")


class Registry:
    def __init__(self, executor):
        self.executor = executor
        self.eligible_role_keys = frozenset({AUTONOMY_PROBE_ROLE})

    def require_authoritative(self, role_key):
        assert role_key == AUTONOMY_PROBE_ROLE
        return RegisteredExecutor(
            role_key,
            self.executor,
            True,
            False,
            False,
        )


def _db() -> Session:
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


def _program(session: Session) -> CalyxProgram:
    repository = PersistentProgramRepository(session)
    item = repository.create_program(
        owner="owner",
        title="receipt binding",
        objective="reject a self-consistent receipt that is not bound to the dispatched assignment",
        jobs=[
            ProgramJobSpec(
                "binding",
                AUTONOMY_PROBE_ROLE,
                "receipt binding fixture",
                "jsp1440/orchid-calyx-backend",
                None,
                False,
                {"priority": 1},
            )
        ],
    )
    repository.start(owner="owner", program_id=item.program_id)
    return item


def _assert_rejected_without_validator_side_effects(mutation: str, expected_code: str) -> None:
    with _db() as session:
        item = _program(session)
        result = AutoMissionCoordinator(
            session,
            registry=Registry(MisboundReceiptExecutor(mutation)),
        ).run_cycle(
            owner="owner",
            worker_id="worker",
            lease_seconds=60,
            timeout_seconds=60,
        )

        assert result.stop_reason == "error"
        assert result.attempted_jobs == 1
        assert result.completed_jobs == 0
        assert result.validator_retries == 0
        assert result.error is not None
        assert result.error["code"] == expected_code

        assert session.query(CalyxProgramValidationEvent).count() == 0
        assert session.query(CalyxBrainCompletionWriteback).count() == 0

        job = (
            session.query(CalyxProgramJob)
            .filter(CalyxProgramJob.program_id == item.program_id)
            .one()
        )
        # Receipt-integrity failures are executor failures, so the durable lease is
        # released immediately instead of leaving the worker stuck until expiry.
        assert job.status == "queued"
        assert job.outcome is None
        assert job.attempt_count == 1
        assert job.lease_owner is None
        assert job.lease_token is None
        assert job.lease_expires_at is None
        assert job.blocker == "EXECUTOR_EXCEPTION:ValueError"


def test_wrong_assignment_id_is_rejected_before_validator_state_mutation():
    _assert_rejected_without_validator_side_effects(
        "assignment_id",
        "RECEIPT_IDENTITY_MISMATCH",
    )


def test_wrong_program_id_is_rejected_before_validator_state_mutation():
    _assert_rejected_without_validator_side_effects(
        "program_id",
        "RECEIPT_IDENTITY_MISMATCH",
    )


def test_wrong_job_key_is_rejected_before_validator_state_mutation():
    _assert_rejected_without_validator_side_effects(
        "job_key",
        "RECEIPT_IDENTITY_MISMATCH",
    )


def test_wrong_executor_identity_is_rejected_before_validator_state_mutation():
    _assert_rejected_without_validator_side_effects(
        "executor_key",
        "RECEIPT_EXECUTOR_IDENTITY_MISMATCH",
    )


def test_wrong_input_checksum_is_rejected_before_validator_state_mutation():
    _assert_rejected_without_validator_side_effects(
        "input_checksum",
        "RECEIPT_INPUT_CHECKSUM_MISMATCH",
    )
