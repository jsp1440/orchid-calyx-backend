import pytest

from app.review_tasks import (
    GovernedReviewTaskService,
    ReviewDecisionInput,
    ReviewDecisionType,
    ReviewTaskError,
    ReviewTaskInput,
)


def task(**overrides):
    data = {
        "orchestration_id": "orch-1",
        "review_type": "EXPERT_REVIEW_REQUIRED",
        "risk_class": "LEVEL_3_CONFLICTING_OR_AMBIGUOUS",
        "routing_outcome": "EXPERT_REVIEW_REQUIRED",
        "required_capability": "review.expert",
        "candidate_ids": (3, 1),
        "aggregate_version_ids": ("agg-b", "agg-a"),
        "priority": 80,
        "scientific_impact_score": 0.8,
    }
    data.update(overrides)
    return ReviewTaskInput(**data)


def test_deterministic_creation_and_replay():
    service = GovernedReviewTaskService()
    first = service.create(task())
    second = service.create(task())
    assert first["task_id"] == second["task_id"]
    assert second["reused"] is True
    assert first["candidate_ids"] == [1, 3]
    assert first["aggregate_version_ids"] == ["agg-a", "agg-b"]
    assert [event["event_type"] for event in second["history"]] == ["TASK_CREATED"]


def test_orchestration_routing_creates_review_task_but_provisional_does_not():
    service = GovernedReviewTaskService()
    provisional = {
        "orchestration_id": "p",
        "routing_outcome": "PROVISIONAL_KNOWLEDGE",
        "risk_class": "LEVEL_1_ROUTINE_SCIENTIFIC",
    }
    assert service.create_from_orchestration(provisional) is None
    routed = {
        "orchestration_id": "x",
        "routing_outcome": "EXPERT_REVIEW_REQUIRED",
        "risk_class": "LEVEL_4_HIGH_IMPACT",
        "candidate_ids": [9],
        "downstream": {"aggregate_version_ids": ["agg-9"]},
        "policy_version": "risk-1",
    }
    created = service.create_from_orchestration(routed)
    assert created["required_capability"] == "review.expert"
    assert created["priority"] == 90


def test_capability_enforced_for_queue_reservation_and_decision():
    service = GovernedReviewTaskService()
    created = service.create(task())
    assert service.queue(("review.science",)) == []
    assert [item["task_id"] for item in service.queue(("review.expert",))] == [created["task_id"]]
    with pytest.raises(ReviewTaskError) as denied:
        service.reserve(created["task_id"], "volunteer-1", ("review.science",))
    assert denied.value.code == "CAPABILITY_REQUIRED"
    reserved = service.reserve(created["task_id"], "expert-1", ("review.expert",))
    assert reserved["assigned_to"] == "expert-1"


def test_decisions_are_audited_and_rejection_is_authoritative():
    service = GovernedReviewTaskService()
    created = service.create(task())
    decided = service.decide(
        created["task_id"],
        ReviewDecisionInput(
            decision=ReviewDecisionType.REJECT,
            reviewer_id="expert-1",
            reviewer_capabilities=("review.expert",),
            comment="Evidence conflict is material",
            provenance={"method": "native-workbench"},
        ),
    )
    assert decided["state"] == "DECIDED"
    assert decided["authoritative_decision"] == "REJECT"
    assert decided["decisions"][0]["provenance"]["method"] == "native-workbench"
    assert [event["event_type"] for event in decided["history"]] == [
        "TASK_CREATED",
        "DECISION_RECORDED",
    ]
    with pytest.raises(ReviewTaskError) as locked:
        service.decide(
            created["task_id"],
            ReviewDecisionInput(
                decision=ReviewDecisionType.ACCEPT,
                reviewer_id="expert-2",
                reviewer_capabilities=("review.expert",),
            ),
        )
    assert locked.value.code == "AUTHORITATIVE_DECISION_LOCKED"


def test_consensus_requirement_and_escalation():
    service = GovernedReviewTaskService()
    created = service.create(task(consensus_required=2))
    first = service.decide(
        created["task_id"],
        ReviewDecisionInput(
            decision=ReviewDecisionType.ACCEPT,
            reviewer_id="expert-1",
            reviewer_capabilities=("review.expert",),
        ),
    )
    assert first["state"] == "IN_REVIEW"
    second = service.decide(
        created["task_id"],
        ReviewDecisionInput(
            decision=ReviewDecisionType.ACCEPT,
            reviewer_id="expert-2",
            reviewer_capabilities=("review.expert",),
        ),
    )
    assert second["state"] == "DECIDED"

    escalated_task = service.create(task(orchestration_id="orch-2"))
    escalated = service.decide(
        escalated_task["task_id"],
        ReviewDecisionInput(
            decision=ReviewDecisionType.ESCALATE,
            reviewer_id="expert-1",
            reviewer_capabilities=("review.expert",),
        ),
    )
    assert escalated["state"] == "ESCALATED"
    assert escalated["authoritative_decision"] == "ESCALATE"


def test_invalid_policy_inputs_block_creation():
    service = GovernedReviewTaskService()
    with pytest.raises(ReviewTaskError) as bad_priority:
        service.create(task(priority=101))
    assert bad_priority.value.code == "INVALID_PRIORITY"
    with pytest.raises(ReviewTaskError) as not_reviewable:
        service.create(task(routing_outcome="PROVISIONAL_KNOWLEDGE"))
    assert not_reviewable.value.code == "ROUTING_NOT_REVIEWABLE"
