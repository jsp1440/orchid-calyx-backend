from datetime import datetime, timezone

import pytest

from app.mission_control_access import (
    AuthenticatedIdentity,
    CapabilityService,
    MissionControlRole,
    PrincipalResolutionError,
    PrincipalResolver,
)
from app.review_tasks import (
    GovernedReviewTaskService,
    ReviewDecisionInput,
    ReviewDecisionType,
    ReviewTaskError,
    ReviewTaskInput,
)


def review_task():
    return ReviewTaskInput(
        orchestration_id="orch-001c",
        review_type="EXPERT_REVIEW_REQUIRED",
        risk_class="LEVEL_3_CONFLICTING_OR_AMBIGUOUS",
        routing_outcome="EXPERT_REVIEW_REQUIRED",
        required_capability="review.expert",
    )


def test_anonymous_identity_resolves_to_public_only():
    principal = PrincipalResolver().resolve(None)
    assert principal.principal_id == "anonymous"
    assert principal.authenticated is False
    assert principal.roles == (MissionControlRole.PUBLIC,)
    assert CapabilityService().evaluate(principal, "mission_control.view.public").allowed
    assert not CapabilityService().evaluate(principal, "review.expert").allowed


def test_authenticated_identity_requires_subject():
    with pytest.raises(PrincipalResolutionError) as error:
        PrincipalResolver().resolve(AuthenticatedIdentity(subject_id=None, authenticated=True))
    assert error.value.code == "AUTHENTICATED_SUBJECT_REQUIRED"


def test_unknown_role_is_rejected():
    identity = AuthenticatedIdentity(
        subject_id="user-1",
        authenticated=True,
        role_names=("SUPERUSER",),
    )
    with pytest.raises(PrincipalResolutionError) as error:
        PrincipalResolver().resolve(identity)
    assert error.value.code == "UNKNOWN_ROLE"


def test_expired_qualification_does_not_grant_scientific_authority():
    identity = AuthenticatedIdentity(
        subject_id="expert-1",
        authenticated=True,
        role_names=("EXPERT",),
        qualifications=("qualified.expert-reviewer",),
        qualification_expires_at={"qualified.expert-reviewer": "2025-01-01T00:00:00Z"},
    )
    principal = PrincipalResolver().resolve(
        identity,
        at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert principal.qualifications == ()
    assert not CapabilityService().evaluate(principal, "review.expert").allowed


def test_active_qualification_grants_expert_review():
    identity = AuthenticatedIdentity(
        subject_id="expert-1",
        authenticated=True,
        role_names=("EXPERT",),
        qualifications=("qualified.expert-reviewer",),
        qualification_expires_at={"qualified.expert-reviewer": "2027-01-01T00:00:00Z"},
    )
    principal = PrincipalResolver().resolve(
        identity,
        at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    assert CapabilityService().evaluate(principal, "review.expert").allowed


def test_administrator_without_scientific_qualification_cannot_review():
    principal = PrincipalResolver().resolve(
        AuthenticatedIdentity(
            subject_id="admin-1",
            authenticated=True,
            role_names=("ADMINISTRATOR",),
        )
    )
    assert CapabilityService().evaluate(principal, "mission_control.view.operations").allowed
    assert not CapabilityService().evaluate(principal, "review.expert").allowed


def test_review_task_queue_and_decision_use_resolved_principal():
    service = GovernedReviewTaskService()
    created = service.create(review_task())
    principal = PrincipalResolver().resolve(
        AuthenticatedIdentity(
            subject_id="expert-1",
            authenticated=True,
            role_names=("EXPERT",),
            qualifications=("qualified.expert-reviewer",),
        )
    )
    queue = service.queue_for_principal(principal)
    assert [item["task_id"] for item in queue] == [created["task_id"]]
    decided = service.decide_for_principal(
        created["task_id"],
        principal,
        ReviewDecisionInput(
            decision=ReviewDecisionType.ACCEPT,
            reviewer_id="expert-1",
            reviewer_capabilities=(),
        ),
    )
    assert decided["authoritative_decision"] == "ACCEPT"
    assert decided["decisions"][0]["provenance"]["authorization"]["allowed"] is True


def test_review_task_denial_uses_capability_reason_code():
    service = GovernedReviewTaskService()
    created = service.create(review_task())
    volunteer = PrincipalResolver().resolve(
        AuthenticatedIdentity(
            subject_id="volunteer-1",
            authenticated=True,
            role_names=("VOLUNTEER",),
            qualifications=("qualified.science-reviewer",),
        )
    )
    with pytest.raises(ReviewTaskError) as error:
        service.reserve_for_principal(created["task_id"], volunteer)
    assert error.value.code == "CAPABILITY_REQUIRED"


def test_decision_reviewer_must_match_principal():
    service = GovernedReviewTaskService()
    created = service.create(review_task())
    principal = PrincipalResolver().resolve(
        AuthenticatedIdentity(
            subject_id="expert-1",
            authenticated=True,
            qualifications=("qualified.expert-reviewer",),
        )
    )
    with pytest.raises(ReviewTaskError) as error:
        service.decide_for_principal(
            created["task_id"],
            principal,
            ReviewDecisionInput(
                decision=ReviewDecisionType.ACCEPT,
                reviewer_id="expert-2",
                reviewer_capabilities=(),
            ),
        )
    assert error.value.code == "PRINCIPAL_REVIEWER_MISMATCH"
