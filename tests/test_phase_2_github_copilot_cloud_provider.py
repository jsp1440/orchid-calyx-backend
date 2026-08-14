from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.calyx_orchestrator.github_coding_executor import (
    BudgetClass,
    ConvergenceClass,
    DispatchRequest,
)
from app.calyx_orchestrator.github_copilot_cloud_provider import (
    COPILOT_ASSIGNEE,
    GitHubCopilotCloudProvider,
)
from app.calyx_orchestrator.github_proposal_mutation_adapter import (
    GitHubTransportResponse,
)


@dataclass
class Transport:
    responses: list[GitHubTransportResponse]

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    def request(self, method: str, path: str, *, json_body=None, params=None):
        del params
        self.calls.append((method, path, None if json_body is None else dict(json_body)))
        return self.responses.pop(0)


def request(convergence: ConvergenceClass = ConvergenceClass.NEW, **kwargs) -> DispatchRequest:
    values = {
        "mission_id": "MISSION-1",
        "repository": "jsp1440/orchid-calyx-backend",
        "objective": "Implement the GitHub coding-agent bridge",
        "acceptance_criteria": ("preserve durable mission identity",),
        "validation_commands": ("pytest -q",),
        "budget_class": BudgetClass.NORMAL,
        "convergence_class": convergence,
        "base_ref": "main",
        "base_sha": "a" * 40,
        "related_issue_numbers": (973,),
        "overlapping_pr_numbers": (),
        "continuation_pr_numbers": (),
        "convergence_pr_numbers": (),
        "superseded_pr_numbers": (),
        "retry_count": 0,
    }
    values.update(kwargs)
    return DispatchRequest(**values)


def provider(transport: Transport) -> GitHubCopilotCloudProvider:
    return GitHubCopilotCloudProvider(
        transport=transport,
        repository_allowlist=("jsp1440/orchid-calyx-backend",),
    )


def test_new_mission_creates_and_assigns_issue_to_copilot() -> None:
    transport = Transport([GitHubTransportResponse(status_code=201, payload={"number": 1001})])
    result = provider(transport).dispatch(request())
    assert result.state == "agent_assigned"
    assert result.issue_number == 1001
    assert result.pull_request_number is None
    method, path, body = transport.calls[0]
    assert method == "POST"
    assert path == "/repos/jsp1440/orchid-calyx-backend/issues"
    assert body is not None
    assert body["assignees"] == [COPILOT_ASSIGNEE]
    assert body["agent_assignment"]["base_branch"] == "main"
    assert "Keep the pull request draft" in body["agent_assignment"]["custom_instructions"]


def test_continue_steers_existing_pr_instead_of_creating_new_issue() -> None:
    transport = Transport([GitHubTransportResponse(status_code=201, payload={"id": 1})])
    result = provider(transport).dispatch(
        request(
            ConvergenceClass.CONTINUE,
            continuation_pr_numbers=(975,),
            overlapping_pr_numbers=(975,),
        )
    )
    assert result.state == "iteration_requested"
    assert result.pull_request_number == 975
    method, path, body = transport.calls[0]
    assert method == "POST"
    assert path == "/repos/jsp1440/orchid-calyx-backend/issues/975/comments"
    assert body is not None
    assert body["body"].startswith("@copilot Continue this existing governed mission")


def test_continue_requires_exactly_one_existing_pr() -> None:
    transport = Transport([])
    with pytest.raises(PermissionError, match="CONTINUE_REQUIRES_ONE_PR"):
        provider(transport).dispatch(request(ConvergenceClass.CONTINUE))
    assert transport.calls == []


def test_already_done_cannot_reach_provider_side_effect() -> None:
    transport = Transport([])
    with pytest.raises(PermissionError, match="ALREADY_DONE_MUST_NOT_DISPATCH"):
        provider(transport).dispatch(request(ConvergenceClass.ALREADY_DONE))
    assert transport.calls == []


def test_nonallowlisted_repository_fails_before_transport() -> None:
    transport = Transport([])
    with pytest.raises(PermissionError, match="REPOSITORY_NOT_ALLOWED"):
        provider(transport).dispatch(request(repository="other/repo"))
    assert transport.calls == []
