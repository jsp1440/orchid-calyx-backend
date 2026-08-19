from __future__ import annotations

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
from .github_coding_executor import GitHubCodingAgentExecutor
from .github_copilot_cloud_provider import GitHubCopilotCloudProvider
from .github_proposal_mutation_adapter import GitHubTransport
from .github_repository_inspector import GitHubRepositoryConvergenceInspector


def build_production_github_coding_agent_dispatch_cycle(
    *,
    db: Session,
    transport: GitHubTransport,
    policy: GitHubCodingRuntimePolicy,
    required_checks: RequiredCiCheckPolicy,
) -> GitHubCodingAgentDispatchCycle:
    """Construct a genuinely real, fully-wired `GitHubCodingAgentDispatchCycle`
    from production collaborators - the remaining piece of backend issue
    #973 (the "production observe/reconcile/repair connection").

    This function is disabled by default in the only way that matters:
    nothing in this codebase calls it. It is not imported by `app.main`, not
    registered as a route, and not attached to any scheduler or recurring
    worker. Calling it constructs an object graph; it does not schedule or
    perform any GitHub call by itself. Every mutating action inside the
    resulting cycle's `run_once()` still additionally requires
    `policy.enabled=True`, the caller to be in `policy.owner_allowlist`, and
    (for `execute=True`) the exact confirmation string
    `GitHubCodingRuntimePolicy` already requires - none of that is relaxed
    or bypassed here. Wiring this factory's result into `app.main`, a route,
    or a recurring worker is a separate, later, owner-governed activation
    decision that this module deliberately does not take.
    """
    repository_allowlist = tuple(policy.repository_allowlist)
    inspector = GitHubRepositoryConvergenceInspector(
        transport=transport,
        repository_allowlist=repository_allowlist,
    )
    provider = GitHubCopilotCloudProvider(
        transport=transport,
        repository_allowlist=repository_allowlist,
    )
    executor = GitHubCodingAgentExecutor(inspector=inspector, provider=provider)
    observer = GitHubIssueLinkedPullRequestObserver(
        transport=transport,
        required_checks=required_checks,
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
