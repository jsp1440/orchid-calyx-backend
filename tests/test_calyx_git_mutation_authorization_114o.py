from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.calyx_orchestrator.executor import canonical_checksum
from app.calyx_orchestrator.git_mutation_authorization import (
    GRANT_SCHEMA,
    GitMutationAuthorizationGate,
)
from app.calyx_orchestrator.proposal_authorization import (
    ProposalAuthorizationBuilder,
    ProposalAuthorizationRegistry,
    ProposalDecision,
)
from app.calyx_orchestrator.sandbox_supervisor_evidence import canonical_sha256

REPOSITORY = "jsp1440/orchid-calyx-backend"
BASE_COMMIT = "a" * 40
PATCH_JOB_ID = "11111111-1111-1111-1111-111111111111"
NOW = datetime(2026, 8, 8, 22, 0, tzinfo=timezone.utc)
SECRET = b"s" * 32
OWNER = "principal:owner"


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


class _PersistedPatchService:
    def get_completed(self, *, program_job_id: str):
        if program_job_id != PATCH_JOB_ID:
            raise LookupError("PERSISTED_PATCH_EXECUTION_NOT_FOUND")
        output = _patch_output()
        return SimpleNamespace(
            program_job_id=PATCH_JOB_ID,
            repository=REPOSITORY,
            branch="autonomy/work-123",
            executor_key="isolated_workspace_patcher_v1",
            output_checksum=canonical_checksum(output),
            output=output,
        )


def _manifest() -> dict:
    output = _patch_output()
    payload = {
        "schema": "calyx-git-proposal-manifest-v2",
        "patch_program_job_id": PATCH_JOB_ID,
        "repository": REPOSITORY,
        "base_commit_sha": BASE_COMMIT,
        "source_autonomy_branch": "autonomy/work-123",
        "proposed_branch": "autonomy/proposal/work-123",
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
        "validations": [
            {
                "preset": "ruff",
                "request_digest": "d" * 64,
                "receipt_digest": "e" * 64,
                "policy_digest": "f" * 64,
                "target_hashes": [
                    {"path": "app/example.py", "sha256": "c" * 64}
                ],
            }
        ],
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


def _review(
    *,
    review_class: str,
    reviewer: str,
    decision: ProposalDecision = ProposalDecision.APPROVED,
):
    return ProposalAuthorizationBuilder(_PersistedPatchService()).build(
        manifest_snapshot=_manifest(),
        requested_by="principal:requester",
        review_class=review_class,
        reviewer_id=reviewer,
        reviewer_roles=(review_class,),
        decision=decision,
        rationale=f"{review_class} review complete.",
        evidence_uris=(f"review:{review_class}-ticket",),
        decided_at=NOW,
    )


def _registry(
    *, security_decision: ProposalDecision = ProposalDecision.APPROVED
) -> ProposalAuthorizationRegistry:
    registry = ProposalAuthorizationRegistry()
    registry.record(
        _review(
            review_class="operational",
            reviewer="principal:ops-reviewer",
        )
    )
    registry.record(
        _review(
            review_class="security",
            reviewer="principal:security-reviewer",
            decision=security_decision,
        )
    )
    return registry


def _request(registry: ProposalAuthorizationRegistry):
    return GitMutationAuthorizationGate.build_request(
        _manifest(),
        review_registry=registry,
        actions=(
            "create_branch",
            "create_commit",
            "push_branch",
            "open_pull_request",
        ),
        expires_at=(NOW + timedelta(minutes=15)).isoformat(),
        now=NOW,
    )


def _owner_grant(
    *, request_digest: str, decision: str, issued_at: str, expires_at: str
) -> dict[str, str]:
    unsigned = {
        "schema": GRANT_SCHEMA,
        "request_digest": request_digest,
        "decision": decision,
        "approved_by": OWNER,
        "issued_at": issued_at,
        "expires_at": expires_at,
    }
    signature = hmac.new(
        SECRET,
        canonical_sha256(unsigned).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    return {**unsigned, "signature": signature}


def test_request_requires_both_authoritative_registry_reviews() -> None:
    registry = ProposalAuthorizationRegistry()
    registry.record(
        _review(review_class="security", reviewer="principal:security-reviewer")
    )
    with pytest.raises(PermissionError, match="PROPOSAL_REVIEWS_PENDING"):
        _request(registry)


def test_rejected_review_blocks_request() -> None:
    registry = _registry(security_decision=ProposalDecision.REJECTED)
    with pytest.raises(PermissionError, match="PROPOSAL_REVIEW_REJECTED"):
        _request(registry)


def test_distinct_reviewers_are_required() -> None:
    registry = ProposalAuthorizationRegistry()
    registry.record(
        _review(review_class="operational", reviewer="principal:reviewer")
    )
    registry.record(_review(review_class="security", reviewer="principal:reviewer"))
    with pytest.raises(
        PermissionError,
        match="PROPOSAL_REVIEW_REVIEWER_CONFLICT|REVIEWER_SEPARATION_REQUIRED",
    ):
        _request(registry)


def test_unregistered_review_object_cannot_satisfy_gate() -> None:
    registry = ProposalAuthorizationRegistry()
    registry.record(
        _review(review_class="operational", reviewer="principal:ops-reviewer")
    )
    unregistered_security = _review(
        review_class="security",
        reviewer="principal:security-reviewer",
    )
    assert unregistered_security.decision is ProposalDecision.APPROVED
    with pytest.raises(PermissionError, match="PROPOSAL_REVIEWS_PENDING"):
        _request(registry)


def test_request_binds_patch_job_reviews_and_grants_no_merge_or_deploy_authority() -> None:
    request = _request(_registry())
    snapshot = request.snapshot()
    assert snapshot["patch_program_job_id"] == PATCH_JOB_ID
    assert len(snapshot["review_authorization_digests"]) == 2
    assert snapshot["merge_authorized"] is False
    assert snapshot["automatic_merge_authorized"] is False
    assert snapshot["deployment_authorized"] is False
    assert snapshot["publication_authorized"] is False
    assert snapshot["taxonomy_activation_authorized"] is False
    assert snapshot["production_database_mutation_authorized"] is False
    assert snapshot["production_graph_mutation_authorized"] is False


def test_merge_action_is_not_allowlisted() -> None:
    with pytest.raises(PermissionError, match="ACTION_NOT_ALLOWED"):
        GitMutationAuthorizationGate.build_request(
            _manifest(),
            review_registry=_registry(),
            actions=("merge_pull_request",),
            expires_at=(NOW + timedelta(minutes=15)).isoformat(),
            now=NOW,
        )


def test_exact_external_owner_grant_verifies_and_expired_grant_fails() -> None:
    gate = GitMutationAuthorizationGate(
        owner_principal=OWNER,
        hmac_secret=SECRET,
    )
    request = _request(_registry())
    grant = _owner_grant(
        request_digest=request.request_digest,
        decision="approved",
        issued_at=NOW.isoformat(),
        expires_at=request.expires_at,
    )
    verified = gate.verify_grant(request, grant, now=NOW + timedelta(minutes=1))
    assert verified.approved_by == OWNER
    with pytest.raises(PermissionError, match="EXPIRED_OR_INVALID"):
        gate.verify_grant(request, grant, now=NOW + timedelta(minutes=16))


def test_stale_owner_grant_issue_time_is_rejected() -> None:
    gate = GitMutationAuthorizationGate(owner_principal=OWNER, hmac_secret=SECRET)
    request = _request(_registry())
    grant = _owner_grant(
        request_digest=request.request_digest,
        decision="approved",
        issued_at=(NOW - timedelta(hours=2)).isoformat(),
        expires_at=request.expires_at,
    )
    with pytest.raises(PermissionError, match="EXPIRED_OR_INVALID"):
        gate.verify_grant(request, grant, now=NOW + timedelta(minutes=1))


def test_runtime_gate_cannot_mint_owner_grants() -> None:
    gate = GitMutationAuthorizationGate(owner_principal=OWNER, hmac_secret=SECRET)
    assert not hasattr(gate, "sign_for_test_or_operator")
    assert not hasattr(gate, "sign_grant")
    assert not hasattr(gate, "approve")


def test_manifest_tampering_invalidates_request() -> None:
    manifest = _manifest()
    manifest["summary"] = "tampered"
    with pytest.raises(PermissionError, match="MANIFEST_DIGEST_MISMATCH"):
        GitMutationAuthorizationGate.build_request(
            manifest,
            review_registry=_registry(),
            actions=("open_pull_request",),
            expires_at=(NOW + timedelta(minutes=15)).isoformat(),
            now=NOW,
        )
