from __future__ import annotations

import pytest

from app.calyx_orchestrator.artifact_registry import (
    ArtifactRegistration,
    ImmutableArtifactRegistry,
)
from app.calyx_orchestrator.brain_capture import (
    BrainCandidateRecord,
    BrainCandidateStore,
    BrainCaptureBundle,
    BrainRecordType,
)
from app.calyx_orchestrator.review_eligibility import (
    ReviewClass,
    ReviewDecision,
    ReviewDecisionState,
    ReviewRegistry,
    ReviewRequest,
)


def prepared():
    artifacts = ImmutableArtifactRegistry()
    artifact = artifacts.register(
        ArtifactRegistration(
            artifact_id="artifact-1",
            content=b"reviewed evidence",
            media_type="application/json",
            source_uri="github:artifact/1",
            producer_assignment_id="assignment-1",
            evidence_uris=("github:issue/442",),
        )
    ).record
    reviews = ReviewRegistry()
    reviews.request(
        ReviewRequest(
            request_id="review-1",
            artifact_id=artifact.artifact_id,
            requested_by="owner",
            producer_id="producer",
            required_classes=(ReviewClass.OPERATIONAL,),
        )
    )
    return artifacts, reviews, artifact


def approve(reviews: ReviewRegistry) -> None:
    reviews.decide(
        ReviewDecision(
            decision_id="decision-1",
            request_id="review-1",
            review_class=ReviewClass.OPERATIONAL,
            reviewer_id="operator-reviewer",
            reviewer_roles=("operational",),
            state=ReviewDecisionState.APPROVED,
            rationale="Evidence and operational boundaries verified.",
        )
    )


def bundle(checksum: str, *, bundle_id: str = "bundle-1", payload=None) -> BrainCaptureBundle:
    return BrainCaptureBundle(
        bundle_id=bundle_id,
        review_request_id="review-1",
        records=(
            BrainCandidateRecord(
                record_id="record-1",
                record_type=BrainRecordType.BUILD,
                source_artifact_id="artifact-1",
                source_path="docs/brain/build.md",
                source_checksum=checksum,
                payload=payload or {"outcome": "DELIVERED", "candidate": True},
            ),
        ),
    )


def test_capture_requires_eligible_review_and_is_repeatable():
    artifacts, reviews, artifact = prepared()
    store = BrainCandidateStore()
    with pytest.raises(PermissionError, match="CAPTURE_REVIEW_NOT_ELIGIBLE"):
        store.capture(bundle(artifact.checksum), artifacts=artifacts, reviews=reviews)
    approve(reviews)
    first = store.capture(bundle(artifact.checksum), artifacts=artifacts, reviews=reviews)
    replay = store.capture(bundle(artifact.checksum), artifacts=artifacts, reviews=reviews)
    assert first == replay
    assert store.status()["bundle_count"] == 1
    assert store.status()["bundles"][0]["published"] is False


def test_capture_is_atomic_on_checksum_failure():
    artifacts, reviews, _ = prepared()
    approve(reviews)
    store = BrainCandidateStore()
    with pytest.raises(ValueError, match="CAPTURE_SOURCE_CHECKSUM_MISMATCH"):
        store.capture(bundle("wrong"), artifacts=artifacts, reviews=reviews)
    assert store.status()["bundle_count"] == 0
    assert store.status()["record_count"] == 0


def test_conflicting_record_and_bundle_replays_are_rejected():
    artifacts, reviews, artifact = prepared()
    approve(reviews)
    store = BrainCandidateStore()
    store.capture(bundle(artifact.checksum), artifacts=artifacts, reviews=reviews)
    with pytest.raises(ValueError, match="IMMUTABLE_CAPTURE_BUNDLE_CONFLICT"):
        store.capture(
            bundle(artifact.checksum, payload={"outcome": "BLOCKED"}),
            artifacts=artifacts,
            reviews=reviews,
        )


def test_rollback_removes_bundle_and_unshared_records():
    artifacts, reviews, artifact = prepared()
    approve(reviews)
    store = BrainCandidateStore()
    captured = store.capture(bundle(artifact.checksum), artifacts=artifacts, reviews=reviews)
    assert store.rollback(captured.bundle_id) == captured
    assert store.status()["bundle_count"] == 0
    assert store.status()["record_count"] == 0
    with pytest.raises(LookupError, match="CAPTURE_BUNDLE_NOT_FOUND"):
        store.rollback(captured.bundle_id)
