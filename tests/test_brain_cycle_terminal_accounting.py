"""A settled blocker is not a delivered result or dependency success."""

from dataclasses import replace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.calyx_orchestrator.engineering_core import TerminalOutcome
from app.calyx_orchestrator.executor import ExecutionState, canonical_checksum
from app.calyx_orchestrator.executor_registry import (
    AUTONOMY_PROBE_ROLE,
    AuthoritativeExecutorRegistry,
    AutonomyProbeExecutor,
    RegisteredExecutor,
)
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


@pytest.mark.parametrize("state,outcome", [
    (ExecutionState.BLOCKED, TerminalOutcome.BLOCKED),
    (ExecutionState.TIMED_OUT, TerminalOutcome.BLOCKED),
    (ExecutionState.CANCELLED, TerminalOutcome.CANCELLED),
])
@pytest.mark.parametrize("budget", [1, 3])
def test_non_delivery_is_settled_but_not_counted_as_completed(tmp_path, state, outcome, budget):
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'cycle.db'}")
    Base.metadata.create_all(engine, tables=[
        CalyxProgram.__table__, CalyxProgramJob.__table__, CalyxProgramDependency.__table__,
    ])

    class TerminalFake:
        executor_key = AutonomyProbeExecutor.executor_key

        def execute(self, assignment):
            receipt = AutonomyProbeExecutor().execute(assignment)
            output = {"executed": False, "status": state.value}
            return replace(
                receipt, state=state, outcome=outcome, output=output,
                output_checksum=canonical_checksum(output), blocker_code="FIXTURE_ONLY",
            )

    registry = AuthoritativeExecutorRegistry()
    registry._by_role[AUTONOMY_PROBE_ROLE] = RegisteredExecutor(
        AUTONOMY_PROBE_ROLE, TerminalFake(), True, False,
    )
    try:
        with Session(engine) as db:
            repository = PersistentProgramRepository(db)
            program = repository.create_program(
                owner="fixture-owner", title="Terminal accounting",
                objective="Blockers must not report successful delivery",
                jobs=[
                    ProgramJobSpec(key, AUTONOMY_PROBE_ROLE, key,
                                   "jsp1440/orchid-calyx-backend")
                    for key in ("upstream", "dependent")
                ],
                dependencies=[("upstream", "dependent")],
            )
            repository.start(owner="fixture-owner", program_id=program.program_id)
            result = run_deterministic_program_cycle(
                db, owner="fixture-owner", worker_id="fixture-worker",
                max_jobs=budget, registry=registry,
            )
            assert result.attempted_jobs == 1
            assert len(result.jobs) == 1
            assert result.completed_jobs == 0
            assert result.as_dict()["settled_jobs"] == 1
            assert result.jobs[0].outcome == outcome.value
        with Session(engine) as db:
            rows = {job.job_key: job for job in db.scalars(select(CalyxProgramJob))}
            assert rows["upstream"].outcome == outcome.value
            assert rows["upstream"].lease_token is None
            assert rows["dependent"].status != "completed"
            assert rows["dependent"].attempt_count == 0
    finally:
        engine.dispose()
