from __future__ import annotations

import pytest

from app.calyx_orchestrator.review_eligibility import (
    ReviewClass,
    ReviewDecision,
    ReviewDecisionState,
    ReviewRegistry,
    ReviewRequest,
)


def request() -> ReviewRequest:
    return ReviewRequest(
        request_id="review-1",
        artifact_id="artifact-1",
        requested_by="owner",
        producer_id="producer",
        required_classes=(ReviewClass.SCIENTIFIC, ReviewClass.LICENSING),
    )


def decision(
    decision_id: str,
    review_class: ReviewClass,
    reviewer_id: str,
    state: ReviewDecisionState = ReviewDecisionState.APPROVED,
) -> ReviewDecision:
    return ReviewDecision(
        decision_id=decision_id,
        request_id="review-1",
        review_class=review_class,
        reviewer_id=reviewer_id,
        reviewer_roles=(review_class.value,),
        state=state,
        rationale="Reviewed against the required evidence and policy.",
    )


def test_all_required_approvals_create_eligibility_only():
    registry = ReviewRegistry()
    registry.request(request())
    assert registry.eligibility("review-1").code == "REVIEWS_PENDING"
    registry.decide(decision("d1", ReviewClass.SCIENTIFIC, "scientist"))
    assert registry.eligibility("review-1").eligible is False
    registry.decide(decision("d2", ReviewClass.LICENSING, "licensing-reviewer"))
    result = registry.eligibility("review-1")
    assert result.eligible is True
    assert result.code == "RELEASE_ELIGIBLE"
    assert not hasattr(result, "published")
    assert not hasattr(result, "deployed")


def test_rejection_and_changes_requested_prevent_eligibility():
    registry = ReviewRegistry()
    registry.request(request())
    registry.decide(
        decision(
            "d1",
            ReviewClass.SCIENTIFIC,
            "scientist",
            ReviewDecisionState.CHANGES_REQUESTED,
        )
    )
    assert registry.eligibility("review-1").code == "CHANGES_REQUESTED"


def test_self_approval_and_missing_role_are_rejected():
    registry = ReviewRegistry()
    registry.request(request())
    with pytest.raises(PermissionError, match="SELF_APPROVAL_PROHIBITED"):
        registry.decide(decision("d1", ReviewClass.SCIENTIFIC, "producer"))
    invalid_role = ReviewDecision(
        decision_id="d2",
        request_id="review-1",
        review_class=ReviewClass.SCIENTIFIC,
        reviewer_id="reviewer",
        reviewer_roles=("operational",),
        state=ReviewDecisionState.APPROVED,
        rationale="Reviewed.",
    )
    with pytest.raises(PermissionError, match="REVIEWER_ROLE_REQUIRED"):
        registry.decide(invalid_role)


def test_decisions_are_immutable_and_one_authoritative_decision_per_class():
    registry = ReviewRegistry()
    registry.request(request())
    first = decision("d1", ReviewClass.SCIENTIFIC, "scientist")
    assert registry.decide(first) == first
    assert registry.decide(first) == first
    with pytest.raises(ValueError, match="AUTHORITATIVE_REVIEW_ALREADY_RECORDED"):
        registry.decide(
            decision(
                "d2",
                ReviewClass.SCIENTIFIC,
                "other-scientist",
                ReviewDecisionState.REJECTED,
            )
        )


def test_mission_control_queue_is_deterministic_and_actionable():
    registry = ReviewRegistry()
    registry.request(request())
    queue = registry.mission_control_queue()
    assert queue[0]["request_id"] == "review-1"
    assert queue[0]["pending_classes"] == ["licensing", "scientific"]
    assert queue[0]["eligible"] is False
