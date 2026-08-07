import pytest

from app.canonical_brain.build_queue import GovernedBuildQueue
from app.canonical_brain.constitution import BuildAdmissionRequest


def _request(build_id: str, **overrides: object) -> BuildAdmissionRequest:
    payload = {
        "build_id": build_id,
        "architecture_id": "architecture:brain",
        "intent_ids": ["intent:governed-operation"],
        "decision_ids": ["decision:brain"],
        "source_uris": ["docs/architecture/BUILD-BRAIN-106.md"],
        "validation_plan_ids": ["validation:brain-106"],
        "deterministic_outputs": True,
        "preserves_provenance": True,
        "separates_evidence_from_inference": True,
    }
    payload.update(overrides)
    return BuildAdmissionRequest(**payload)


def test_compliant_build_enters_admitted_queue() -> None:
    queue = GovernedBuildQueue()
    item = queue.submit(_request("BUILD-BRAIN-106"), priority=10)

    assert item.status == "admitted"
    assert item.admission.status == "admitted"
    assert queue.snapshot().runnable_count == 1


def test_prohibited_build_is_visible_but_not_runnable() -> None:
    queue = GovernedBuildQueue()
    item = queue.submit(_request("BUILD-BLOCKED", merge_requested=True))

    assert item.status == "blocked"
    assert queue.snapshot().blocked_count == 1
    assert queue.snapshot().runnable_count == 0


def test_queue_transitions_are_governed() -> None:
    queue = GovernedBuildQueue()
    queue.submit(_request("BUILD-TRANSITION"))

    assert queue.transition("BUILD-TRANSITION", "scheduled").status == "scheduled"
    assert queue.transition("BUILD-TRANSITION", "running").status == "running"
    assert queue.transition("BUILD-TRANSITION", "completed").status == "completed"

    with pytest.raises(ValueError):
        queue.transition("BUILD-TRANSITION", "running")


def test_blocked_build_cannot_be_scheduled() -> None:
    queue = GovernedBuildQueue()
    queue.submit(_request("BUILD-NO-SCHEDULE", deployment_requested=True))

    with pytest.raises(ValueError):
        queue.transition("BUILD-NO-SCHEDULE", "scheduled")


def test_duplicate_build_identity_is_idempotent_but_conflicts_fail() -> None:
    queue = GovernedBuildQueue()
    first = queue.submit(_request("BUILD-IDEMPOTENT"), priority=20)
    second = queue.submit(_request("BUILD-IDEMPOTENT"), priority=20)
    assert first == second

    with pytest.raises(ValueError):
        queue.submit(_request("BUILD-IDEMPOTENT", deterministic_outputs=False), priority=20)
