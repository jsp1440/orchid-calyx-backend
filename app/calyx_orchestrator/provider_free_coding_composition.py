"""Durable composition for the provider-free deterministic coding worker.

Construction only: this module does not schedule, dispatch, merge, deploy, or
contact a model provider. Activation remains an explicit runtime decision.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from .github_agent_ci_policy import RequiredCiCheckPolicy
from .github_agent_dispatch_cycle import (
    GitHubCodingAgentDispatchCycle,
    GitHubCodingRuntimePolicy,
    SqlAlchemyCodingJobLeaseGateway,
)
from .github_agent_dispatch_store import DurableGitHubAgentDispatchStore
from .github_agent_observation_gateway import GitHubIssueLinkedPullRequestObserver
from .github_agent_repair_gateway import GitHubCommentRepairGateway
from .github_coding_executor import DispatchRequest, GitHubCodingAgentExecutor
from .github_proposal_mutation_adapter import GitHubTransport
from .github_repository_inspector import GitHubRepositoryConvergenceInspector
from .provider_free_coding_adapter import (
    PROVIDER_FREE_EXECUTOR,
    DeterministicWorkerReceipt,
    ProviderFreeCodingAdapter,
)


def build_provider_free_durable_coding_cycle(
    *,
    db: Session,
    transport: GitHubTransport,
    policy: GitHubCodingRuntimePolicy,
    required_checks: RequiredCiCheckPolicy,
    runner: Callable[[DispatchRequest], DeterministicWorkerReceipt],
) -> GitHubCodingAgentDispatchCycle:
    """Wire the deterministic adapter into the existing durable lease lifecycle."""
    if not policy.no_api_mode:
        raise PermissionError("PROVIDER_FREE_CYCLE_REQUIRES_NO_API_MODE")
    if PROVIDER_FREE_EXECUTOR not in policy.provider_free_executors:
        raise PermissionError("PROVIDER_FREE_EXECUTOR_NOT_ALLOWLISTED")

    repository_allowlist = tuple(policy.repository_allowlist)
    inspector = GitHubRepositoryConvergenceInspector(
        transport=transport,
        repository_allowlist=repository_allowlist,
        base_ref="oc-autonomous-integration",
    )
    provider = ProviderFreeCodingAdapter(runner)
    executor = GitHubCodingAgentExecutor(inspector=inspector, provider=provider)
    observer = GitHubIssueLinkedPullRequestObserver(
        transport=transport,
        required_checks=required_checks,
        bot_login=None,
        require_bound_pr=True,
    )
    repairer = GitHubCommentRepairGateway(transport=transport)

    return GitHubCodingAgentDispatchCycle(
        policy=policy,
        leases=SqlAlchemyCodingJobLeaseGateway(db),
        store=DurableGitHubAgentDispatchStore(db),
        executor=executor,
        observer=observer,
        repairer=repairer,
    )
