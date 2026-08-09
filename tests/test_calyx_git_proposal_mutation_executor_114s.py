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
from app.calyx_orchestrator.git_proposal_mutation_executor import (
    GitProposalMutationError,
    GitProposalMutationExecutor,
)
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
COMMIT_SHA = "9" * 40
NOW = datetime(2026, 8, 9, 2, 30, tzinfo=timezone.utc)
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


def _store() -> DurableProposalAuthorizationStore:
    store = DurableProposalAuthorizationStore(_session())
    for review_class, reviewer in (
        ("operational", "principal:ops-reviewer"),
        ("security", "principal:security-reviewer"),
    ):
        store.record_review(
            manifest_snapshot=_manifest(),
            patch_receipt=_patch_receipt(),
            requested_by="principal:requester",
            review_class=review_class,
            reviewer_id=reviewer,
            reviewer_roles=(review_class,),
            decision=ProposalDecision.APPROVED,
            rationale=f"{review_class} approved",
            evidence_uris=(f"review:{review_class}",),
            decided_at=NOW,
        )
    return store


def _authorization(store: DurableProposalAuthorizationStore):
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
        actions=(
            "create_branch",
            "create_commit",
            "push_branch",
            "open_pull_request",
        ),
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
    plan = GitProposalExecutionPlanner.build(
        manifest_snapshot=_manifest(),
        review_store=store,
        authorization_gate=gate,
        request=request,
        grant_mapping=grant,
        now=NOW + timedelta(minutes=1),
    )
    return gate, request, grant, plan


class FakeMutationAdapter:
    def __init__(
        self,
        *,
        fail_action: str | None = None,
        divergent: bool = False,
        wrong_push_commit: bool = False,
    ) -> None:
        self.fail_action = fail_action
        self.divergent = divergent
        self.wrong_push_commit = wrong_push_commit
        self.calls: list[str] = []

    def apply_proposal_operation(self, *, plan_digest: str, operation):
        assert len(plan_digest) == 64
        self.calls.append(operation.action)
        if operation.action == self.fail_action:
            raise RuntimeError("FAKE_REMOTE_FAILURE")
        common = {
            "action": operation.action,
            "status": "created",
            "repository": REPOSITORY,
            "branch": "autonomy/proposal/work-123",
        }
        if operation.action == "create_branch":
            return {**common, "base_commit_sha": BASE_COMMIT}
        if operation.action == "create_commit":
            changes = [{"path": "app/example.py", "after_sha256": "c" * 64}]
            if self.divergent:
                changes[0]["after_sha256"] = "0" * 64
            return {
                **common,
                "parent_commit_sha": BASE_COMMIT,
                "commit_sha": COMMIT_SHA,
                "change_hashes": changes,
            }
        if operation.action == "push_branch":
            commit = "8" * 40 if self.wrong_push_commit else COMMIT_SHA
            return {**common, "commit_sha": commit}
        if operation.action == "open_pull_request":
            return {
                **common,
                "head_branch": "autonomy/proposal/work-123",
                "base_commit_sha": BASE_COMMIT,
                "head_commit_sha": COMMIT_SHA,
                "pull_request_number": 1234,
            }
        raise AssertionError(operation.action)


def _execute(adapter: FakeMutationAdapter, *, plan=None, now=None):
    store = _store()
    gate, request, grant, actual_plan = _authorization(store)
    executor = GitProposalMutationExecutor(
        adapter=adapter,
        repository_allowlist=(REPOSITORY,),
    )
    return executor.execute(
        plan=actual_plan if plan is None else plan,
        manifest_snapshot=_manifest(),
        review_store=store,
        authorization_gate=gate,
        request=request,
        grant_mapping=grant,
        now=NOW + timedelta(minutes=1) if now is None else now,
    )


def test_successful_flow_is_canonical_and_never_grants_merge_authority() -> None:
    adapter = FakeMutationAdapter()
    receipt = _execute(adapter)
    assert adapter.calls == [
        "create_branch",
        "create_commit",
        "push_branch",
        "open_pull_request",
    ]
    assert receipt.status == "completed"
    snapshot = receipt.snapshot()
    assert snapshot["completed_actions"] == adapter.calls
    assert snapshot["merge_authorized"] is False
    assert snapshot["automatic_merge_authorized"] is False
    assert snapshot["deployment_authorized"] is False
    assert snapshot["publication_authorized"] is False
    assert snapshot["production_database_mutation_authorized"] is False
    assert snapshot["production_graph_mutation_authorized"] is False


def test_tampered_plan_is_rejected_before_adapter_call() -> None:
    store = _store()
    gate, request, grant, plan = _authorization(store)
    tampered = replace(plan, pr_title="tampered")
    adapter = FakeMutationAdapter()
    executor = GitProposalMutationExecutor(
        adapter=adapter,
        repository_allowlist=(REPOSITORY,),
    )
    with pytest.raises(PermissionError, match="PLAN_MISMATCH"):
        executor.execute(
            plan=tampered,
            manifest_snapshot=_manifest(),
            review_store=store,
            authorization_gate=gate,
            request=request,
            grant_mapping=grant,
            now=NOW + timedelta(minutes=1),
        )
    assert adapter.calls == []


def test_expired_owner_grant_is_rejected_before_adapter_call() -> None:
    adapter = FakeMutationAdapter()
    with pytest.raises(PermissionError, match="EXPIRED_OR_INVALID|EXPIRY_INVALID"):
        _execute(adapter, now=NOW + timedelta(minutes=16))
    assert adapter.calls == []


def test_divergent_commit_postimage_fails_closed_with_partial_receipt() -> None:
    adapter = FakeMutationAdapter(divergent=True)
    with pytest.raises(GitProposalMutationError) as raised:
        _execute(adapter)
    receipt = raised.value.receipt
    assert receipt.status == "partial_failure"
    assert receipt.completed_actions == ("create_branch",)
    assert adapter.calls == ["create_branch", "create_commit"]


def test_push_must_reference_exact_created_commit() -> None:
    adapter = FakeMutationAdapter(wrong_push_commit=True)
    with pytest.raises(GitProposalMutationError) as raised:
        _execute(adapter)
    receipt = raised.value.receipt
    assert receipt.status == "partial_failure"
    assert receipt.completed_actions == ("create_branch", "create_commit")
    assert adapter.calls == ["create_branch", "create_commit", "push_branch"]


def test_remote_failure_preserves_completed_side_effect_evidence() -> None:
    adapter = FakeMutationAdapter(fail_action="push_branch")
    with pytest.raises(GitProposalMutationError) as raised:
        _execute(adapter)
    receipt = raised.value.receipt
    assert receipt.status == "partial_failure"
    assert receipt.completed_actions == ("create_branch", "create_commit")
    assert len(receipt.operation_evidence) == 2
    assert receipt.failure_code == "RuntimeError"


def test_repository_allowlist_is_enforced_before_mutation() -> None:
    store = _store()
    gate, request, grant, plan = _authorization(store)
    adapter = FakeMutationAdapter()
    executor = GitProposalMutationExecutor(
        adapter=adapter,
        repository_allowlist=("other/repo",),
    )
    with pytest.raises(PermissionError, match="REPOSITORY_NOT_ALLOWED"):
        executor.execute(
            plan=plan,
            manifest_snapshot=_manifest(),
            review_store=store,
            authorization_gate=gate,
            request=request,
            grant_mapping=grant,
            now=NOW + timedelta(minutes=1),
        )
    assert adapter.calls == []
