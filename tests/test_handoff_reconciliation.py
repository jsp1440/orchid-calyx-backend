from __future__ import annotations

from dataclasses import replace

import pytest

from app.calyx_orchestrator.handoff_reconciliation import (
    ChainLink,
    CheckState,
    DurableObservation,
    HandoffState,
    ReportedClaim,
    reconcile_handoff,
)

HEAD = "a" * 40
OTHER = "b" * 40

# The claim from issue #1757, verbatim in substance: a branch, a file count, a
# test count, and nothing on GitHub.
DESKTOP_CLAIM = ReportedClaim(
    reporter_id="claude-desktop",
    branch="claude/r1-autonomy-next",
    changed_file_count=22,
    tests_passed=11121,
)

COMPLETE = DurableObservation(
    issue_number=1757,
    branch="claude/issue-1757",
    branch_head_sha=HEAD,
    commits_ahead_of_base=1,
    pr_number=1758,
    pr_is_draft=True,
    pr_head_sha=HEAD,
    checks_head_sha=HEAD,
    checks=CheckState.PASSED,
    remaining_gap_recorded=True,
)


def test_a_claim_with_nothing_on_github_is_local_claim_only():
    decision = reconcile_handoff(DESKTOP_CLAIM, DurableObservation(issue_number=1757))

    assert decision.state is HandoffState.LOCAL_CLAIM_ONLY
    assert decision.missing is ChainLink.BRANCH
    assert not decision.is_durable_completion
    assert not decision.claimed_branch_observed


def test_claimed_tests_never_substitute_for_executed_checks():
    observed = replace(COMPLETE, checks=CheckState.NOT_RUN, checks_head_sha="")

    decision = reconcile_handoff(DESKTOP_CLAIM, observed)

    assert decision.state is HandoffState.INCOMPLETE
    assert decision.missing is ChainLink.EXECUTED_CHECKS
    assert not decision.is_durable_completion


def test_no_claim_and_no_chain_is_incomplete_not_local_claim():
    decision = reconcile_handoff(None, DurableObservation())

    assert decision.state is HandoffState.INCOMPLETE
    assert decision.missing is ChainLink.ISSUE


@pytest.mark.parametrize(
    ("change", "link", "reason"),
    [
        ({"issue_number": None}, ChainLink.ISSUE, "NO_LINKED_ISSUE"),
        ({"branch_head_sha": ""}, ChainLink.BRANCH, "NO_BRANCH_ON_GITHUB"),
        (
            {"commits_ahead_of_base": 0},
            ChainLink.NON_EMPTY_COMMIT,
            "BRANCH_HAS_NO_COMMITS_AHEAD_OF_BASE",
        ),
        ({"pr_number": None}, ChainLink.DRAFT_PR, "NO_PULL_REQUEST_FOR_BRANCH"),
        ({"pr_is_draft": False}, ChainLink.DRAFT_PR, "PULL_REQUEST_IS_NOT_DRAFT"),
        (
            {"pr_head_sha": OTHER},
            ChainLink.EXACT_HEAD,
            "PR_HEAD_DOES_NOT_MATCH_BRANCH_HEAD",
        ),
        (
            {"checks_head_sha": OTHER},
            ChainLink.EXECUTED_CHECKS,
            f"CHECKS_RAN_AGAINST_{OTHER[:12]}_NOT_THIS_HEAD",
        ),
        (
            {"remaining_gap_recorded": False},
            ChainLink.RECORDED_GAP,
            "NO_REMAINING_GAP_OR_TERMINAL_EVIDENCE_RECORDED",
        ),
    ],
)
def test_each_missing_link_is_named(change, link, reason):
    decision = reconcile_handoff(None, replace(COMPLETE, **change))

    assert decision.missing is link
    assert decision.reason == reason
    assert not decision.is_durable_completion


def test_stale_checks_with_a_claim_are_incomplete_not_local_claim_only():
    # Some durable chain exists, so the claim is no longer the only thing there.
    decision = reconcile_handoff(
        DESKTOP_CLAIM, replace(COMPLETE, checks_head_sha=OTHER)
    )

    assert decision.state is HandoffState.INCOMPLETE


@pytest.mark.parametrize(
    ("checks", "state"),
    [
        (CheckState.NOT_EXECUTED, HandoffState.CI_INFRASTRUCTURE_BLOCKED),
        (CheckState.PENDING, HandoffState.IN_VALIDATION),
        (CheckState.FAILED, HandoffState.REPAIR),
        (CheckState.PASSED, HandoffState.DELIVERED),
    ],
)
def test_check_outcome_on_the_exact_head_decides_the_state(checks, state):
    decision = reconcile_handoff(None, replace(COMPLETE, checks=checks))

    assert decision.state is state
    assert decision.is_durable_completion is (state is HandoffState.DELIVERED)
    assert decision.head_sha == HEAD


def test_runner_non_execution_is_not_green():
    decision = reconcile_handoff(
        None, replace(COMPLETE, checks=CheckState.NOT_EXECUTED)
    )

    assert decision.state is not HandoffState.DELIVERED
    assert decision.missing is ChainLink.EXECUTED_CHECKS


def test_failed_checks_route_to_repair_before_gap_recording():
    observed = replace(COMPLETE, checks=CheckState.FAILED, remaining_gap_recorded=False)

    assert reconcile_handoff(None, observed).state is HandoffState.REPAIR


def test_claimed_branch_is_reported_only_when_github_has_it():
    observed = replace(COMPLETE, branch=DESKTOP_CLAIM.branch)

    assert reconcile_handoff(DESKTOP_CLAIM, observed).claimed_branch_observed
    assert not reconcile_handoff(DESKTOP_CLAIM, COMPLETE).claimed_branch_observed


@pytest.mark.parametrize("field", ["branch_head_sha", "pr_head_sha", "checks_head_sha"])
@pytest.mark.parametrize("value", [HEAD[:7], HEAD.upper(), "main"])
def test_abbreviated_or_symbolic_heads_are_refused(field, value):
    with pytest.raises(ValueError, match="HEAD_SHA_MUST_BE_40_HEX"):
        DurableObservation(**{field: value})


def test_negative_commit_count_is_refused():
    with pytest.raises(ValueError, match="COMMITS_AHEAD_MUST_BE_NON_NEGATIVE"):
        DurableObservation(commits_ahead_of_base=-1)


@pytest.mark.parametrize(
    "value", ["failed", "pending", "not_executed", "not_run", None, object()]
)
def test_raw_or_unknown_check_states_are_refused(value):
    with pytest.raises(TypeError, match="CHECKS_MUST_BE_CHECK_STATE"):
        DurableObservation(checks=value)


@pytest.mark.parametrize("field", ["pr_is_draft", "remaining_gap_recorded"])
@pytest.mark.parametrize("value", ["false", 0, 1, None])
def test_non_boolean_gate_values_are_refused(field, value):
    with pytest.raises(TypeError, match=f"{field.upper()}_MUST_BE_BOOL"):
        DurableObservation(**{field: value})


@pytest.mark.parametrize("field", ["issue_number", "pr_number"])
@pytest.mark.parametrize("value", [True, False, 0, -1, "1757", 1.5])
def test_non_positive_or_non_integer_identifiers_are_refused(field, value):
    error = f"{field.upper()}_MUST_BE_POSITIVE_INT_OR_NONE"
    with pytest.raises((TypeError, ValueError), match=error):
        DurableObservation(**{field: value})


@pytest.mark.parametrize("value", [True, False, -1, "1", 1.5])
def test_commit_count_requires_a_non_negative_integer(value):
    with pytest.raises(
        (TypeError, ValueError), match="COMMITS_AHEAD_MUST_BE_NON_NEGATIVE_INT"
    ):
        DurableObservation(commits_ahead_of_base=value)


@pytest.mark.parametrize(
    "field", ["branch", "branch_head_sha", "pr_head_sha", "checks_head_sha"]
)
@pytest.mark.parametrize("value", [None, True, 123])
def test_observation_text_fields_require_strings(field, value):
    with pytest.raises(TypeError, match=f"{field.upper()}_MUST_BE_STR"):
        DurableObservation(**{field: value})
