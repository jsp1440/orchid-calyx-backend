from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from app.calyx_orchestrator.github_claude_code_action_provider import (
    GitHubClaudeCodeActionProvider,
)
from app.calyx_orchestrator.github_coding_executor import (
    BudgetClass,
    ConvergenceClass,
    DispatchRequest,
)
from app.calyx_orchestrator.github_proposal_mutation_adapter import (
    GitHubTransportResponse,
)


@dataclass
class FakeTransport:
    responses: list[GitHubTransportResponse]
    requests: list[tuple[str, str, object]] = field(default_factory=list)

    def request(self, method: str, path: str, *, json_body: object | None = None):
        self.requests.append((method, path, json_body))
        return self.responses.pop(0)


def request_for(convergence: ConvergenceClass) -> DispatchRequest:
    return DispatchRequest(
        mission_id="CLAUDE-BOOTSTRAP-001",
        repository="jsp1440/orchid-calyx-backend",
        objective="Add a harmless documentation note",
        acceptance_criteria=("README contains the note",),
        validation_commands=("git diff --check",),
        budget_class=BudgetClass.TINY,
        convergence_class=convergence,
        base_ref="main",
        base_sha="a" * 40,
        related_issue_numbers=(10,),
        overlapping_pr_numbers=(),
        continuation_pr_numbers=(42,) if convergence == ConvergenceClass.CONTINUE else (),
        convergence_pr_numbers=(),
        superseded_pr_numbers=(),
        retry_count=0,
    )


def test_new_mission_creates_at_claude_trigger_issue() -> None:
    transport = FakeTransport([GitHubTransportResponse(201, {"number": 123})])
    provider = GitHubClaudeCodeActionProvider(
        transport=transport,
        repository_allowlist=("jsp1440/orchid-calyx-backend",),
    )

    result = provider.dispatch(request_for(ConvergenceClass.NEW))

    assert result.provider == "anthropic-claude-code-github-action"
    assert result.issue_number == 123
    assert result.pull_request_number is None
    assert result.draft is True
    assert result.state == "agent_triggered"
    method, path, payload = transport.requests[0]
    assert method == "POST"
    assert path == "/repos/jsp1440/orchid-calyx-backend/issues"
    assert payload["title"].startswith("@claude CLAUDE-BOOTSTRAP-001")
    assert "Read `CLAUDE.md` and `AGENTS.md`" in payload["body"]
    assert "Draft PR only" in payload["body"]


def test_continue_comments_on_exactly_one_existing_pr() -> None:
    transport = FakeTransport([GitHubTransportResponse(201, {"html_url": "https://example"})])
    provider = GitHubClaudeCodeActionProvider(
        transport=transport,
        repository_allowlist=("jsp1440/orchid-calyx-backend",),
    )

    result = provider.dispatch(request_for(ConvergenceClass.CONTINUE))

    assert result.pull_request_number == 42
    assert result.state == "iteration_requested"
    method, path, payload = transport.requests[0]
    assert method == "POST"
    assert path == "/repos/jsp1440/orchid-calyx-backend/issues/42/comments"
    assert payload["body"].startswith("@claude Continue this existing governed mission")


def test_provider_fails_closed_outside_repository_allowlist() -> None:
    provider = GitHubClaudeCodeActionProvider(
        transport=FakeTransport([]),
        repository_allowlist=("jsp1440/orchid-continuum-frontend",),
    )

    with pytest.raises(PermissionError, match="CLAUDE_PROVIDER_REPOSITORY_NOT_ALLOWED"):
        provider.dispatch(request_for(ConvergenceClass.NEW))


def test_provider_never_dispatches_already_done() -> None:
    provider = GitHubClaudeCodeActionProvider(
        transport=FakeTransport([]),
        repository_allowlist=("jsp1440/orchid-calyx-backend",),
    )

    with pytest.raises(PermissionError, match="CLAUDE_PROVIDER_ALREADY_DONE_MUST_NOT_DISPATCH"):
        provider.dispatch(request_for(ConvergenceClass.ALREADY_DONE))
