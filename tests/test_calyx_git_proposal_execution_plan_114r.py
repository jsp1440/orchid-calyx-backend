from __future__ import annotations

import base64
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.executor import canonical_checksum
from app.calyx_orchestrator.git_mutation_authorization import (
    GRANT_SCHEMA,
    GitMutationAuthorizationGate,
)
from app.calyx_orchestrator.git_proposal_execution_plan import GitProposalExecutionPlanner
from app.calyx_orchestrator.owner_signature_verifier import (
    Ed25519OwnerGrantSignatureVerifier,
    OwnerVerificationKey,
    owner_grant_signing_bytes,
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
NOW = datetime(2026, 8, 9, 0, 45, tzinfo=timezone.utc)
OWNER = "principal:owner"


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


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
) -> None:
    store.record_review(
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
    include_operational: bool = True,
    security_decision: ProposalDecision = ProposalDecision.APPROVED,
) -> DurableProposalAuthorizationStore:
    store = DurableProposalAuthorizationStore(_session())
    if include_operational:
        _record_review(
            store,
            review_class="operational",
            reviewer="principal:ops-reviewer",
        )
    _record_review(
        store,
        review_class="security",
        reviewer="principal:security-reviewer",
        decision=security_decision,
    )
    return store


def _authorization(
    store: DurableProposalAuthorizationStore,
    *,
    actions: tuple[str, ...] = (
        "create_branch",
        "create_commit",
        "push_branch",
        "open_pull_request",
    ),
):
    private = Ed25519PrivateKey.generate()
    raw_public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    key = OwnerVerificationKey.from_base64url(
        key_id="owner-test",
        public_key=_b64url(raw_public),
    )
    gate = GitMutationAuthorizationGate(
        owner_principal=OWNER,
        signature_verifier=Ed25519OwnerGrantSignatureVerifier(keys={key.key_id: key}),
    )
    request = gate.build_request(
        _manifest(),
        review_store=store,
        actions=actions,
        expires_at=(NOW + timedelta(minutes=15)).isoformat(),
        now=NOW,
    )
    unsigned = {
        "schema": GRANT_SCHEMA,
        "request_digest": request.request_digest,
        "decision": "approved",
        "approved_by": OWNER,
        "issued_at": NOW.isoformat(),
        "expires_at": request.expires_at,
    }
    signature = private.sign(owner_grant_signing_bytes(unsigned))
    grant = {
        **unsigned,
        "signature": f"ed25519:{key.key_id}:{_b64url(signature)}",
    }
    return gate, request, grant


def test_plan_is_deterministic_binds_evidence_and_performs_no_mutation() -> None:
    store = _store()
    gate, request, grant = _authorization(store)
    first = GitProposalExecutionPlanner.build(
        manifest_snapshot=_manifest(),
        review_store=store,
        authorization_gate=gate,
        request=request,
        grant_mapping=grant,
        now=NOW + timedelta(minutes=1),
    )
    second = GitProposalExecutionPlanner.build(
        manifest_snapshot=_manifest(),
        review_store=store,
        authorization_gate=gate,
        request=request,
        grant_mapping=grant,
        now=NOW + timedelta(minutes=1),
    )
    assert first.plan_digest == second.plan_digest
    snapshot = first.snapshot()
    assert snapshot["authorization_request_digest"] == request.request_digest
    assert snapshot["manifest_digest"] == request.manifest_digest
    assert snapshot["review_authorization_digests"] == list(
        request.review_authorization_digests
    )
    assert snapshot["owner_approved_by"] == OWNER
    assert snapshot["owner_grant_verified"] is True
    assert snapshot["plan_only"] is True
    assert snapshot["git_mutation_performed"] is False
    assert snapshot["branch_created"] is False
    assert snapshot["commit_created"] is False
    assert snapshot["push_performed"] is False
    assert snapshot["pull_request_created"] is False
    assert snapshot["merge_authorized"] is False
    assert snapshot["deployment_authorized"] is False
    assert snapshot["publication_authorized"] is False
    assert snapshot["production_database_mutation_authorized"] is False
    assert snapshot["production_graph_mutation_authorized"] is False


def test_plan_canonicalizes_authorized_action_order_and_supports_subset() -> None:
    store = _store()
    gate, request, grant = _authorization(
        store,
        actions=("open_pull_request", "create_branch"),
    )
    plan = GitProposalExecutionPlanner.build(
        manifest_snapshot=_manifest(),
        review_store=store,
        authorization_gate=gate,
        request=request,
        grant_mapping=grant,
        now=NOW + timedelta(minutes=1),
    )
    assert [operation.action for operation in plan.operations] == [
        "create_branch",
        "open_pull_request",
    ]


def test_request_mismatch_is_rejected_before_planning() -> None:
    store = _store()
    gate, request, grant = _authorization(store)
    altered = replace(request, proposed_branch="autonomy/proposal/tampered")
    with pytest.raises(PermissionError, match="AUTHORIZATION_REQUEST_MISMATCH"):
        GitProposalExecutionPlanner.build(
            manifest_snapshot=_manifest(),
            review_store=store,
            authorization_gate=gate,
            request=altered,
            grant_mapping=grant,
            now=NOW + timedelta(minutes=1),
        )


def test_manifest_tampering_is_rejected() -> None:
    store = _store()
    gate, request, grant = _authorization(store)
    manifest = _manifest()
    manifest["summary"] = "tampered"
    with pytest.raises(PermissionError, match="MANIFEST_DIGEST_MISMATCH"):
        GitProposalExecutionPlanner.build(
            manifest_snapshot=manifest,
            review_store=store,
            authorization_gate=gate,
            request=request,
            grant_mapping=grant,
            now=NOW + timedelta(minutes=1),
        )


def test_missing_or_rejected_durable_review_blocks_planning() -> None:
    missing = _store(include_operational=False)
    gate, _, _ = _authorization(_store())
    valid_store = _store()
    _, request, grant = _authorization(valid_store)
    with pytest.raises(PermissionError, match="PROPOSAL_REVIEWS_PENDING"):
        GitProposalExecutionPlanner.build(
            manifest_snapshot=_manifest(),
            review_store=missing,
            authorization_gate=gate,
            request=request,
            grant_mapping=grant,
            now=NOW + timedelta(minutes=1),
        )

    rejected = _store(security_decision=ProposalDecision.REJECTED)
    with pytest.raises(PermissionError, match="PROPOSAL_REVIEW_REJECTED"):
        GitProposalExecutionPlanner.build(
            manifest_snapshot=_manifest(),
            review_store=rejected,
            authorization_gate=gate,
            request=request,
            grant_mapping=grant,
            now=NOW + timedelta(minutes=1),
        )


def test_invalid_signature_and_expired_grant_block_planning() -> None:
    store = _store()
    gate, request, grant = _authorization(store)
    invalid = dict(grant)
    invalid["signature"] = invalid["signature"][:-1] + "A"
    with pytest.raises(PermissionError, match="SIGNATURE_INVALID"):
        GitProposalExecutionPlanner.build(
            manifest_snapshot=_manifest(),
            review_store=store,
            authorization_gate=gate,
            request=request,
            grant_mapping=invalid,
            now=NOW + timedelta(minutes=1),
        )

    with pytest.raises(PermissionError, match="EXPIRED_OR_INVALID|EXPIRY_INVALID"):
        GitProposalExecutionPlanner.build(
            manifest_snapshot=_manifest(),
            review_store=store,
            authorization_gate=gate,
            request=request,
            grant_mapping=grant,
            now=NOW + timedelta(minutes=16),
        )
