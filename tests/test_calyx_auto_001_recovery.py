from __future__ import annotations

from app.calyx_orchestrator.auto_mission_service import AutoMissionCoordinator
from app.calyx_orchestrator.executor_registry import AUTONOMY_PROBE_ROLE
from app.calyx_orchestrator.program_models import CalyxProgramJob
from app.calyx_orchestrator.program_repository import ProgramJobSpec
from tests.test_calyx_auto_001 import (
    FeedbackExecutor,
    Registry,
    db,
    program,
    spec,
)


class MissingFileExecutor:
    executor_key = "missing-file-executor-v1"

    def __init__(self) -> None:
        self.calls = 0
        self.rollback_calls = 0

    def execute(self, assignment):
        del assignment
        self.calls += 1
        raise FileNotFoundError("fixture missing validation input")

    def rollback(self, assignment_id):
        del assignment_id
        self.rollback_calls += 1
        return True


def unsupported_spec(key: str, priority: int) -> ProgramJobSpec:
    return ProgramJobSpec(
        key,
        "unsupported-role",
        key,
        "jsp1440/orchid-calyx-backend",
        None,
        False,
        {"priority": priority},
    )


def test_governance_holds_do_not_consume_capacity_before_automatic_claim():
    with db() as session:
        item = program(
            session,
            [
                spec("held-a", 1, "merge"),
                spec("held-b", 2, "merge"),
                spec("automatic", 3),
            ],
        )
        executor = FeedbackExecutor()
        result = AutoMissionCoordinator(
            session,
            registry=Registry(executor),
        ).run_cycle(owner="owner", worker_id="w", max_jobs=5)

        assert result.stop_reason == "governance_boundary"
        assert result.attempted_jobs == 1
        assert result.completed_jobs == 1
        assert result.governance_holds == 2
        assert [call.job_key for call in executor.calls] == ["automatic"]

        jobs = (
            session.query(CalyxProgramJob)
            .filter(CalyxProgramJob.program_id == item.program_id)
            .all()
        )
        by_key = {job.job_key: job for job in jobs}
        assert by_key["automatic"].status == "completed"
        for key in ("held-a", "held-b"):
            assert by_key[key].status == "queued"
            assert by_key[key].attempt_count == 0
            assert by_key[key].lease_token is None


def test_unsupported_roles_do_not_starve_later_automatic_work():
    with db() as session:
        program(
            session,
            [
                unsupported_spec("unsupported-a", 1),
                unsupported_spec("unsupported-b", 2),
                spec("automatic", 3),
            ],
        )
        executor = FeedbackExecutor()
        result = AutoMissionCoordinator(
            session,
            registry=Registry(executor),
        ).run_cycle(owner="owner", worker_id="w", max_jobs=5)

        assert result.stop_reason == "governance_boundary"
        assert result.attempted_jobs == 1
        assert result.completed_jobs == 1
        assert result.governance_holds == 2
        assert [call.job_key for call in executor.calls] == ["automatic"]


def test_held_upstream_still_blocks_automatic_dependent():
    with db() as session:
        program(
            session,
            [spec("held-parent", 1, "merge"), spec("automatic-child", 2)],
            [("held-parent", "automatic-child")],
        )
        executor = FeedbackExecutor()
        result = AutoMissionCoordinator(
            session,
            registry=Registry(executor),
        ).run_cycle(owner="owner", worker_id="w", max_jobs=5)

        assert result.stop_reason == "governance_boundary"
        assert result.attempted_jobs == 0
        assert result.governance_holds == 1
        assert executor.calls == []


def test_filesystem_executor_failure_is_contained_and_lease_is_released():
    with db() as session:
        item = program(session, [spec("missing-file")])
        executor = MissingFileExecutor()
        result = AutoMissionCoordinator(
            session,
            registry=Registry(executor, workspace_mutation=True),
        ).run_cycle(owner="owner", worker_id="w", max_jobs=1)

        assert result.stop_reason == "error"
        assert result.attempted_jobs == 1
        assert result.completed_jobs == 0
        assert result.error is not None
        assert result.error["exception_type"] == "FileNotFoundError"
        assert result.error["lease_released"] is True
        assert result.error["retry_scheduled"] is True
        assert executor.calls == 1
        assert executor.rollback_calls == 1

        job = (
            session.query(CalyxProgramJob)
            .filter_by(program_id=item.program_id)
            .one()
        )
        assert job.role_key == AUTONOMY_PROBE_ROLE
        assert job.status == "queued"
        assert job.outcome is None
        assert job.attempt_count == 1
        assert job.lease_owner is None
        assert job.lease_token is None
        assert job.lease_expires_at is None
        assert job.blocker == "EXECUTOR_EXCEPTION:FileNotFoundError"
