from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.calyx_orchestrator.executor import canonical_checksum
from app.calyx_orchestrator.git_mutation_authorization import (
    GRANT_SCHEMA,
    GitMutationAuthorizationGate,
)
from app.calyx_orchestrator.proposal_authorization import ProposalDecision
from app.calyx_orchestrator.proposal_authorization_models import (
    ProposalAuthorizationDecisionRecord,
)
from app.calyx_orchestrator.proposal_authorization_store import (
    DurableProposalAuthorizationStore,
)
from app.calyx_orchestrator.sandbox_supervisor_evidence import canonical_sha256
from app.database import Base

REPOSITORY = "jsp1440/orchid-calyx-backend"
BASE_COMMIT = "a" * 40
NOW = datetime(2026, 8, 8, 23, 0, tzinfo=timezone.utc)
SECRET = b"s" * 32
OWNER = "principal:owner"


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[ProposalAuthorizationDecisionRecord.__table__],
    )
    return Session(engine)


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
    output = _patch_output()
    payload = {
        "schema": "calyx-git-proposal-manifest-v1",
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


def _record_review(
    store: DurableProposalAuthorizationStore,
    *,
    review_class: str,
    reviewer: str,
    decision: ProposalDecision = ProposalDecision.APPROVED,
):
    return store.record_review(
        manifest_snapshot=_manifest(),
        patch_receipt=_patch_receipt(),
        requested_by="principal:requester",
        review_class=review_class,
        reviewer_id=reviewer,
        reviewer_roles=(review_class,),
        decision=decision,
        rationale=f"{review_class} review complete.",
        evidence_uris=(f"review:{review_class}-ticket",),
        decided_at=NOW,
    )


def _store(
    *,
    security_decision: ProposalDecision = ProposalDecision.APPROVED,
    same_reviewer: bool = False,
) -> DurableProposalAuthorizationStore:
    store = DurableProposalAuthorizationStore(_session())
    operational_reviewer = (
        "principal:shared-reviewer" if same_reviewer else "principal:ops-reviewer"
    )
    security_reviewer = (
        "principal:shared-reviewer"
        if same_reviewer
        else "principal:security-reviewer"
    )
    _record_review(
        store,
        review_class="operational",
        reviewer=operational_reviewer,
    )
    _record_review(
        store,
        review_class="security",
        reviewer=security_reviewer,
        decision=security_decision,
    )
    return store


def _request(store: DurableProposalAuthorizationStore):
    return GitMutationAuthorizationGate.build_request(
        _manifest(),
        review_store=store,
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


def test_request_requires_both_persisted_reviews() -> None:
    store = DurableProposalAuthorizationStore(_session())
    _record_review(
        store,
        review_class="security",
        reviewer="principal:security-reviewer",
    )
    with pytest.raises(PermissionError, match="PROPOSAL_REVIEWS_PENDING"):
        _request(store)


def test_rejected_persisted_review_blocks_request() -> None:
    with pytest.raises(PermissionError, match="PROPOSAL_REVIEW_REJECTED"):
        _request(_store(security_decision=ProposalDecision.REJECTED))


def test_distinct_persisted_reviewers_are_required() -> None:
    with pytest.raises(PermissionError, match="PROPOSAL_REVIEW_REVIEWER_CONFLICT"):
        _request(_store(same_reviewer=True))


def test_tampered_persisted_review_cannot_satisfy_gate() -> None:
    store = _store()
    row = store.db.scalar(
        select(ProposalAuthorizationDecisionRecord).where(
            ProposalAuthorizationDecisionRecord.review_class == "security"
        )
    )
    assert row is not None
    row.payload_json = row.payload_json.replace("security review complete.", "tampered")
    store.db.commit()
    with pytest.raises(PermissionError, match="PROPOSAL_AUTH_DURABLE"):
        _request(store)


def test_request_binds_durable_review_digests_and_grants_no_merge_authority() -> None:
    request = _request(_store())
    snapshot = request.snapshot()
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
            review_store=_store(),
            actions=("merge_pull_request",),
            expires_at=(NOW + timedelta(minutes=15)).isoformat(),
            now=NOW,
        )


def test_exact_external_owner_grant_verifies_and_expired_grant_fails() -> None:
    gate = GitMutationAuthorizationGate(
        owner_principal=OWNER,
        hmac_secret=SECRET,
    )
    request = _request(_store())
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
    request = _request(_store())
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
            review_store=_store(),
            actions=("open_pull_request",),
            expires_at=(NOW + timedelta(minutes=15)).isoformat(),
            now=NOW,
        )
