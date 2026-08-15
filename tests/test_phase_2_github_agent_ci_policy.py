from __future__ import annotations

import pytest

from app.calyx_orchestrator.github_agent_ci_policy import RequiredCiCheckPolicy


def test_empty_roster_is_rejected() -> None:
    with pytest.raises(ValueError, match="REQUIRED_CI_CHECK_POLICY_EMPTY_ROSTER"):
        RequiredCiCheckPolicy(required_checks=frozenset())


def test_digest_is_deterministic_and_order_independent() -> None:
    a = RequiredCiCheckPolicy(required_checks=frozenset({"validate", "publication-pipeline-operational-readiness"}))
    b = RequiredCiCheckPolicy(required_checks=frozenset({"publication-pipeline-operational-readiness", "validate"}))
    assert a.digest() == b.digest()


def test_digest_changes_with_roster() -> None:
    a = RequiredCiCheckPolicy(required_checks=frozenset({"validate"}))
    b = RequiredCiCheckPolicy(required_checks=frozenset({"validate", "publication-pipeline-operational-readiness"}))
    assert a.digest() != b.digest()


def test_all_configured_checks_succeed_reaches_known_and_succeeded() -> None:
    policy = RequiredCiCheckPolicy(required_checks=frozenset({"validate", "publication-pipeline-operational-readiness"}))
    assessment = policy.evaluate(
        {"validate": "success", "publication-pipeline-operational-readiness": "success"}
    )
    assert assessment.required_checks_known is True
    assert assessment.required_checks_pending == ()
    assert assessment.required_checks_failed == ()
    assert set(assessment.required_checks_succeeded) == {"validate", "publication-pipeline-operational-readiness"}
    assert assessment.infrastructure_failure is False


def test_missing_configured_check_never_reports_known() -> None:
    """A required check that simply never appears in the check-runs response
    must never be silently treated as passing or skipped - completeness is
    never inferred from whatever subset GitHub happens to return."""
    policy = RequiredCiCheckPolicy(required_checks=frozenset({"validate", "never-configured-to-run"}))
    assessment = policy.evaluate({"validate": "success"})
    assert assessment.required_checks_known is False
    assert assessment.required_checks_pending == ("never-configured-to-run",)


def test_still_running_check_is_pending_not_failed() -> None:
    policy = RequiredCiCheckPolicy(required_checks=frozenset({"validate"}))
    assessment = policy.evaluate({"validate": None})
    assert assessment.required_checks_known is False
    assert assessment.required_checks_pending == ("validate",)
    assert assessment.required_checks_failed == ()


def test_real_failure_conclusion_is_a_code_failure_not_infrastructure() -> None:
    policy = RequiredCiCheckPolicy(required_checks=frozenset({"validate"}))
    assessment = policy.evaluate({"validate": "failure"})
    assert assessment.required_checks_known is True
    assert assessment.required_checks_failed == ("validate",)
    assert assessment.infrastructure_failure is False


@pytest.mark.parametrize("conclusion", ["cancelled", "timed_out", "action_required", "stale"])
def test_infrastructure_conclusions_never_count_as_a_code_failure(conclusion: str) -> None:
    policy = RequiredCiCheckPolicy(required_checks=frozenset({"validate"}))
    assessment = policy.evaluate({"validate": conclusion})
    assert assessment.infrastructure_failure is True
    assert assessment.required_checks_failed == ()
