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
from .github_claude_code_action_provider import GitHubClaudeCodeActionProvider
from .github_claude_code_repair_gateway import GitHubClaudeCodeRepairGateway
from .github_coding_executor import GitHubCodingAgentExecutor
from .github_proposal_mutation_adapter import GitHubTransport
from .github_repository_inspector import GitHubRepositoryConvergenceInspector


def build_production_claude_code_dispatch_cycle(
    *,
    db: Session,
    transport: GitHubTransport,
    policy: GitHubCodingRuntimePolicy,
    required_checks: RequiredCiCheckPolicy,
) -> GitHubCodingAgentDispatchCycle:
    """Construct the real Claude Code GitHub Action executor graph.

    Construction is side-effect free. This factory is intentionally not imported
    by ``app.main`` and is not attached to a route, scheduler, or worker. The same
    runtime policy and explicit execute confirmation used by the existing Copilot
    path remain mandatory before a mutating dispatch can occur.
    """
    repository_allowlist = tuple(policy.repository_allowlist)
    inspector = GitHubRepositoryConvergenceInspector(
        transport=transport,
        repository_allowlist=repository_allowlist,
    )
    provider = GitHubClaudeCodeActionProvider(
        transport=transport,
        repository_allowlist=repository_allowlist,
    )
    executor = GitHubCodingAgentExecutor(inspector=inspector, provider=provider)
    observer = GitHubIssueLinkedPullRequestObserver(
        transport=transport,
        required_checks=required_checks,
    )
    repairer = GitHubClaudeCodeRepairGateway(transport=transport)
    return GitHubCodingAgentDispatchCycle(
        policy=policy,
        leases=SqlAlchemyCodingJobLeaseGateway(db),
        store=DurableGitHubAgentDispatchStore(db),
        executor=executor,
        observer=observer,
        repairer=repairer,
    )
