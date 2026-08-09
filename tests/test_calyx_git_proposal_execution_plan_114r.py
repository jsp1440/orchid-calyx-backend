from __future__ import annotations

import base64
import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.calyx_orchestrator.engineering_core import TerminalOutcome
from app.calyx_orchestrator.execution_bridge import LeaseExecutionBridge
from app.calyx_orchestrator.executor import ExecutionReceipt, ExecutionState, canonical_checksum
from app.calyx_orchestrator.git_mutation_authorization import GRANT_SCHEMA, GitMutationAuthorizationGate
from app.calyx_orchestrator.git_proposal_execution_plan import GitProposalExecutionPlanner
from app.calyx_orchestrator.isolated_patch_executor import ISOLATED_PATCH_ROLE, IsolatedWorkspacePatchExecutor
from app.calyx_orchestrator.owner_signature_verifier import (
    Ed25519OwnerGrantSignatureVerifier,
    OwnerVerificationKey,
    owner_grant_signing_bytes,
)
from app.calyx_orchestrator.program_models import CalyxProgram, CalyxProgramDependency, CalyxProgramJob
from app.calyx_orchestrator.program_repository import PersistentProgramRepository, ProgramJobSpec
from app.calyx_orchestrator.program_worker import PersistentProgramWorker
from app.calyx_orchestrator.proposal_authorization import ProposalDecision
from app.calyx_orchestrator.proposal_authorization_models import ProposalAuthorizationDecisionRecord
from app.calyx_orchestrator.proposal_authorization_store import DurableProposalAuthorizationStore
from app.calyx_orchestrator.sandbox_supervisor_evidence import canonical_sha256
from app.database import Base

REPOSITORY = "jsp1440/orchid-calyx-backend"
BRANCH = "autonomy/work-123"
BASE_COMMIT = "a" * 40
PATCH_CONTENT = "print('bounded plan change')\n"
PATCH_BYTES = PATCH_CONTENT.encode("utf-8")
PATCH_BEFORE = "b" * 64
PATCH_AFTER = hashlib.sha256(PATCH_BYTES).hexdigest()
NOW = datetime(2026, 8, 9, 1, 0, tzinfo=timezone.utc)
OWNER = "principal:owner"


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            CalyxProgram.__table__,
            CalyxProgramJob.__table__,
            CalyxProgramDependency.__table__,
            ProposalAuthorizationDecisionRecord.__table__,
        ],
    )
    return Session(engine)


def _patch_inputs() -> dict[str, object]:
    return {
        "patches": [
            {
                "path": "app/example.py",
                "before_sha256": PATCH_BEFORE,
                "content_utf8": PATCH_CONTENT,
            }
        ]
    }


def _patch_output() -> dict[str, object]:
    return {
        "status": "delivered",
        "executed": True,
        "mode": "authoritative_isolated_workspace_patch",
        "repository": REPOSITORY,
        "branch": BRANCH,
        "checkout_commit_sha": BASE_COMMIT,
        "workspace_isolated": True,
        "workspace_disposable": True,
        "changes": [
            {
                "path": "app/example.py",
                "before_sha256": PATCH_BEFORE,
                "after_sha256": PATCH_AFTER,
                "created": False,
                "size_bytes": len(PATCH_BYTES),
            }
        ],
        "file_count": 1,
        "total_written_bytes": len(PATCH_BYTES),
        "commit_created": False,
        "validation_commands_run": False,
        "side_effects": ["isolated_workspace_files_modified"],
    }


def _persist_patch(session: Session) -> CalyxProgramJob:
    repository = PersistentProgramRepository(session)
    program = repository.create_program(
        owner="owner",
        title="durable plan patch",
        objective="persist exact isolated patch execution",
        jobs=[
            ProgramJobSpec(
                "patch",
                ISOLATED_PATCH_ROLE,
                "patch",
                REPOSITORY,
                BRANCH,
                True,
                inputs=_patch_inputs(),
            )
        ],
        dependencies=[],
    )
    repository.start(owner="owner", program_id=program.program_id)
    claimed = PersistentProgramWorker(session).claim(worker_id="worker")
    assert claimed is not None and claimed.lease_token
    output = _patch_output()
    receipt = ExecutionReceipt(
        assignment_id=claimed.program_job_id,
        program_id=program.program_id,
        job_key=claimed.job_key,
        executor_key=IsolatedWorkspacePatchExecutor.executor_key,
        state=ExecutionState.DELIVERED,
        outcome=TerminalOutcome.DELIVERED,
        input_checksum="1" * 64,
        output_checksum=canonical_checksum(output),
        output=output,
        evidence_uris=("github:issue/701",),
    )
    return LeaseExecutionBridge(session).complete_from_receipt(
        program_job_id=claimed.program_job_id,
        worker_id="worker",
        lease_token=claimed.lease_token,
        receipt=receipt,
    )


def _manifest(patch_program_job_id: str) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema": "calyx-git-proposal-manifest-v2",
        "patch_program_job_id": patch_program_job_id,
        "repository": REPOSITORY,
        "base_commit_sha": BASE_COMMIT,
        "source_autonomy_branch": BRANCH,
        "proposed_branch": "autonomy/proposal/work-123",
        "patch_output_checksum": canonical_checksum(_patch_output()),
        "changes": [
            {
                "path": "app/example.py",
                "before_sha256": PATCH_BEFORE,
                "after_sha256": PATCH_AFTER,
                "created": False,
                "size_bytes": len(PATCH_BYTES),
            }
        ],
        "validations": [
            {
                "preset": "ruff",
                "request_digest": "d" * 64,
                "receipt_digest": "e" * 64,
                "policy_digest": "f" * 64,
                "target_hashes": [{"path": "app/example.py", "sha256": PATCH_AFTER}],
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


def _store() -> tuple[DurableProposalAuthorizationStore, str]:
    session = _session()
    patch_job = _persist_patch(session)
    store = DurableProposalAuthorizationStore(session)
    manifest = _manifest(patch_job.program_job_id)
    for review_class, reviewer in (
        ("operational", "principal:ops-reviewer"),
        ("security", "principal:security-reviewer"),
    ):
        store.record_review(
            manifest_snapshot=manifest,
            requested_by="principal:requester",
            review_class=review_class,
            reviewer_id=reviewer,
            reviewer_roles=(review_class,),
            decision=ProposalDecision.APPROVED,
            rationale=f"{review_class} review complete.",
            evidence_uris=(f"review:{review_class}-ticket",),
            decided_at=NOW,
        )
    return store, patch_job.program_job_id


def _authorization(
    store: DurableProposalAuthorizationStore,
    patch_job_id: str,
    *,
    actions: tuple[str, ...] = (
        "create_branch",
        "create_commit",
        "push_branch",
        "open_pull_request",
    ),
):
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    key = OwnerVerificationKey.from_base64url(
        key_id="owner-test",
        public_key=_b64url(public),
    )
    gate = GitMutationAuthorizationGate(
        owner_principal=OWNER,
        signature_verifier=Ed25519OwnerGrantSignatureVerifier(keys={key.key_id: key}),
    )
    request = gate.build_request(
        _manifest(patch_job_id),
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
    grant = {**unsigned, "signature": f"ed25519:{key.key_id}:{_b64url(signature)}"}
    return gate, request, grant


def test_plan_is_deterministic_and_binds_durable_patch_identity() -> None:
    store, patch_job_id = _store()
    gate, request, grant = _authorization(store, patch_job_id)
    first = GitProposalExecutionPlanner.build(
        manifest_snapshot=_manifest(patch_job_id),
        review_store=store,
        authorization_gate=gate,
        request=request,
        grant_mapping=grant,
        now=NOW + timedelta(minutes=1),
    )
    second = GitProposalExecutionPlanner.build(
        manifest_snapshot=_manifest(patch_job_id),
        review_store=store,
        authorization_gate=gate,
        request=request,
        grant_mapping=grant,
        now=NOW + timedelta(minutes=1),
    )
    assert first.plan_digest == second.plan_digest
    snapshot = first.snapshot()
    assert snapshot["schema"] == "calyx-git-proposal-execution-plan-v2"
    assert snapshot["patch_program_job_id"] == patch_job_id
    assert snapshot["authorization_request_digest"] == request.request_digest
    assert snapshot["manifest_digest"] == request.manifest_digest
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
    commit_op = next(item for item in snapshot["operations"] if item["action"] == "create_commit")
    assert commit_op["parameters"]["patch_program_job_id"] == patch_job_id


def test_plan_canonicalizes_authorized_action_order_and_supports_subset() -> None:
    store, patch_job_id = _store()
    gate, request, grant = _authorization(
        store,
        patch_job_id,
        actions=("open_pull_request", "create_branch"),
    )
    plan = GitProposalExecutionPlanner.build(
        manifest_snapshot=_manifest(patch_job_id),
        review_store=store,
        authorization_gate=gate,
        request=request,
        grant_mapping=grant,
        now=NOW + timedelta(minutes=1),
    )
    assert [operation.action for operation in plan.operations] == ["create_branch", "open_pull_request"]


def test_request_or_patch_job_mismatch_is_rejected_before_planning() -> None:
    store, patch_job_id = _store()
    gate, request, grant = _authorization(store, patch_job_id)
    altered = replace(request, patch_program_job_id="other-patch-job")
    with pytest.raises(PermissionError, match="AUTHORIZATION_REQUEST_MISMATCH"):
        GitProposalExecutionPlanner.build(
            manifest_snapshot=_manifest(patch_job_id),
            review_store=store,
            authorization_gate=gate,
            request=altered,
            grant_mapping=grant,
            now=NOW + timedelta(minutes=1),
        )


def test_manifest_tampering_is_rejected() -> None:
    store, patch_job_id = _store()
    gate, request, grant = _authorization(store, patch_job_id)
    manifest = _manifest(patch_job_id)
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


def test_invalid_signature_and_expired_grant_block_planning() -> None:
    store, patch_job_id = _store()
    gate, request, grant = _authorization(store, patch_job_id)
    invalid = dict(grant)
    invalid["signature"] = invalid["signature"][:-1] + ("A" if invalid["signature"][-1] != "A" else "B")
    with pytest.raises(PermissionError, match="SIGNATURE_INVALID"):
        GitProposalExecutionPlanner.build(
            manifest_snapshot=_manifest(patch_job_id),
            review_store=store,
            authorization_gate=gate,
            request=request,
            grant_mapping=invalid,
            now=NOW + timedelta(minutes=1),
        )
    with pytest.raises(PermissionError, match="EXPIRED_OR_INVALID|EXPIRY_INVALID"):
        GitProposalExecutionPlanner.build(
            manifest_snapshot=_manifest(patch_job_id),
            review_store=store,
            authorization_gate=gate,
            request=request,
            grant_mapping=grant,
            now=NOW + timedelta(minutes=16),
        )
