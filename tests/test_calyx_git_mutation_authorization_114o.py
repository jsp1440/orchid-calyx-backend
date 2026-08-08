from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.calyx_orchestrator.git_mutation_authorization import (
    GitMutationAuthorizationGate,
)
from app.calyx_orchestrator.proposal_authorization import (
    ProposalAuthorizationRecord,
    ProposalDecision,
)
from app.calyx_orchestrator.sandbox_supervisor_evidence import canonical_sha256

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
GIT_SHA = "1" * 40
NOW = datetime(2026, 8, 8, 22, 0, tzinfo=timezone.utc)


def manifest() -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "calyx-git-proposal-manifest-v1",
        "repository": "jsp1440/orchid-calyx-backend",
        "base_commit_sha": GIT_SHA,
        "source_autonomy_branch": "autonomy/work/123",
        "proposed_branch": "autonomy/proposal/123",
        "patch_output_checksum": SHA_A,
        "changes": [
            {
                "path": "app/example.py",
                "before_sha256": SHA_B,
                "after_sha256": SHA_C,
                "created": False,
                "size_bytes": 12,
            }
        ],
        "validations": [
            {
                "preset": "ruff",
                "request_digest": SHA_A,
                "receipt_digest": SHA_B,
                "policy_digest": SHA_C,
                "targets": [{"path": "app/example.py", "sha256": SHA_C}],
            }
        ],
        "commit_title": "test proposal",
        "pr_title": "test proposal",
        "summary": "bounded proposal",
        "git_mutation_performed": False,
        "commit_created": False,
        "push_performed": False,
        "pull_request_created": False,
        "automatic_merge_authorized": False,
        "deployment_authorized": False,
        "publication_authorized": False,
        "production_database_mutation_authorized": False,
        "production_graph_mutation_authorized": False,
    }
    return {**payload, "manifest_digest": canonical_sha256(payload)}


def review(review_class: str, reviewer: str) -> ProposalAuthorizationRecord:
    snapshot = manifest()
    record = ProposalAuthorizationRecord(
        manifest_digest=str(snapshot["manifest_digest"]),
        repository=str(snapshot["repository"]),
        base_commit_sha=str(snapshot["base_commit_sha"]),
        source_autonomy_branch=str(snapshot["source_autonomy_branch"]),
        proposed_branch=str(snapshot["proposed_branch"]),
        patch_output_checksum=str(snapshot["patch_output_checksum"]),
        producer_id="executor:isolated_workspace_patcher_v1",
        requested_by="autonomy-worker-1",
        review_class=review_class,
        reviewer_id=reviewer,
        reviewer_roles=(review_class,),
        decision=ProposalDecision.APPROVED,
        rationale="reviewed exact manifest evidence",
        evidence_uris=(f"brain://review/{review_class}",),
        decided_at=NOW.isoformat(),
    )
    record.verify_for_manifest(snapshot)
    return record


def gate() -> GitMutationAuthorizationGate:
    return GitMutationAuthorizationGate(
        owner_principal="owner:jsp1440",
        hmac_secret=b"x" * 32,
    )


def test_request_requires_security_and_operational_reviews() -> None:
    with pytest.raises(PermissionError, match="REQUIRED_REVIEWS_MISSING"):
        gate().build_request(
            manifest(),
            review_authorizations=(review("security", "security-reviewer"),),
            actions=("create_branch", "create_commit", "push_branch", "open_pull_request"),
            expires_at=(NOW + timedelta(minutes=10)).isoformat(),
            now=NOW,
        )


def test_request_requires_separate_reviewers() -> None:
    with pytest.raises(PermissionError, match="REVIEWER_SEPARATION_REQUIRED"):
        gate().build_request(
            manifest(),
            review_authorizations=(
                review("security", "same-reviewer"),
                review("operational", "same-reviewer"),
            ),
            actions=("create_branch",),
            expires_at=(NOW + timedelta(minutes=10)).isoformat(),
            now=NOW,
        )


def test_request_binds_review_digests_and_forbids_merge_authority() -> None:
    security = review("security", "security-reviewer")
    operational = review("operational", "operations-reviewer")
    request = gate().build_request(
        manifest(),
        review_authorizations=(security, operational),
        actions=("create_branch", "create_commit", "push_branch", "open_pull_request"),
        expires_at=(NOW + timedelta(minutes=10)).isoformat(),
        now=NOW,
    )
    assert request.review_authorization_digests == (
        operational.authorization_digest,
        security.authorization_digest,
    )
    assert request.snapshot()["merge_authorized"] is False
    with pytest.raises(PermissionError, match="ACTION_NOT_ALLOWED"):
        gate().build_request(
            manifest(),
            review_authorizations=(security, operational),
            actions=("merge_pull_request",),
            expires_at=(NOW + timedelta(minutes=10)).isoformat(),
            now=NOW,
        )


def test_owner_grant_is_request_bound_and_expires() -> None:
    request = gate().build_request(
        manifest(),
        review_authorizations=(
            review("security", "security-reviewer"),
            review("operational", "operations-reviewer"),
        ),
        actions=("create_branch", "open_pull_request"),
        expires_at=(NOW + timedelta(minutes=10)).isoformat(),
        now=NOW,
    )
    approval = gate().sign_for_test_or_operator(
        request_digest=request.request_digest,
        decision="approved",
        issued_at=NOW.isoformat(),
        expires_at=request.expires_at,
    )
    verified = gate().verify_grant(request, approval, now=NOW + timedelta(minutes=1))
    assert verified.decision == "approved"
    with pytest.raises(PermissionError, match="EXPIRED_OR_INVALID"):
        gate().verify_grant(request, approval, now=NOW + timedelta(minutes=11))
