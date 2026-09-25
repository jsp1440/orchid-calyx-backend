import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.github_agent_ci_policy import RequiredCiCheckPolicy
from app.calyx_orchestrator.github_agent_dispatch_cycle import GitHubCodingRuntimePolicy
from app.calyx_orchestrator.github_coding_executor import BudgetClass
from app.calyx_orchestrator.program_models import (
    CalyxProgram,
    CalyxProgramDependency,
    CalyxProgramJob,
)
from app.calyx_orchestrator.provider_free_coding_adapter import PROVIDER_FREE_EXECUTOR
from app.calyx_orchestrator.provider_free_coding_composition import (
    build_provider_free_durable_coding_cycle,
)
from app.database import Base


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CalyxProgram.__table__,
            CalyxProgramJob.__table__,
            CalyxProgramDependency.__table__,
        ],
    )
    with Session(engine) as session:
        yield session


def policy(**overrides):
    values = {
        "enabled": True,
        "owner_allowlist": frozenset({"owner"}),
        "repository_allowlist": frozenset({"orchid-calyx-backend"}),
        "max_budget_class": BudgetClass.TINY,
        "no_api_mode": True,
        "provider_free_executors": frozenset({PROVIDER_FREE_EXECUTOR}),
    }
    values.update(overrides)
    return GitHubCodingRuntimePolicy(**values)


def build(db, runtime_policy):
    return build_provider_free_durable_coding_cycle(
        db=db,
        transport=object(),
        policy=runtime_policy,
        required_checks=RequiredCiCheckPolicy(frozenset({"validation"})),
        runner=lambda _: None,
    )


def test_composition_requires_no_api_mode(db):
    with pytest.raises(PermissionError, match="PROVIDER_FREE_CYCLE_REQUIRES_NO_API_MODE"):
        build(db, policy(no_api_mode=False))


def test_composition_requires_trusted_executor_allowlist(db):
    with pytest.raises(PermissionError, match="PROVIDER_FREE_EXECUTOR_NOT_ALLOWLISTED"):
        build(db, policy(provider_free_executors=frozenset()))


def test_composition_uses_existing_durable_lease_and_dispatch_store(db):
    cycle = build(db, policy())
    assert cycle.policy.no_api_mode is True
    assert PROVIDER_FREE_EXECUTOR in cycle.policy.provider_free_executors
    assert cycle.leases.__class__.__name__ == "SqlAlchemyCodingJobLeaseGateway"
    assert cycle.store.__class__.__name__ == "DurableGitHubAgentDispatchStore"


def test_composition_is_pinned_to_integration_and_bound_pr_identity(db):
    cycle = build(db, policy())
    assert cycle.executor.inspector._base_ref == "oc-autonomous-integration"
    assert cycle.observer._bot_login is None
    assert cycle.observer._require_bound_pr is True
