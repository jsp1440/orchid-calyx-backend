import pytest

from app.calyx_orchestrator.artifact_registry import ImmutableArtifactRegistry
from app.calyx_orchestrator.brain_capture import BrainCandidateStore
from app.calyx_orchestrator.executor import GovernedAssignment
from app.calyx_orchestrator.executor_registry import (
    AUTONOMY_PROBE_ROLE,
    AuthoritativeExecutorRegistry,
)
from app.calyx_orchestrator.review_eligibility import (
    ReviewClass,
    ReviewDecision,
    ReviewDecisionState,
    ReviewRegistry,
)
from app.canonical_brain.evidence_bridge import build_execution_evidence_package


def authoritative_execution():
    registry = AuthoritativeExecutorRegistry()
    registered = registry.require_authoritative(AUTONOMY_PROBE_ROLE)
    assignment = GovernedAssignment(
        assignment_id="a" * 64,
        program_id="program:brain-test",
        job_key="BUILD-BRAIN-TEST",
        role_key=AUTONOMY_PROBE_ROLE,
        objective="Verify authoritative execution evidence bridge",
        inputs={"job": {"mutating_intent": False}},
        evidence_uris=("github://commit/example", "ci://run/example"),
    )
    return registered.executor.execute(assignment)


def package(**overrides):
    values = {
        "executor_role_key": AUTONOMY_PROBE_ROLE,
        "requested_by": "operator:mission-control",
    }
    values.update(overrides)
    return build_execution_evidence_package(authoritative_execution(), **values)


def test_authoritative_receipt_builds_deterministic_existing_contracts() -> None:
    first = package(required_review_classes=(ReviewClass.OPERATIONAL, ReviewClass.SECURITY))
    second = package(required_review_classes=(ReviewClass.OPERATIONAL, ReviewClass.SECURITY))

    assert first == second
    assert first.artifact.producer_assignment_id == "a" * 64
    assert first.artifact.metadata["build_id"] == "BUILD-BRAIN-TEST"
    assert first.artifact.metadata["producer_id"] == "executor:autonomy_probe_v1"
    assert first.artifact.metadata["authoritative"] is True
    assert first.artifact.metadata["published"] is False
    assert first.review.producer_id == "executor:autonomy_probe_v1"
    assert first.capture.records[0].source_checksum == first.artifact.checksum
    assert first.capture.records[0].payload["build_id"] == "BUILD-BRAIN-TEST"
    assert first.capture.records[0].payload["authoritative"] is True
    assert first.capture.records[0].payload["candidate_only"] is True


def test_unregistered_executor_role_fails_closed() -> None:
    with pytest.raises(LookupError, match="AUTHORITATIVE_EXECUTOR_NOT_REGISTERED"):
        package(executor_role_key="brain_engineer")


def test_executor_identity_mismatch_fails_closed() -> None:
    receipt = authoritative_execution()
    mismatched = receipt.__class__(
        assignment_id=receipt.assignment_id,
        program_id=receipt.program_id,
        job_key=receipt.job_key,
        executor_key="different_executor_v1",
        state=receipt.state,
        outcome=receipt.outcome,
        input_checksum=receipt.input_checksum,
        output_checksum=receipt.output_checksum,
        output=receipt.output,
        evidence_uris=receipt.evidence_uris,
        blocker_code=receipt.blocker_code,
    )
    with pytest.raises(ValueError, match="EXECUTOR_MISMATCH"):
        build_execution_evidence_package(
            mismatched,
            executor_role_key=AUTONOMY_PROBE_ROLE,
            requested_by="operator:mission-control",
        )


def test_missing_evidence_fails_closed() -> None:
    receipt = authoritative_execution()
    empty_evidence = receipt.__class__(
        assignment_id=receipt.assignment_id,
        program_id=receipt.program_id,
        job_key=receipt.job_key,
        executor_key=receipt.executor_key,
        state=receipt.state,
        outcome=receipt.outcome,
        input_checksum=receipt.input_checksum,
        output_checksum=receipt.output_checksum,
        output=receipt.output,
        evidence_uris=(),
        blocker_code=receipt.blocker_code,
    )
    with pytest.raises(ValueError, match="EVIDENCE_URI_REQUIRED"):
        build_execution_evidence_package(
            empty_evidence,
            executor_role_key=AUTONOMY_PROBE_ROLE,
            requested_by="operator:mission-control",
        )


def test_self_request_and_duplicate_review_classes_fail_closed() -> None:
    with pytest.raises(PermissionError, match="SELF_REQUEST"):
        package(requested_by="executor:autonomy_probe_v1")

    with pytest.raises(ValueError, match="DUPLICATE_EXECUTION_REVIEW_CLASS"):
        package(required_review_classes=(ReviewClass.OPERATIONAL, ReviewClass.OPERATIONAL))


def test_existing_review_and_capture_gates_remain_authoritative() -> None:
    candidate = package(required_review_classes=(ReviewClass.OPERATIONAL,))
    artifacts = ImmutableArtifactRegistry()
    reviews = ReviewRegistry()
    store = BrainCandidateStore()

    artifacts.register(candidate.artifact)
    reviews.request(candidate.review)

    with pytest.raises(PermissionError, match="CAPTURE_REVIEW_NOT_ELIGIBLE"):
        store.capture(candidate.capture, artifacts=artifacts, reviews=reviews)

    reviews.decide(
        ReviewDecision(
            decision_id="decision:operational-review",
            request_id=candidate.review.request_id,
            review_class=ReviewClass.OPERATIONAL,
            reviewer_id="reviewer:ops",
            reviewer_roles=("operational",),
            state=ReviewDecisionState.APPROVED,
            rationale="Execution evidence is complete and internally consistent.",
        )
    )
    captured = store.capture(candidate.capture, artifacts=artifacts, reviews=reviews)
    assert captured == candidate.capture
    assert store.status()["bundles"][0]["published"] is False
