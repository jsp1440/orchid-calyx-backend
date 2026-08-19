from __future__ import annotations

from dataclasses import dataclass

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.github_agent_ci_policy import RequiredCiCheckPolicy
from app.calyx_orchestrator.github_agent_composition import (
    build_production_github_coding_agent_dispatch_cycle,
)
from app.calyx_orchestrator.github_agent_dispatch_cycle import (
    GitHubCodingAgentDispatchCycle,
    GitHubCodingRuntimePolicy,
    SqlAlchemyCodingJobLeaseGateway,
)
from app.calyx_orchestrator.github_agent_dispatch_store import (
    DurableGitHubAgentDispatchStore,
    GitHubAgentDispatchRecordRow,
)
from app.calyx_orchestrator.github_agent_observation_gateway import (
    GitHubIssueLinkedPullRequestObserver,
)
from app.calyx_orchestrator.github_agent_repair_gateway import (
    GitHubCommentRepairGateway,
)
from app.calyx_orchestrator.github_coding_executor import GitHubCodingAgentExecutor
from app.calyx_orchestrator.program_models import (
    CalyxProgram,
    CalyxProgramDependency,
    CalyxProgramJob,
)
from app.database import Base

REPOSITORY = "jsp1440/orchid-calyx-backend"


@dataclass
class _NeverCalledTransport:
    def request(self, method: str, path: str, *, json_body=None, params=None):  # pragma: no cover
        raise AssertionError("no GitHub call may happen merely from constructing the composition")


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


def test_composition_builds_a_genuinely_real_dispatch_cycle(db: Session) -> None:
    """Every collaborator must be the real production class - not a fake,
    not a None placeholder - and constructing it must not itself make any
    GitHub call or otherwise activate anything."""
    policy = GitHubCodingRuntimePolicy(
        enabled=True,
        owner_allowlist=frozenset({"jsp1440"}),
        repository_allowlist=frozenset({REPOSITORY}),
    )
    cycle = build_production_github_coding_agent_dispatch_cycle(
        db=db,
        transport=_NeverCalledTransport(),
        policy=policy,
        required_checks=RequiredCiCheckPolicy(required_checks=frozenset({"validate"})),
    )

    assert isinstance(cycle, GitHubCodingAgentDispatchCycle)
    assert isinstance(cycle.leases, SqlAlchemyCodingJobLeaseGateway)
    assert isinstance(cycle.store, DurableGitHubAgentDispatchStore)
    assert isinstance(cycle.executor, GitHubCodingAgentExecutor)
    assert isinstance(cycle.observer, GitHubIssueLinkedPullRequestObserver)
    assert isinstance(cycle.repairer, GitHubCommentRepairGateway)
    # Disabled-by-default is a property of the policy the caller supplies,
    # not something this factory silently overrides.
    assert cycle.policy.enabled is True


def test_composition_defaults_stay_disabled_unless_the_caller_opts_in(db: Session) -> None:
    cycle = build_production_github_coding_agent_dispatch_cycle(
        db=db,
        transport=_NeverCalledTransport(),
        policy=GitHubCodingRuntimePolicy(
            repository_allowlist=frozenset({REPOSITORY}),
        ),  # enabled=False by default
        required_checks=RequiredCiCheckPolicy(required_checks=frozenset({"validate"})),
    )
    with pytest.raises(PermissionError, match="GITHUB_CODING_RUNTIME_DISABLED"):
        cycle.run_once(owner="jsp1440")
