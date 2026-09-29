"""Restart/idempotency acceptance proof for the provider-free coding lifecycle."""

from app.calyx_orchestrator.github_agent_lifecycle import (
    AgentLifecycleState,
    GitHubAgentDispatchRecord,
    PullRequestObservation,
    reconcile_agent_lifecycle,
)


def dispatch(state=AgentLifecycleState.CI_PENDING):
    return GitHubAgentDispatchRecord(
        program_job_id="job-660",
        mission_id="mission-660",
        repository="orchid-continuum-frontend",
        base_sha="a" * 40,
        provider="provider-free",
        issue_number=660,
        state=state,
        branch="oc-auto-660",
        pull_request_number=1491,
        pull_request_url="https://github.com/jsp1440/orchid-continuum-frontend/pull/1491",
        head_sha="b" * 40,
    )


def observation(**kw):
    base = {
        "repository": "orchid-continuum-frontend",
        "issue_number": 660,
        "pull_request_number": 1491,
        "draft": True,
        "head_sha": "b" * 40,
        "required_checks_known": True,
    }
    base.update(kw)
    return PullRequestObservation(**base)


def test_restart_reconciliation_does_not_redispatch_existing_work():
    persisted = dispatch()
    decision = reconcile_agent_lifecycle(
        persisted,
        observation(required_checks_pending=("frontend-ci",)),
    )
    assert decision.record.program_job_id == persisted.program_job_id
    assert decision.record.pull_request_number == 1491
    assert decision.record.provider == "provider-free"
    assert decision.action.value == "await"
    assert decision.record.state == AgentLifecycleState.CI_PENDING


def test_repeated_unchanged_observation_is_idempotent():
    persisted = dispatch()
    observed = observation(required_checks_pending=("frontend-ci",))
    first = reconcile_agent_lifecycle(persisted, observed)
    second = reconcile_agent_lifecycle(first.record, observed)
    assert second.action == first.action
    assert second.record.pull_request_number == first.record.pull_request_number
    assert second.record.repair_attempts == first.record.repair_attempts


def test_green_restart_advances_to_owner_review_without_merge():
    decision = reconcile_agent_lifecycle(
        dispatch(),
        observation(draft=True),
    )
    assert decision.record.state == AgentLifecycleState.READY_FOR_OWNER_REVIEW
    assert decision.action.value == "owner_review"
    assert decision.record.pull_request_number == 1491


def test_failed_ci_restart_requests_bounded_repair_not_redispatch():
    decision = reconcile_agent_lifecycle(
        dispatch(),
        observation(
            required_checks_failed=("frontend-ci",),
            failure_class="test_failure",
        ),
    )
    assert decision.action.value == "request_repair"
    assert decision.record.pull_request_number == 1491
    assert decision.record.last_failure_class == "test_failure"
