from datetime import datetime, timezone

import pytest
from app.calyx_orchestrator.brain_capture import BrainCandidateStore

from app.calyx_orchestrator.artifact_registry import ImmutableArtifactRegistry
from app.calyx_orchestrator.review_eligibility import (
    ReviewClass,
    ReviewDecision,
    ReviewDecisionState,
    ReviewRegistry,
)
from app.canonical_brain.evidence_bridge import build_execution_evidence_package
from app.canonical_brain.orchestration import ExecutionReceipt


def receipt(outcome: str = "completed") -> ExecutionReceipt:
    return ExecutionReceipt(
        receipt_id="r" * 64,
        assignment_id="a" * 64,
        build_id="BUILD-BRAIN-TEST",
        agent_id="agent:brain-engineer",
        outcome=outcome,
        recorded_at=datetime(2026, 8, 7, tzinfo=timezone.utc),
        evidence_uris=["github://commit/example", "ci://run/example"],
        output_checksum="b" * 64 if outcome == "completed" else None,
    )


def test_completed_receipt_builds_deterministic_existing_contracts() -> None:
    first = build_execution_evidence_package(
        receipt(),
        requested_by="operator:mission-control",
        producer_id="agent:brain-engineer",
        required_review_classes=(ReviewClass.OPERATIONAL, ReviewClass.SECURITY),
    )
    second = build_execution_evidence_package(
        receipt(),
        requested_by="operator:mission-control",
        producer_id="agent:brain-engineer",
        required_review_classes=(ReviewClass.OPERATIONAL, ReviewClass.SECURITY),
    )

    assert first == second
    assert first.artifact.producer_assignment_id == "a" * 64
    assert first.artifact.metadata["published"] is False
    assert first.capture.records[0].source_checksum == first.artifact.checksum
    assert first.capture.records[0].payload["candidate_only"] is True


def test_started_or_incomplete_receipts_fail_closed() -> None:
    with pytest.raises(ValueError, match="ONLY_COMPLETED_RECEIPTS"):
        build_execution_evidence_package(
            receipt("started"),
            requested_by="operator:mission-control",
            producer_id="agent:brain-engineer",
        )

    incomplete = receipt().model_copy(update={"evidence_uris": []})
    with pytest.raises(ValueError, match="EVIDENCE_URI_REQUIRED"):
        build_execution_evidence_package(
            incomplete,
            requested_by="operator:mission-control",
            producer_id="agent:brain-engineer",
        )


def test_self_request_and_duplicate_review_classes_fail_closed() -> None:
    with pytest.raises(PermissionError, match="SELF_REQUEST"):
        build_execution_evidence_package(
            receipt(),
            requested_by="agent:brain-engineer",
            producer_id="agent:brain-engineer",
        )

    with pytest.raises(ValueError, match="DUPLICATE_EXECUTION_REVIEW_CLASS"):
        build_execution_evidence_package(
            receipt(),
            requested_by="operator:mission-control",
            producer_id="agent:brain-engineer",
            required_review_classes=(ReviewClass.OPERATIONAL, ReviewClass.OPERATIONAL),
        )


def test_existing_review_and_capture_gates_are_authoritative() -> None:
    package = build_execution_evidence_package(
        receipt(),
        requested_by="operator:mission-control",
        producer_id="agent:brain-engineer",
        required_review_classes=(ReviewClass.OPERATIONAL,),
    )
    artifacts = ImmutableArtifactRegistry()
    reviews = ReviewRegistry()
    store = BrainCandidateStore()

    artifacts.register(package.artifact)
    reviews.request(package.review)

    with pytest.raises(PermissionError, match="CAPTURE_REVIEW_NOT_ELIGIBLE"):
        store.capture(package.capture, artifacts=artifacts, reviews=reviews)

    reviews.decide(
        ReviewDecision(
            decision_id="decision:operational-review",
            request_id=package.review.request_id,
            review_class=ReviewClass.OPERATIONAL,
            reviewer_id="reviewer:ops",
            reviewer_roles=("operational",),
            state=ReviewDecisionState.APPROVED,
            rationale="Execution evidence is complete and internally consistent.",
        )
    )
    captured = store.capture(package.capture, artifacts=artifacts, reviews=reviews)
    assert captured == package.capture
    assert store.status()["bundles"][0]["published"] is False
