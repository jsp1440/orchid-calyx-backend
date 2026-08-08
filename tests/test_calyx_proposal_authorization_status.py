from __future__ import annotations

from datetime import datetime, timezone

from app.calyx_orchestrator.executor import canonical_checksum
from app.calyx_orchestrator.proposal_authorization import (
    ProposalAuthorizationBuilder,
    ProposalAuthorizationRegistry,
    ProposalDecision,
)
from app.calyx_orchestrator.proposal_authorization_status import proposal_review_status
from app.calyx_orchestrator.sandbox_supervisor_evidence import canonical_sha256

REPOSITORY = "jsp1440/orchid-calyx-backend"
BASE_COMMIT = "a" * 40


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
        "executor_key": "isolated_workspace_patcher_v1",
        "state": "delivered",
        "outcome": "delivered",
        "output": output,
        "output_checksum": canonical_checksum(output),
    }


def _manifest() -> dict:
    payload = {
        "schema": "calyx-git-proposal-manifest-v1",
        "repository": REPOSITORY,
        "base_commit_sha": BASE_COMMIT,
        "source_autonomy_branch": "autonomy/work-123",
        "proposed_branch": "autonomy/proposal/work-123",
        "patch_output_checksum": canonical_checksum(_patch_output()),
        "changes": [],
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


def _record(
    review_class: str,
    decision: ProposalDecision,
    *,
    reviewer_id: str | None = None,
):
    return ProposalAuthorizationBuilder().build(
        manifest_snapshot=_manifest(),
        patch_receipt=_patch_receipt(),
        requested_by="principal:requester",
        review_class=review_class,
        reviewer_id=reviewer_id or f"principal:{review_class}-reviewer",
        reviewer_roles=(review_class,),
        decision=decision,
        rationale="Reviewed exact proposal evidence.",
        evidence_uris=(f"review:{review_class}-ticket",),
        decided_at=datetime(2026, 8, 8, 22, 0, tzinfo=timezone.utc),
    )


def test_one_approval_remains_pending_and_non_authoritative() -> None:
    registry = ProposalAuthorizationRegistry()
    security = _record("security", ProposalDecision.APPROVED)
    registry.record(security)

    status = proposal_review_status(registry, manifest_digest=security.manifest_digest)
    assert status.review_evidence_complete is False
    assert status.code == "PROPOSAL_REVIEWS_PENDING"
    assert status.approved_classes == ("security",)
    assert status.pending_classes == ("operational",)
    assert status.reviewer_conflict is False
    assert status.git_mutation_authorized is False
    assert status.commit_authorized is False
    assert status.push_authorized is False
    assert status.pull_request_creation_authorized is False
    assert status.automatic_merge_authorized is False


def test_both_independent_classes_complete_review_evidence_only() -> None:
    registry = ProposalAuthorizationRegistry()
    security = _record("security", ProposalDecision.APPROVED)
    operational = _record("operational", ProposalDecision.APPROVED)
    registry.record(security)
    registry.record(operational)

    status = proposal_review_status(registry, manifest_digest=security.manifest_digest)
    assert status.review_evidence_complete is True
    assert status.code == "PROPOSAL_REVIEW_EVIDENCE_COMPLETE"
    assert status.approved_classes == ("operational", "security")
    assert status.pending_classes == ()
    assert status.rejected_classes == ()
    assert status.reviewer_conflict is False
    assert status.git_mutation_authorized is False


def test_same_reviewer_cannot_complete_both_required_classes() -> None:
    registry = ProposalAuthorizationRegistry()
    reviewer = "principal:dual-role-reviewer"
    security = _record(
        "security",
        ProposalDecision.APPROVED,
        reviewer_id=reviewer,
    )
    operational = _record(
        "operational",
        ProposalDecision.APPROVED,
        reviewer_id=reviewer,
    )
    registry.record(security)
    registry.record(operational)

    status = proposal_review_status(registry, manifest_digest=security.manifest_digest)
    assert status.review_evidence_complete is False
    assert status.code == "PROPOSAL_REVIEW_REVIEWER_CONFLICT"
    assert status.approved_classes == ("operational", "security")
    assert status.pending_classes == ()
    assert status.rejected_classes == ()
    assert status.reviewer_conflict is True
    assert status.git_mutation_authorized is False
    assert status.commit_authorized is False
    assert status.push_authorized is False
    assert status.pull_request_creation_authorized is False
    assert status.automatic_merge_authorized is False


def test_any_rejection_blocks_review_evidence_completion() -> None:
    registry = ProposalAuthorizationRegistry()
    security = _record("security", ProposalDecision.APPROVED)
    operational = _record("operational", ProposalDecision.REJECTED)
    registry.record(security)
    registry.record(operational)

    status = proposal_review_status(registry, manifest_digest=security.manifest_digest)
    assert status.review_evidence_complete is False
    assert status.code == "PROPOSAL_REVIEW_REJECTED"
    assert status.rejected_classes == ("operational",)
    assert status.reviewer_conflict is False
    assert status.git_mutation_authorized is False
