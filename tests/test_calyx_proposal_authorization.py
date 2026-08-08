from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.calyx_orchestrator.executor import canonical_checksum
from app.calyx_orchestrator.proposal_authorization import (
    ProposalAuthorizationBuilder,
    ProposalAuthorizationRegistry,
    ProposalDecision,
)
from app.calyx_orchestrator.sandbox_supervisor_evidence import canonical_sha256

REPOSITORY = "jsp1440/orchid-calyx-backend"
BASE_COMMIT = "a" * 40
PATCH_EXECUTOR = "isolated_workspace_patcher_v1"


def _patch_output() -> dict:
    return {
        "status": "delivered",
        "executed": True,
        "mode": "authoritative_isolated_workspace_patch",
        "repository": REPOSITORY,
        "branch": "autonomy/work-123",
        "checkout_commit_sha": BASE_COMMIT,
        "workspace_isolated": True,
        "workspace_disposable": True,
        "changes": [
            {
                "path": "app/example.py",
                "before_sha256": "b" * 64,
                "after_sha256": "c" * 64,
                "created": False,
                "size_bytes": 100,
            }
        ],
        "file_count": 1,
        "total_written_bytes": 100,
        "commit_created": False,
        "validation_commands_run": False,
        "side_effects": ["isolated_workspace_files_modified"],
    }


def _patch_receipt() -> dict:
    output = _patch_output()
    return {
        "executor_key": PATCH_EXECUTOR,
        "state": "delivered",
        "outcome": "delivered",
        "output": output,
        "output_checksum": canonical_checksum(output),
    }


def _manifest(*, proposed_branch: str = "autonomy/proposal/work-123") -> dict:
    output = _patch_output()
    payload = {
        "schema": "calyx-git-proposal-manifest-v1",
        "repository": REPOSITORY,
        "base_commit_sha": BASE_COMMIT,
        "source_autonomy_branch": "autonomy/work-123",
        "proposed_branch": proposed_branch,
        "patch_output_checksum": canonical_checksum(output),
        "changes": [
            {
                "path": "app/example.py",
                "before_sha256": "b" * 64,
                "after_sha256": "c" * 64,
                "created": False,
                "size_bytes": 100,
            }
        ],
        "validations": [],
        "commit_title": "Bounded change",
        "pr_title": "Bounded change",
        "summary": "Proposal evidence.",
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


def _build(
    *,
    manifest: dict | None = None,
    patch_receipt: dict | None = None,
    requested_by: str = "principal:requester",
    review_class: str = "security",
    reviewer_id: str = "principal:security-reviewer",
    reviewer_roles: tuple[str, ...] = ("security",),
    decision: ProposalDecision = ProposalDecision.APPROVED,
):
    return ProposalAuthorizationBuilder().build(
        manifest_snapshot=_manifest() if manifest is None else manifest,
        patch_receipt=_patch_receipt() if patch_receipt is None else patch_receipt,
        requested_by=requested_by,
        review_class=review_class,
        reviewer_id=reviewer_id,
        reviewer_roles=reviewer_roles,
        decision=decision,
        rationale="Reviewed exact proposal evidence.",
        evidence_uris=("review:ticket-123",),
        decided_at=datetime(2026, 8, 8, 22, 0, tzinfo=timezone.utc),
    )


def test_record_is_deterministic_and_grants_no_mutation_authority() -> None:
    first = _build()
    second = _build()
    assert first.authorization_digest == second.authorization_digest
    snapshot = first.snapshot()
    assert snapshot["decision"] == "approved"
    assert snapshot["producer_id"] == f"executor:{PATCH_EXECUTOR}"
    assert snapshot["git_mutation_authorized"] is False
    assert snapshot["commit_authorized"] is False
    assert snapshot["push_authorized"] is False
    assert snapshot["pull_request_creation_authorized"] is False
    assert snapshot["automatic_merge_authorized"] is False
    assert snapshot["deployment_authorized"] is False
    assert snapshot["publication_authorized"] is False
    assert snapshot["taxonomy_activation_authorized"] is False
    assert snapshot["production_database_mutation_authorized"] is False
    assert snapshot["production_graph_mutation_authorized"] is False


def test_manifest_digest_tampering_is_rejected() -> None:
    manifest = _manifest()
    manifest["summary"] = "tampered"
    with pytest.raises(PermissionError, match="MANIFEST_DIGEST_MISMATCH"):
        _build(manifest=manifest)


def test_patch_receipt_checksum_must_match_manifest() -> None:
    receipt = _patch_receipt()
    receipt["output"]["total_written_bytes"] = 101
    with pytest.raises(PermissionError, match="PATCH_CHECKSUM_MISMATCH"):
        _build(patch_receipt=receipt)


def test_patch_receipt_identity_must_match_manifest() -> None:
    receipt = _patch_receipt()
    receipt["output"]["repository"] = "other/repository"
    receipt["output_checksum"] = canonical_checksum(receipt["output"])
    manifest = _manifest()
    manifest["patch_output_checksum"] = receipt["output_checksum"]
    payload = dict(manifest)
    payload.pop("manifest_digest")
    manifest["manifest_digest"] = canonical_sha256(payload)
    with pytest.raises(PermissionError, match="PATCH_IDENTITY_MISMATCH"):
        _build(manifest=manifest, patch_receipt=receipt)


def test_only_authoritative_isolated_patch_executor_is_accepted() -> None:
    receipt = _patch_receipt()
    receipt["executor_key"] = "caller-supplied-executor"
    with pytest.raises(PermissionError, match="PATCH_EXECUTOR_INVALID"):
        _build(patch_receipt=receipt)


def test_reviewer_cannot_self_approve_requester() -> None:
    with pytest.raises(PermissionError, match="SELF_APPROVAL_PROHIBITED"):
        _build(
            requested_by="principal:security-reviewer",
            reviewer_id="principal:security-reviewer",
        )


def test_reviewer_cannot_self_approve_patch_producer() -> None:
    with pytest.raises(PermissionError, match="SELF_APPROVAL_PROHIBITED"):
        _build(reviewer_id=f"executor:{PATCH_EXECUTOR}")


def test_reviewer_must_hold_requested_review_role() -> None:
    with pytest.raises(PermissionError, match="REVIEWER_ROLE_REQUIRED"):
        _build(reviewer_roles=("operational",))


def test_old_record_does_not_authorize_changed_manifest_digest() -> None:
    record = _build()
    changed = _manifest(proposed_branch="autonomy/proposal/work-124")
    with pytest.raises(PermissionError, match="STALE_MANIFEST"):
        record.verify_for_manifest(changed)


def test_rejection_is_immutable_for_manifest_and_review_class() -> None:
    registry = ProposalAuthorizationRegistry()
    rejected = _build(decision=ProposalDecision.REJECTED)
    registry.record(rejected)
    approved = _build(decision=ProposalDecision.APPROVED)
    with pytest.raises(ValueError, match="AUTHORITATIVE_DECISION_ALREADY_RECORDED"):
        registry.record(approved)
    assert registry.require(
        manifest_digest=rejected.manifest_digest,
        review_class=rejected.review_class,
    ).decision == ProposalDecision.REJECTED


def test_review_class_is_limited_to_governed_repository_classes() -> None:
    with pytest.raises(PermissionError, match="REVIEW_CLASS_NOT_ALLOWED"):
        _build(review_class="scientific", reviewer_roles=("scientific",))


def test_evidence_and_timezone_are_required() -> None:
    builder = ProposalAuthorizationBuilder()
    with pytest.raises(ValueError, match="EVIDENCE_INVALID"):
        builder.build(
            manifest_snapshot=_manifest(),
            patch_receipt=_patch_receipt(),
            requested_by="principal:requester",
            review_class="security",
            reviewer_id="principal:security-reviewer",
            reviewer_roles=("security",),
            decision="approved",
            rationale="Reviewed exact proposal evidence.",
            evidence_uris=(),
            decided_at=datetime(2026, 8, 8, 22, 0, tzinfo=timezone.utc),
        )
    with pytest.raises(ValueError, match="TIMEZONE_REQUIRED"):
        builder.build(
            manifest_snapshot=_manifest(),
            patch_receipt=_patch_receipt(),
            requested_by="principal:requester",
            review_class="security",
            reviewer_id="principal:security-reviewer",
            reviewer_roles=("security",),
            decision="approved",
            rationale="Reviewed exact proposal evidence.",
            evidence_uris=("review:ticket-123",),
            decided_at=datetime(2026, 8, 8, 22, 0),
        )
