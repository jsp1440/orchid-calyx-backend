from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone

import pytest

from app.kernel import (
    GovernanceAction,
    GovernanceDecision,
    GovernancePolicy,
    GovernanceRequest,
    OCIDFactory,
    OCIDKind,
    PolicyEffect,
    PolicyStatus,
    ScientificObjectValidationError,
)


def test_governance_policy_requires_name_and_actions() -> None:
    with pytest.raises(ScientificObjectValidationError, match="name must not be empty"):
        GovernancePolicy(actions=(GovernanceAction.PUBLISH,))

    with pytest.raises(ScientificObjectValidationError, match="at least one governed action"):
        GovernancePolicy(name="Publish policy")


def test_active_policy_requires_author_and_reviewer() -> None:
    with pytest.raises(ScientificObjectValidationError, match="require authored_by"):
        GovernancePolicy(
            name="Publication approval",
            actions=(GovernanceAction.PUBLISH,),
            status=PolicyStatus.ACTIVE,
            reviewed_by="reviewer@example.org",
        )

    with pytest.raises(ScientificObjectValidationError, match="require reviewed_by"):
        GovernancePolicy(
            name="Publication approval",
            actions=(GovernanceAction.PUBLISH,),
            status=PolicyStatus.ACTIVE,
            authored_by="author@example.org",
        )


def test_policy_is_immutable_and_conditions_are_read_only() -> None:
    policy = GovernancePolicy(
        name="Review before commit",
        actions=(GovernanceAction.COMMIT,),
        conditions={"minimum_reviewers": 1},
    )

    with pytest.raises(FrozenInstanceError):
        policy.priority = 10  # type: ignore[misc]
    with pytest.raises(TypeError):
        policy.conditions["minimum_reviewers"] = 2  # type: ignore[index]


def test_policy_normalizes_effective_window_to_utc() -> None:
    local_tz = timezone(timedelta(hours=-7))
    policy = GovernancePolicy(
        name="Seasonal policy",
        actions=(GovernanceAction.EXECUTE,),
        effective_from=datetime(2026, 7, 23, 8, tzinfo=local_tz),
        effective_until=datetime(2026, 7, 24, 8, tzinfo=local_tz),
    )

    assert policy.effective_from == datetime(2026, 7, 23, 15, tzinfo=timezone.utc)
    assert policy.effective_until == datetime(2026, 7, 24, 15, tzinfo=timezone.utc)


def test_policy_rejects_duplicate_actions() -> None:
    with pytest.raises(ScientificObjectValidationError, match="actions must be unique"):
        GovernancePolicy(
            name="Duplicate action policy",
            actions=(GovernanceAction.READ, GovernanceAction.READ),
        )


def test_superseded_policy_requires_valid_predecessor() -> None:
    with pytest.raises(ScientificObjectValidationError, match="require supersedes_policy_ocid"):
        GovernancePolicy(
            name="Superseded policy",
            actions=(GovernanceAction.QUERY,),
            status=PolicyStatus.SUPERSEDED,
            reviewed_by="reviewer@example.org",
        )


def test_governance_request_validates_publication_scope() -> None:
    with pytest.raises(ScientificObjectValidationError, match="PUBLICATION OCID"):
        GovernanceRequest(
            action=GovernanceAction.COMMIT,
            publication_ocid=OCIDFactory.new(OCIDKind.ASSERTION),
        )


def test_governance_decision_requires_unique_policy_references() -> None:
    policy_ocid = OCIDFactory.new(OCIDKind.KNOWLEDGE_OBJECT)
    with pytest.raises(ScientificObjectValidationError, match="must be unique"):
        GovernanceDecision(
            effect=PolicyEffect.DENY,
            policy_ocids=(policy_ocid, policy_ocid),
            reasons=("Duplicate policy reference",),
        )
