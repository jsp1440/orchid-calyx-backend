from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.auto_mission_models import (
    CalyxBrainCompletionWriteback,
    CalyxProgramValidationEvent,
)
from app.calyx_orchestrator.auto_mission_service import AutoMissionCoordinator
from app.calyx_orchestrator.executor_registry import AUTONOMY_PROBE_ROLE
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


def _program(session: Session, *, role_key: str) -> CalyxProgram:
    repo = PersistentProgramRepository(session)
    program = repo.create_program(
        owner="owner",
        title="orchestrator readiness",
        objective="prove blocked or invalid runnable work remains visible",
        jobs=[
            ProgramJobSpec(
                "fixture",
                role_key,
                "orchestrator readiness fixture",
                "jsp1440/orchid-calyx-backend",
                None,
                False,
                {"priority": 1},
            )
        ],
    )
    repo.start(owner="owner", program_id=program.program_id)
    return program


def test_runnable_unsupported_role_is_reported_as_hold_not_idle():
    with _db() as session:
        program = _program(session, role_key="future_unregistered_executor_role")

        result = AutoMissionCoordinator(session).run_cycle(
            owner="owner",
            worker_id="worker",
        )

        assert result.stop_reason == "governance_boundary"
        assert result.governance_holds == 1
        assert result.attempted_jobs == 0
        assert result.completed_jobs == 0

        job = (
            session.query(CalyxProgramJob)
            .filter(CalyxProgramJob.program_id == program.program_id)
            .one()
        )
        assert job.status == "queued"
        assert job.outcome is None
        assert job.attempt_count == 0
        assert job.lease_owner is None
        assert job.lease_token is None
        assert session.query(CalyxBrainCompletionWriteback).count() == 0


def test_invalid_persisted_schedule_is_reported_not_misclassified_as_idle():
    with _db() as session:
        program = _program(session, role_key=AUTONOMY_PROBE_ROLE)
        job = (
            session.query(CalyxProgramJob)
            .filter(CalyxProgramJob.program_id == program.program_id)
            .one()
        )
        job.status = "corrupt-scheduler-state"
        session.commit()

        result = AutoMissionCoordinator(session).run_cycle(
            owner="owner",
            worker_id="worker",
        )

        assert result.stop_reason == "scheduler_invalid"
        assert result.attempted_jobs == 0
        assert result.completed_jobs == 0
        assert result.governance_holds == 0
        assert result.error is not None
        assert result.error["code"] == (
            "UNSUPPORTED_PERSISTED_JOB_STATUS:corrupt-scheduler-state"
        )
        session.refresh(job)
        assert job.status == "corrupt-scheduler-state"
        assert job.outcome is None
        assert job.attempt_count == 0
        assert job.lease_owner is None
        assert job.lease_token is None
        assert session.query(CalyxBrainCompletionWriteback).count() == 0
