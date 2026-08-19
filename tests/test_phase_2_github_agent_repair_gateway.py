from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.calyx_orchestrator.github_agent_lifecycle import GitHubAgentDispatchRecord
from app.calyx_orchestrator.github_agent_repair_gateway import (
    GitHubCommentRepairGateway,
)
from app.calyx_orchestrator.github_proposal_mutation_adapter import (
    GitHubTransportResponse,
)

REPOSITORY = "jsp1440/orchid-calyx-backend"


@dataclass
class Transport:
    responses: list[GitHubTransportResponse]

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []

    def request(self, method: str, path: str, *, json_body=None, params=None):
        del params
        self.calls.append((method, path, json_body))
        return self.responses.pop(0)


def dispatch(**kwargs) -> GitHubAgentDispatchRecord:
    values = {
        "program_job_id": "job-1",
        "mission_id": "MISSION-1",
        "repository": REPOSITORY,
        "base_sha": "a" * 40,
        "provider": "github-copilot-cloud-agent",
        "issue_number": 402,
        "pull_request_number": 404,
        "repair_attempts": 0,
    }
    values.update(kwargs)
    return GitHubAgentDispatchRecord(**values)


def test_posts_an_at_copilot_comment_on_the_bound_pr_and_returns_its_url() -> None:
    transport = Transport(
        [GitHubTransportResponse(201, {"html_url": f"https://github.com/{REPOSITORY}/pull/404#issuecomment-1"})]
    )
    gateway = GitHubCommentRepairGateway(transport=transport)

    url = gateway.request_repair(dispatch(), failure_class="required_ci_failure:validate")

    assert url == f"https://github.com/{REPOSITORY}/pull/404#issuecomment-1"
    method, path, body = transport.calls[0]
    assert method == "POST"
    assert path == f"/repos/{REPOSITORY}/issues/404/comments"
    assert "@copilot" in body["body"]
    assert "required_ci_failure:validate" in body["body"]


def test_refuses_to_repair_before_a_pr_exists() -> None:
    gateway = GitHubCommentRepairGateway(transport=Transport([]))
    with pytest.raises(PermissionError, match="GITHUB_REPAIR_PR_REQUIRED"):
        gateway.request_repair(dispatch(pull_request_number=None), failure_class="x")


def test_non_201_response_fails_closed() -> None:
    transport = Transport([GitHubTransportResponse(403, {})])
    gateway = GitHubCommentRepairGateway(transport=transport)
    with pytest.raises(RuntimeError, match="GITHUB_REPAIR_COMMENT_FAILED"):
        gateway.request_repair(dispatch(), failure_class="x")
