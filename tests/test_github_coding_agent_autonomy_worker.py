from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.calyx_orchestrator.github_agent_autonomy_policy import (
    GitHubCodingAgentAutonomyPolicy,
)
from app.calyx_orchestrator.github_agent_ci_policy import RequiredCiCheckPolicy
from app.calyx_orchestrator.github_agent_dispatch_cycle import GitHubCodingRuntimePolicy
from app.calyx_orchestrator.github_agent_dispatch_store import (
    GitHubAgentDispatchRecordRow,
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
from runtime import github_coding_agent_autonomy_worker as worker

REPOSITORY = "jsp1440/orchid-calyx-backend"
OWNER = "jsp1440"


class _NeverCalledTransport:
    def request(self, method, path, *, json_body=None, params=None):  # pragma: no cover
        raise AssertionError(
            "no GitHub call may happen: an unauthorized worker cycle, or a "
            "cycle with no existing dispatch record, must never reach the transport"
        )


def _session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CalyxProgram.__table__,
            CalyxProgramJob.__table__,
            CalyxProgramDependency.__table__,
            GitHubAgentDispatchRecordRow.__table__,
        ],
    )
    return sessionmaker(bind=engine)


def _enqueue_mission(SessionLocal) -> None:
    with SessionLocal() as db:
        repo = PersistentProgramRepository(db)
        program = repo.create_program(
            owner=OWNER,
            title="Autonomy worker mission",
            objective="Prove the automatic caller reaches the real dispatch cycle",
            jobs=[
                ProgramJobSpec(
                    job_key="autonomy-worker-mission-001",
                    role_key="github_coding_agent",
                    title="Autonomy worker mission",
                    repository=REPOSITORY,
                    branch="agent/autonomy-worker-mission-001",
                    mutating=True,
                    inputs={"budget_class": "TINY", "mission_id": "autonomy-worker-mission-001"},
                )
            ],
            dependencies=[],
        )
        repo.start(owner=OWNER, program_id=program.program_id)
        db.commit()


def _runtime_policy() -> GitHubCodingRuntimePolicy:
    return GitHubCodingRuntimePolicy(
        enabled=True,
        owner_allowlist=frozenset({OWNER}),
        repository_allowlist=frozenset({REPOSITORY}),
    )


def _required_checks() -> RequiredCiCheckPolicy:
    return RequiredCiCheckPolicy(required_checks=frozenset({"validate"}))


def test_disabled_policy_never_touches_the_database_or_transport(monkeypatch) -> None:
    def forbidden_session_local():  # pragma: no cover
        raise AssertionError("a disabled/unauthorized cycle must never open a database session")

    monkeypatch.setattr(worker, "get_session_local", forbidden_session_local)

    result = worker.run_once(
        transport=_NeverCalledTransport(),
        runtime_policy=_runtime_policy(),
        required_checks=_required_checks(),
        policy=GitHubCodingAgentAutonomyPolicy(),  # enabled=False by default
    )

    assert result["executed"] is False
    assert result["reason"] == "disabled_or_owner_not_configured"


def test_authorized_cycle_with_no_queued_mission_reaches_idle_without_any_github_call(monkeypatch) -> None:
    SessionLocal = _session_factory()
    monkeypatch.setattr(worker, "get_session_local", lambda: SessionLocal)

    result = worker.run_once(
        transport=_NeverCalledTransport(),
        runtime_policy=_runtime_policy(),
        required_checks=_required_checks(),
        policy=GitHubCodingAgentAutonomyPolicy(enabled=True, owner=OWNER),
    )

    assert result["executed"] is True
    assert result["cycle"]["state"] == "idle_no_candidate"


def test_authorized_cycle_reaches_preflight_ready_for_a_real_queued_mission_without_any_github_call(
    monkeypatch,
) -> None:
    SessionLocal = _session_factory()
    monkeypatch.setattr(worker, "get_session_local", lambda: SessionLocal)
    _enqueue_mission(SessionLocal)

    result = worker.run_once(
        transport=_NeverCalledTransport(),
        runtime_policy=_runtime_policy(),
        required_checks=_required_checks(),
        policy=GitHubCodingAgentAutonomyPolicy(enabled=True, owner=OWNER),
    )

    assert result["executed"] is True
    assert result["cycle"]["state"] == "preflight_ready"
    assert result["cycle"]["repository"] == REPOSITORY
    assert result["cycle"]["side_effects"] == ()


def test_run_forever_refuses_to_start_when_not_authorized() -> None:
    with pytest.raises(PermissionError, match="GITHUB_CODING_AGENT_AUTONOMY_NOT_AUTHORIZED"):
        worker.run_forever(
            transport=_NeverCalledTransport(),
            runtime_policy=_runtime_policy(),
            required_checks=_required_checks(),
            policy=GitHubCodingAgentAutonomyPolicy(),
        )


def test_run_forever_loops_sleeps_and_reports_each_cycle(monkeypatch) -> None:
    SessionLocal = _session_factory()
    monkeypatch.setattr(worker, "get_session_local", lambda: SessionLocal)

    sleeps: list[float] = []
    cycles: list[dict] = []

    def stop_after_two(seconds: float) -> None:
        sleeps.append(seconds)
        if len(sleeps) >= 2:
            raise StopIteration

    with pytest.raises(StopIteration):
        worker.run_forever(
            transport=_NeverCalledTransport(),
            runtime_policy=_runtime_policy(),
            required_checks=_required_checks(),
            policy=GitHubCodingAgentAutonomyPolicy(enabled=True, owner=OWNER, poll_seconds=90),
            sleeper=stop_after_two,
            on_cycle=cycles.append,
        )

    assert sleeps == [90, 90]
    assert len(cycles) == 2
    assert all(cycle["executed"] is True for cycle in cycles)
