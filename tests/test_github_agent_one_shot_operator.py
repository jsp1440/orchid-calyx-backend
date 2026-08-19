from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator import github_agent_one_shot_operator as one_shot
from app.calyx_orchestrator.github_agent_ci_policy import RequiredCiCheckPolicy
from app.calyx_orchestrator.github_agent_dispatch_cycle import EXECUTE_CONFIRMATION
from app.calyx_orchestrator.github_agent_dispatch_store import (
    GitHubAgentDispatchRecordRow,
)
from app.calyx_orchestrator.github_agent_observation_gateway import COPILOT_BOT_LOGIN
from app.calyx_orchestrator.github_agent_one_shot_operator import (
    OneShotExecutionError,
    OneShotExecutionRequest,
    execute_one_shot_mission,
)
from app.calyx_orchestrator.github_coding_executor import BudgetClass
from app.calyx_orchestrator.github_proposal_mutation_adapter import (
    GitHubTransportResponse,
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

REPOSITORY = "jsp1440/Orchid-Continuum-Brain"
OWNER = "jsp1440"


@pytest.fixture()
def db() -> Session:
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
    with Session(engine) as session:
        yield session


@dataclass
class FakeTransport:
    responses: list[GitHubTransportResponse]

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, path: str, *, json_body=None, params=None):
        del json_body, params
        self.calls.append((method, path))
        return self.responses.pop(0)


class _NeverCalledTransport:
    def request(self, method, path, *, json_body=None, params=None):  # pragma: no cover
        raise AssertionError("a failed-closed check must never reach the transport")


def _enqueue_mission(db: Session, *, job_key: str = "one-shot-mission-001") -> str:
    repo = PersistentProgramRepository(db)
    program = repo.create_program(
        owner=OWNER,
        title="One-shot live experiment",
        objective="Prove the one-shot operator surface end to end",
        jobs=[
            ProgramJobSpec(
                job_key=job_key,
                role_key="github_coding_agent",
                title="One-shot mission",
                repository=REPOSITORY,
                branch=f"agent/{job_key}",
                mutating=True,
                inputs={"budget_class": "TINY", "mission_id": job_key},
            )
        ],
        dependencies=[],
    )
    repo.start(owner=OWNER, program_id=program.program_id)
    db.commit()
    job = db.query(CalyxProgramJob).filter(CalyxProgramJob.job_key == job_key).one()
    return job.program_job_id


def _request(*, program_job_id: str, confirmation: str = EXECUTE_CONFIRMATION, **overrides) -> OneShotExecutionRequest:
    values = {
        "owner": OWNER,
        "repository": REPOSITORY,
        "expected_program_job_id": program_job_id,
        "budget_class": BudgetClass.TINY,
        "required_checks": RequiredCiCheckPolicy(required_checks=frozenset({"validate"})),
        "confirmation": confirmation,
    }
    values.update(overrides)
    return OneShotExecutionRequest(**values)


def test_blank_owner_fails_closed_before_any_query(db: Session) -> None:
    with pytest.raises(OneShotExecutionError, match="ONE_SHOT_OWNER_REQUIRED"):
        execute_one_shot_mission(
            db=db,
            transport=_NeverCalledTransport(),
            request=_request(program_job_id="whatever", owner=""),
        )


def test_blank_repository_fails_closed(db: Session) -> None:
    with pytest.raises(OneShotExecutionError, match="ONE_SHOT_REPOSITORY_REQUIRED"):
        execute_one_shot_mission(
            db=db,
            transport=_NeverCalledTransport(),
            request=_request(program_job_id="whatever", repository=""),
        )


def test_blank_expected_program_job_id_fails_closed(db: Session) -> None:
    with pytest.raises(OneShotExecutionError, match="ONE_SHOT_EXPECTED_PROGRAM_JOB_ID_REQUIRED"):
        execute_one_shot_mission(
            db=db,
            transport=_NeverCalledTransport(),
            request=_request(program_job_id=""),
        )


def test_wrong_confirmation_string_fails_closed(db: Session) -> None:
    with pytest.raises(OneShotExecutionError, match="ONE_SHOT_CONFIRMATION_MISMATCH"):
        execute_one_shot_mission(
            db=db,
            transport=_NeverCalledTransport(),
            request=_request(program_job_id="whatever", confirmation="not-the-real-string"),
        )


def test_no_queued_mission_fails_closed(db: Session) -> None:
    with pytest.raises(OneShotExecutionError, match="ONE_SHOT_EXPECTED_EXACTLY_ONE_CANDIDATE:0"):
        execute_one_shot_mission(
            db=db,
            transport=_NeverCalledTransport(),
            request=_request(program_job_id="nonexistent-job"),
        )


def test_more_than_one_queued_mission_fails_closed_rather_than_guess(db: Session) -> None:
    _enqueue_mission(db, job_key="one-shot-mission-a")
    second_id = _enqueue_mission(db, job_key="one-shot-mission-b")

    with pytest.raises(OneShotExecutionError, match="ONE_SHOT_EXPECTED_EXACTLY_ONE_CANDIDATE:2"):
        execute_one_shot_mission(
            db=db,
            transport=_NeverCalledTransport(),
            request=_request(program_job_id=second_id),
        )


def test_unexpected_candidate_identity_fails_closed(db: Session) -> None:
    _enqueue_mission(db, job_key="one-shot-mission-real")

    with pytest.raises(OneShotExecutionError, match="ONE_SHOT_UNEXPECTED_CANDIDATE"):
        execute_one_shot_mission(
            db=db,
            transport=_NeverCalledTransport(),
            request=_request(program_job_id="a-different-job-id-the-owner-did-not-authorize"),
        )


def test_happy_path_executes_exactly_the_authorized_mission(db: Session) -> None:
    program_job_id = _enqueue_mission(db, job_key="one-shot-mission-happy")
    # execute=True runs real convergence inspection (base_sha, open PRs, open
    # issues) before the provider ever dispatches - the fake transport must
    # answer that full real sequence, not just the final issue-creation call.
    transport = FakeTransport(
        [
            GitHubTransportResponse(200, {"object": {"sha": "a" * 40}}),
            GitHubTransportResponse(200, []),
            GitHubTransportResponse(200, []),
            GitHubTransportResponse(201, {"number": 4242}),
        ],
    )

    result = execute_one_shot_mission(
        db=db,
        transport=transport,
        request=_request(program_job_id=program_job_id),
    )

    assert result.state == "agent_assigned"
    assert result.program_job_id == program_job_id
    assert result.issue_number == 4242
    assert transport.calls[-1] == ("POST", f"/repos/{REPOSITORY}/issues")


def test_result_identity_mismatch_is_still_caught_as_defense_in_depth(db: Session, monkeypatch) -> None:
    """Even if the underlying cycle somehow returned a different job's
    result than the one verified pre-flight, this surface must still refuse
    to treat that as a normal outcome."""
    program_job_id = _enqueue_mission(db, job_key="one-shot-mission-mismatch")

    class _StubCycle:
        def run_once(self, *, owner, execute, confirmation):
            del owner, execute, confirmation
            from app.calyx_orchestrator.github_agent_dispatch_cycle import (
                DispatchCycleResult,
            )

            return DispatchCycleResult(state="agent_assigned", program_job_id="unexpected-job-id")

    monkeypatch.setattr(
        one_shot, "build_production_github_coding_agent_dispatch_cycle", lambda **kwargs: _StubCycle()
    )

    with pytest.raises(OneShotExecutionError, match="ONE_SHOT_EXECUTED_UNEXPECTED_JOB"):
        execute_one_shot_mission(
            db=db,
            transport=_NeverCalledTransport(),
            request=_request(program_job_id=program_job_id),
        )


def test_copilot_bot_login_constant_matches_what_the_fake_provider_expects() -> None:
    # Sanity check the fixture's own assumptions stay honest about which
    # identity the real observation gateway expects, even though this test
    # file's happy path doesn't reach the observer.
    assert COPILOT_BOT_LOGIN == "copilot-swe-agent[bot]"
