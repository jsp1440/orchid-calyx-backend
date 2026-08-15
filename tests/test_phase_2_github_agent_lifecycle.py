from __future__ import annotations

import pytest

from app.calyx_orchestrator.github_agent_lifecycle import (
    AgentLifecycleState,
    GitHubAgentDispatchRecord,
    LifecycleAction,
    PullRequestObservation,
    reconcile_agent_lifecycle,
    record_repair_request,
)


def record(**kwargs) -> GitHubAgentDispatchRecord:
    values = {
        "program_job_id": "job-1",
        "mission_id": "MISSION-1",
        "repository": "jsp1440/orchid-calyx-backend",
        "base_sha": "a" * 40,
        "provider": "github-copilot-cloud-agent",
        "issue_number": 1001,
    }
    values.update(kwargs)
    return GitHubAgentDispatchRecord(**values)


def observation(**kwargs) -> PullRequestObservation:
    values = {
        "repository": "jsp1440/orchid-calyx-backend",
        "issue_number": 1001,
    }
    values.update(kwargs)
    return PullRequestObservation(**values)


def test_blank_branch_fails_verification() -> None:
    with pytest.raises(ValueError, match="GITHUB_AGENT_DISPATCH_BRANCH_INVALID"):
        record(branch="   ").verify()


def test_branch_defaults_to_none_and_survives_lifecycle_transitions() -> None:
    """branch is set once at dispatch creation and must be preserved across
    every subsequent lifecycle transition, exactly like repository/base_sha -
    it is an identity field, not observation-driven state."""
    dispatch = record(branch="agent/mission-001")
    assert dispatch.branch == "agent/mission-001"

    decision = reconcile_agent_lifecycle(dispatch, observation())
    assert decision.record.branch == "agent/mission-001"

    with_pr = reconcile_agent_lifecycle(
        decision.record,
        observation(
            pull_request_number=1002,
            pull_request_url="https://github.com/jsp1440/orchid-calyx-backend/pull/1002",
            draft=True,
            head_sha="b" * 40,
            required_checks_known=True,
        ),
    )
    assert with_pr.record.branch == "agent/mission-001"


def test_assignment_waits_without_pr_and_never_releases_dependencies() -> None:
    decision = reconcile_agent_lifecycle(record(), observation())
    assert decision.record.state == AgentLifecycleState.AWAITING_PR
    assert decision.action == LifecycleAction.AWAIT
    assert decision.dependency_release_allowed is False


def test_green_draft_pr_stops_at_owner_review_gate() -> None:
    decision = reconcile_agent_lifecycle(
        record(),
        observation(
            pull_request_number=1002,
            pull_request_url="https://github.com/jsp1440/orchid-calyx-backend/pull/1002",
            draft=True,
            head_sha="b" * 40,
            required_checks_known=True,
            required_checks_succeeded=("focused", "governance"),
        ),
    )
    assert decision.record.state == AgentLifecycleState.READY_FOR_OWNER_REVIEW
    assert decision.action == LifecycleAction.OWNER_REVIEW
    assert decision.dependency_release_allowed is False


def test_only_observed_merge_allows_dependency_release() -> None:
    decision = reconcile_agent_lifecycle(
        record(pull_request_number=1002, head_sha="b" * 40),
        observation(
            pull_request_number=1002,
            merged=True,
            head_sha="b" * 40,
            required_checks_known=True,
        ),
    )
    assert decision.record.state == AgentLifecycleState.MERGED
    assert decision.action == LifecycleAction.MARK_DELIVERED
    assert decision.dependency_release_allowed is True


def test_failed_ci_requests_repair_without_incrementing_until_dispatch_accepted() -> None:
    first = reconcile_agent_lifecycle(
        record(pull_request_number=1002),
        observation(
            pull_request_number=1002,
            draft=True,
            required_checks_known=True,
            required_checks_failed=("focused",),
            failure_class="ruff",
        ),
    )
    assert first.action == LifecycleAction.REQUEST_REPAIR
    assert first.record.repair_attempts == 0
    accepted = record_repair_request(first.record, failure_class="ruff")
    assert accepted.repair_attempts == 1
    assert accepted.state == AgentLifecycleState.CI_PENDING


def test_infrastructure_failure_does_not_consume_repair_budget() -> None:
    decision = reconcile_agent_lifecycle(
        record(pull_request_number=1002, repair_attempts=2),
        observation(
            pull_request_number=1002,
            infrastructure_failure=True,
            failure_class="runner_unavailable",
        ),
    )
    assert decision.action == LifecycleAction.AWAIT
    assert decision.record.repair_attempts == 2
    assert decision.record.state == AgentLifecycleState.CI_PENDING


def test_third_same_failure_ceiling_escalates_without_another_repair() -> None:
    decision = reconcile_agent_lifecycle(
        record(pull_request_number=1002, repair_attempts=3),
        observation(
            pull_request_number=1002,
            draft=True,
            required_checks_known=True,
            required_checks_failed=("focused",),
            failure_class="same-test-failure",
        ),
    )
    assert decision.action == LifecycleAction.ESCALATE
    assert decision.record.state == AgentLifecycleState.BLOCKED
    assert decision.dependency_release_allowed is False


def test_non_draft_agent_pr_fails_closed() -> None:
    decision = reconcile_agent_lifecycle(
        record(pull_request_number=1002),
        observation(
            pull_request_number=1002,
            draft=False,
            required_checks_known=True,
            required_checks_succeeded=("focused",),
        ),
    )
    assert decision.action == LifecycleAction.ESCALATE
    assert decision.record.state == AgentLifecycleState.BLOCKED


def test_pr_identity_mismatch_fails_closed() -> None:
    with pytest.raises(PermissionError, match="PR_MISMATCH"):
        reconcile_agent_lifecycle(
            record(pull_request_number=1002),
            observation(pull_request_number=1003),
        )
