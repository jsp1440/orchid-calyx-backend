import pytest

from app.calyx_orchestrator.github_agent_dispatch_cycle import GitHubCodingRuntimePolicy
from app.calyx_orchestrator.github_coding_executor import BudgetClass
from app.calyx_orchestrator.provider_free_coding_adapter import PROVIDER_FREE_EXECUTOR
from app.calyx_orchestrator.provider_free_coding_composition import (
    build_provider_free_durable_coding_cycle,
)


def policy(**overrides):
    values = dict(
        enabled=True,
        owner_allowlist=frozenset({"owner"}),
        repository_allowlist=frozenset({"orchid-calyx-backend"}),
        max_budget_class=BudgetClass.TINY,
        no_api_mode=True,
        provider_free_executors=frozenset({PROVIDER_FREE_EXECUTOR}),
    )
    values.update(overrides)
    return GitHubCodingRuntimePolicy(**values)


def test_composition_requires_no_api_mode(db, github_transport, required_ci_policy):
    with pytest.raises(PermissionError, match="PROVIDER_FREE_CYCLE_REQUIRES_NO_API_MODE"):
        build_provider_free_durable_coding_cycle(
            db=db,
            transport=github_transport,
            policy=policy(no_api_mode=False),
            required_checks=required_ci_policy,
            runner=lambda _: None,
        )


def test_composition_requires_trusted_executor_allowlist(
    db, github_transport, required_ci_policy
):
    with pytest.raises(PermissionError, match="PROVIDER_FREE_EXECUTOR_NOT_ALLOWLISTED"):
        build_provider_free_durable_coding_cycle(
            db=db,
            transport=github_transport,
            policy=policy(provider_free_executors=frozenset()),
            required_checks=required_ci_policy,
            runner=lambda _: None,
        )


def test_composition_uses_existing_durable_lease_and_dispatch_store(
    db, github_transport, required_ci_policy
):
    cycle = build_provider_free_durable_coding_cycle(
        db=db,
        transport=github_transport,
        policy=policy(),
        required_checks=required_ci_policy,
        runner=lambda _: None,
    )
    assert cycle.policy.no_api_mode is True
    assert PROVIDER_FREE_EXECUTOR in cycle.policy.provider_free_executors
    assert cycle.leases.__class__.__name__ == "SqlAlchemyCodingJobLeaseGateway"
    assert cycle.store.__class__.__name__ == "DurableGitHubAgentDispatchStore"
