from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.github_agent_dispatch_cycle import (
    EXECUTE_CONFIRMATION,
    GitHubCodingAgentDispatchCycle,
    GitHubCodingRuntimePolicy,
    SqlAlchemyCodingJobLeaseGateway,
)
from app.calyx_orchestrator.github_coding_executor import BudgetClass
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

REPOSITORY = "jsp1440/orchid-calyx-backend"
OWNER = "jsp1440"


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[CalyxProgram.__table__, CalyxProgramJob.__table__, CalyxProgramDependency.__table__],
    )
    with Session(engine) as session:
        yield session


class _NullDispatchStore:
    """No dispatch has ever been recorded for this program job."""

    def get(self, *, program_job_id: str):
        return None

    def record(self, dispatch):  # pragma: no cover - not reached by the preflight path
        raise AssertionError("record() must not be called during preflight")


def _enqueue_github_coding_mission(
    db: Session,
    *,
    budget_class: str = "TINY",
    repository: str = REPOSITORY,
) -> str:
    """Mirrors exactly what a POST to the existing, owner-gated `/programs`
    route does (see `program_routes.create_program` + `start_program`) -
    this is the real, already-existing mission-creation path, not a new one.
    """
    repo = PersistentProgramRepository(db)
    program = repo.create_program(
        owner=OWNER,
        title="First GitHub coding-agent mission",
        objective="Prove the merged executor chain can claim a real, durably-persisted mission",
        jobs=[
            ProgramJobSpec(
                job_key="github-coding-mission-001",
                role_key="github_coding_agent",
                title="Smallest safe controlled test mission",
                repository=repository,
                branch="agent/github-coding-mission-001",
                mutating=True,
                inputs={"budget_class": budget_class, "mission_id": "github-coding-mission-001"},
            )
        ],
        dependencies=[],
    )
    repo.start(owner=OWNER, program_id=program.program_id)
    return program.program_id


def test_real_program_job_flows_through_to_preflight_ready(db: Session) -> None:
    """End-to-end: a mission created through the existing, already-governed
    program API is durably persisted, claimed through the real SQL-backed
    lease gateway (not a fake), and the merged dispatch cycle correctly
    reaches preflight_ready with zero provider side effects.

    This is the exact gap OPS-0008 identified: nothing had ever exercised
    the real CalyxProgramJob -> SqlAlchemyCodingJobLeaseGateway -> dispatch
    cycle path together. Every existing dispatch-cycle test uses a fake
    in-memory lease gateway instead of the real persistence layer.
    """
    _enqueue_github_coding_mission(db)

    policy = GitHubCodingRuntimePolicy(
        enabled=True,
        owner_allowlist=frozenset({OWNER}),
        repository_allowlist=frozenset({REPOSITORY}),
        max_budget_class=BudgetClass.NORMAL,
    )
    cycle = GitHubCodingAgentDispatchCycle(
        policy=policy,
        leases=SqlAlchemyCodingJobLeaseGateway(db),
        store=_NullDispatchStore(),
        executor=None,  # type: ignore[arg-type]  # unreached: preflight path with no existing dispatch
        observer=None,  # type: ignore[arg-type]
        repairer=None,  # type: ignore[arg-type]
    )

    result = cycle.run_once(owner=OWNER, execute=False)

    assert result.state == "preflight_ready"
    assert result.repository == REPOSITORY
    assert result.side_effects == ()


def test_disabled_policy_rejects_the_same_real_job(db: Session) -> None:
    """The same real, durably-persisted job is correctly rejected while the
    runtime policy remains disabled - proving disabled-by-default holds
    against real persisted state, not just the fakes in the unit tests."""
    _enqueue_github_coding_mission(db)

    policy = GitHubCodingRuntimePolicy()  # enabled=False by default
    cycle = GitHubCodingAgentDispatchCycle(
        policy=policy,
        leases=SqlAlchemyCodingJobLeaseGateway(db),
        store=_NullDispatchStore(),
        executor=None,  # type: ignore[arg-type]
        observer=None,  # type: ignore[arg-type]
        repairer=None,  # type: ignore[arg-type]
    )

    with pytest.raises(PermissionError, match="GITHUB_CODING_RUNTIME_DISABLED"):
        cycle.run_once(owner=OWNER, execute=False)


def test_no_queued_candidate_is_honest_idle(db: Session) -> None:
    """No job of any kind exists. The cycle must report the genuinely-empty
    case distinctly from a rejected-candidate case (see the next test) -
    that distinction is the entire point of this hardening pass."""
    policy = GitHubCodingRuntimePolicy(
        enabled=True,
        owner_allowlist=frozenset({OWNER}),
        repository_allowlist=frozenset({REPOSITORY}),
    )
    cycle = GitHubCodingAgentDispatchCycle(
        policy=policy,
        leases=SqlAlchemyCodingJobLeaseGateway(db),
        store=_NullDispatchStore(),
        executor=None,  # type: ignore[arg-type]
        observer=None,  # type: ignore[arg-type]
        repairer=None,  # type: ignore[arg-type]
    )

    result = cycle.run_once(owner=OWNER, execute=False)

    assert result.state == "idle_no_candidate"
    assert result.reason is None
    assert result.program_job_id is None


def test_mutating_candidate_without_branch_is_an_explicit_diagnostic_rejection(
    db: Session,
) -> None:
    """This is the exact previously-silent bug: a real mutating job created
    with branch=None used to make the dispatch cycle report a bare "idle"
    with zero explanation. It must now surface the real admission-policy
    rejection reason instead."""
    repo = PersistentProgramRepository(db)
    program = repo.create_program(
        owner=OWNER,
        title="Mission missing its authoritative branch",
        objective="Prove the previously-silent admission rejection is now explicit",
        jobs=[
            ProgramJobSpec(
                job_key="github-coding-mission-no-branch",
                role_key="github_coding_agent",
                title="Missing branch",
                repository=REPOSITORY,
                branch=None,  # the exact trigger for MUTATING_JOB_REQUIRES_BRANCH
                mutating=True,
                inputs={"budget_class": "TINY", "mission_id": "github-coding-mission-no-branch"},
            )
        ],
        dependencies=[],
    )
    repo.start(owner=OWNER, program_id=program.program_id)

    policy = GitHubCodingRuntimePolicy(
        enabled=True,
        owner_allowlist=frozenset({OWNER}),
        repository_allowlist=frozenset({REPOSITORY}),
    )
    cycle = GitHubCodingAgentDispatchCycle(
        policy=policy,
        leases=SqlAlchemyCodingJobLeaseGateway(db),
        store=_NullDispatchStore(),
        executor=None,  # type: ignore[arg-type]
        observer=None,  # type: ignore[arg-type]
        repairer=None,  # type: ignore[arg-type]
    )

    result = cycle.run_once(owner=OWNER, execute=False)

    assert result.state == "rejected_admission"
    assert result.reason == "MUTATING_JOB_REQUIRES_BRANCH"
    assert result.program_job_id is not None


def test_execute_mode_still_requires_exact_confirmation_against_real_job(db: Session) -> None:
    _enqueue_github_coding_mission(db)

    policy = GitHubCodingRuntimePolicy(
        enabled=True,
        owner_allowlist=frozenset({OWNER}),
        repository_allowlist=frozenset({REPOSITORY}),
    )
    cycle = GitHubCodingAgentDispatchCycle(
        policy=policy,
        leases=SqlAlchemyCodingJobLeaseGateway(db),
        store=_NullDispatchStore(),
        executor=None,  # type: ignore[arg-type]
        observer=None,  # type: ignore[arg-type]
        repairer=None,  # type: ignore[arg-type]
    )

    with pytest.raises(PermissionError, match="GITHUB_CODING_EXECUTE_CONFIRMATION_REQUIRED"):
        cycle.run_once(owner=OWNER, execute=True, confirmation="wrong-token")

    assert EXECUTE_CONFIRMATION == "DISPATCH_GITHUB_CODING_AGENT"
