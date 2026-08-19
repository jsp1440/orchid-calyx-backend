from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.calyx_orchestrator.github_agent_ci_policy import RequiredCiCheckPolicy
from app.calyx_orchestrator.github_agent_lifecycle import GitHubAgentDispatchRecord
from app.calyx_orchestrator.github_agent_observation_gateway import (
    COPILOT_BOT_LOGIN,
    GitHubIssueLinkedPullRequestObserver,
)
from app.calyx_orchestrator.github_proposal_mutation_adapter import (
    GitHubTransportResponse,
)

REPOSITORY = "jsp1440/orchid-calyx-backend"


@dataclass
class Transport:
    responses: list[GitHubTransportResponse]

    def __post_init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, path: str, *, json_body=None, params=None):
        del json_body, params
        self.calls.append((method, path))
        return self.responses.pop(0)


def dispatch(**kwargs) -> GitHubAgentDispatchRecord:
    values = {
        "program_job_id": "job-1",
        "mission_id": "MISSION-1",
        "repository": REPOSITORY,
        "base_sha": "a" * 40,
        "provider": "github-copilot-cloud-agent",
        "issue_number": 402,
    }
    values.update(kwargs)
    return GitHubAgentDispatchRecord(**values)


def observer(transport: Transport, *, required: frozenset[str] = frozenset({"validate"})):
    return GitHubIssueLinkedPullRequestObserver(
        transport=transport,
        required_checks=RequiredCiCheckPolicy(required_checks=required),
    )


def cross_referenced_event(*, pr_number: int, login: str = COPILOT_BOT_LOGIN, repository: str = REPOSITORY):
    return {
        "event": "cross-referenced",
        "source": {
            "type": "issue",
            "issue": {
                "number": pr_number,
                "user": {"login": login},
                "pull_request": {"url": "https://api.github.com/..."},
                "repository": {"full_name": repository},
            },
        },
    }


def pr_payload(*, number: int, head_sha: str, draft: bool = True, merged: bool = False, state: str = "open", login: str = COPILOT_BOT_LOGIN, repository: str = REPOSITORY):
    return {
        "number": number,
        "draft": draft,
        "merged": merged,
        "state": state,
        "html_url": f"https://github.com/{repository}/pull/{number}",
        "user": {"login": login},
        "base": {"repo": {"full_name": repository}},
        "head": {"sha": head_sha},
    }


def test_resolves_linked_pr_from_issue_timeline() -> None:
    """The exact pattern this repository's own issue #402 -> PR #404 history
    demonstrates: an assigned issue's timeline carries a cross-referenced
    event whose source is a Copilot-authored PR."""
    transport = Transport(
        [
            GitHubTransportResponse(200, [cross_referenced_event(pr_number=404)]),
            GitHubTransportResponse(200, pr_payload(number=404, head_sha="b" * 40)),
            GitHubTransportResponse(
                200,
                {"check_runs": [{"name": "validate", "status": "completed", "conclusion": "success"}]},
            ),
        ]
    )
    result = observer(transport).observe(dispatch(issue_number=402))
    assert result.pull_request_number == 404
    assert result.head_sha == "b" * 40
    assert result.draft is True
    assert result.required_checks_known is True
    assert result.required_checks_succeeded == ("validate",)


def test_no_linked_pr_yet_is_a_legitimate_await_not_a_failure() -> None:
    transport = Transport([GitHubTransportResponse(200, [])])
    result = observer(transport).observe(dispatch())
    assert result.pull_request_number is None


def test_ambiguous_pr_linkage_fails_closed() -> None:
    transport = Transport(
        [
            GitHubTransportResponse(
                200,
                [cross_referenced_event(pr_number=404), cross_referenced_event(pr_number=405)],
            )
        ]
    )
    with pytest.raises(RuntimeError, match="GITHUB_OBSERVATION_AMBIGUOUS_PR_LINKAGE"):
        observer(transport).observe(dispatch())


def test_cross_reference_from_a_non_copilot_author_is_ignored_as_a_candidate() -> None:
    transport = Transport(
        [GitHubTransportResponse(200, [cross_referenced_event(pr_number=404, login="someone-else")])]
    )
    result = observer(transport).observe(dispatch())
    assert result.pull_request_number is None


def test_wrong_provenance_on_direct_lookup_fails_closed() -> None:
    """Once a PR number is already bound, the observer re-verifies its
    provenance directly rather than trusting the earlier timeline scan."""
    transport = Transport([GitHubTransportResponse(200, pr_payload(number=404, head_sha="b" * 40, login="someone-else"))])
    with pytest.raises(PermissionError, match="GITHUB_OBSERVATION_PR_PROVENANCE_MISMATCH"):
        observer(transport).observe(dispatch(pull_request_number=404))


def test_repository_mismatch_on_direct_lookup_fails_closed() -> None:
    transport = Transport(
        [GitHubTransportResponse(200, pr_payload(number=404, head_sha="b" * 40, repository="someone/else"))]
    )
    with pytest.raises(PermissionError, match="GITHUB_OBSERVATION_REPOSITORY_MISMATCH"):
        observer(transport).observe(dispatch(pull_request_number=404))


def test_pr_closed_without_merge_fails_closed() -> None:
    transport = Transport(
        [GitHubTransportResponse(200, pr_payload(number=404, head_sha="b" * 40, state="closed", merged=False))]
    )
    with pytest.raises(PermissionError, match="GITHUB_OBSERVATION_PR_CLOSED_WITHOUT_MERGE"):
        observer(transport).observe(dispatch(pull_request_number=404))


def test_merged_pr_short_circuits_ci_evaluation() -> None:
    transport = Transport(
        [GitHubTransportResponse(200, pr_payload(number=404, head_sha="c" * 40, merged=True, state="closed"))]
    )
    result = observer(transport).observe(dispatch(pull_request_number=404))
    assert result.merged is True
    assert result.head_sha == "c" * 40


def test_known_pr_always_reads_that_exact_number_never_re_scans_timeline() -> None:
    transport = Transport(
        [
            GitHubTransportResponse(200, pr_payload(number=404, head_sha="d" * 40)),
            GitHubTransportResponse(200, {"check_runs": []}),
        ]
    )
    observer(transport).observe(dispatch(pull_request_number=404))
    assert transport.calls[0] == ("GET", f"/repos/{REPOSITORY}/pulls/404")
    assert all("timeline" not in path for _, path in transport.calls)


def test_failed_required_check_is_surfaced_with_a_failure_class() -> None:
    transport = Transport(
        [
            GitHubTransportResponse(200, pr_payload(number=404, head_sha="e" * 40)),
            GitHubTransportResponse(
                200,
                {"check_runs": [{"name": "validate", "status": "completed", "conclusion": "failure"}]},
            ),
        ]
    )
    result = observer(transport).observe(dispatch(pull_request_number=404))
    assert result.required_checks_failed == ("validate",)
    assert result.failure_class == "required_ci_failure:validate"


def test_infrastructure_conclusion_is_distinguished_from_a_code_failure() -> None:
    transport = Transport(
        [
            GitHubTransportResponse(200, pr_payload(number=404, head_sha="f" * 40)),
            GitHubTransportResponse(
                200,
                {"check_runs": [{"name": "validate", "status": "completed", "conclusion": "cancelled"}]},
            ),
        ]
    )
    result = observer(transport).observe(dispatch(pull_request_number=404))
    assert result.infrastructure_failure is True
    assert result.required_checks_failed == ()


def test_non_200_transport_response_fails_closed() -> None:
    transport = Transport([GitHubTransportResponse(404, {})])
    with pytest.raises(RuntimeError, match="GITHUB_OBSERVATION_PR_LOOKUP_FAILED"):
        observer(transport).observe(dispatch(pull_request_number=404))
