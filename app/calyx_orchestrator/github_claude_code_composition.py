from __future__ import annotations

from sqlalchemy.orm import Session

from .agent_security_gateway import (
    SecuredCodingAgentProvider,
    SecuredRepositoryInspectionGateway,
    build_github_coding_security_gateway,
)
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

    Repository inspection and provider dispatch are additionally wrapped by the
    provider-neutral Agent Security Gateway so changing model/provider capacity
    cannot change the authorized tool surface.
    """
    repository_allowlist = tuple(policy.repository_allowlist)
    security = build_github_coding_security_gateway(repository_allowlist)
    raw_inspector = GitHubRepositoryConvergenceInspector(
        transport=transport,
        repository_allowlist=repository_allowlist,
    )
    inspector = SecuredRepositoryInspectionGateway(
        inner=raw_inspector,
        security=security,
    )
    raw_provider = GitHubClaudeCodeActionProvider(
        transport=transport,
        repository_allowlist=repository_allowlist,
    )
    provider = SecuredCodingAgentProvider(
        inner=raw_provider,
        security=security,
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
