from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.calyx_orchestrator.assignment_factory import assignment_inputs_for_program_job
from app.calyx_orchestrator.engineering_core import TerminalOutcome
from app.calyx_orchestrator.execution_bridge import LeaseExecutionBridge
from app.calyx_orchestrator.executor import ExecutionReceipt, ExecutionState, canonical_checksum
from app.calyx_orchestrator.git_mutation_authorization import GRANT_SCHEMA, GitMutationAuthorizationGate
from app.calyx_orchestrator.isolated_patch_executor import ISOLATED_PATCH_ROLE, IsolatedWorkspacePatchExecutor
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
PATCH_CONTENT = "print('bounded owner change')\n"
PATCH_BYTES = PATCH_CONTENT.encode("utf-8")
PATCH_BEFORE = "b" * 64
PATCH_AFTER = hashlib.sha256(PATCH_BYTES).hexdigest()
NOW = datetime(2026, 8, 8, 23, 0, tzinfo=timezone.utc)
SECRET = b"s" * 32
OWNER = "principal:owner"


class TestHmacVerifier:
    __test__ = False

    def verify(self, *, payload: Mapping[str, Any], signature: str) -> bool:
        expected = hmac.new(SECRET, canonical_sha256(payload).encode("ascii"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)


def _gate() -> GitMutationAuthorizationGate:
    return GitMutationAuthorizationGate(owner_principal=OWNER, signature_verifier=TestHmacVerifier())


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
    return {"patches": [{"path": "app/example.py", "before_sha256": PATCH_BEFORE, "content_utf8": PATCH_CONTENT}]}


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
        "changes": [{"path": "app/example.py", "before_sha256": PATCH_BEFORE, "after_sha256": PATCH_AFTER, "created": False, "size_bytes": len(PATCH_BYTES)}],
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
        title="durable owner authorization patch",
        objective="persist exact isolated patch execution",
        jobs=[ProgramJobSpec("patch", ISOLATED_PATCH_ROLE, "patch", REPOSITORY, BRANCH, True, inputs=_patch_inputs())],
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
        input_checksum=canonical_checksum(assignment_inputs_for_program_job(program, claimed)),
        output_checksum=canonical_checksum(output),
        output=output,
        evidence_uris=("github:issue/691",),
    )
    return LeaseExecutionBridge(session).complete_from_receipt(
        program_job_id=claimed.program_job_id,
        worker_id="worker",
        lease_token=claimed.lease_token,
        receipt=receipt,
    )


def _manifest(patch_program_job_id: str) -> dict:
    output = _patch_output()
    payload = {
        "schema": "calyx-git-proposal-manifest-v2",
        "patch_program_job_id": patch_program_job_id,
        "repository": REPOSITORY,
        "base_commit_sha": BASE_COMMIT,
        "source_autonomy_branch": BRANCH,
        "proposed_branch": "autonomy/proposal/work-123",
        "patch_output_checksum": canonical_checksum(output),
        "changes": [{"path": "app/example.py", "before_sha256": PATCH_BEFORE, "after_sha256": PATCH_AFTER, "created": False, "size_bytes": len(PATCH_BYTES)}],
        "validations": [{"preset": "ruff", "request_digest": "d" * 64, "receipt_digest": "e" * 64, "policy_digest": "f" * 64, "target_hashes": [{"path": "app/example.py", "sha256": PATCH_AFTER}]}],
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


def _record_review(store, job_id, review_class, reviewer, decision=ProposalDecision.APPROVED):
    return store.record_review(
        manifest_snapshot=_manifest(job_id),
        requested_by="principal:requester",
        review_class=review_class,
        reviewer_id=reviewer,
        reviewer_roles=(review_class,),
        decision=decision,
        rationale=f"{review_class} review complete.",
        evidence_uris=(f"review:{review_class}-ticket",),
        decided_at=NOW,
    )


def _store(*, security_decision=ProposalDecision.APPROVED, same_reviewer=False):
    session = _session()
    patch_job = _persist_patch(session)
    store = DurableProposalAuthorizationStore(session)
    ops = "principal:shared-reviewer" if same_reviewer else "principal:ops-reviewer"
    sec = "principal:shared-reviewer" if same_reviewer else "principal:security-reviewer"
    _record_review(store, patch_job.program_job_id, "operational", ops)
    _record_review(store, patch_job.program_job_id, "security", sec, security_decision)
    return store, patch_job.program_job_id


def _request(store, job_id):
    return GitMutationAuthorizationGate.build_request(
        _manifest(job_id),
        review_store=store,
        actions=("create_branch", "create_commit", "push_branch", "open_pull_request"),
        expires_at=(NOW + timedelta(minutes=15)).isoformat(),
        now=NOW,
    )


def _owner_grant(*, request_digest, decision, issued_at, expires_at):
    unsigned = {"schema": GRANT_SCHEMA, "request_digest": request_digest, "decision": decision, "approved_by": OWNER, "issued_at": issued_at, "expires_at": expires_at}
    signature = hmac.new(SECRET, canonical_sha256(unsigned).encode("ascii"), hashlib.sha256).hexdigest()
    return {**unsigned, "signature": signature}


def test_request_binds_strengthened_durable_patch_and_independent_reviews():
    store, job_id = _store()
    request = _request(store, job_id)
    snapshot = request.snapshot()
    assert snapshot["patch_program_job_id"] == job_id
    assert len(snapshot["review_authorization_digests"]) == 2
    assert snapshot["merge_authorized"] is False
    assert snapshot["automatic_merge_authorized"] is False
    assert snapshot["deployment_authorized"] is False
    assert snapshot["publication_authorized"] is False
    assert snapshot["taxonomy_activation_authorized"] is False
    assert snapshot["production_database_mutation_authorized"] is False
    assert snapshot["production_graph_mutation_authorized"] is False


def test_missing_rejected_or_same_reviewer_reviews_fail_closed():
    session = _session()
    patch_job = _persist_patch(session)
    store = DurableProposalAuthorizationStore(session)
    _record_review(store, patch_job.program_job_id, "security", "principal:security-reviewer")
    with pytest.raises(PermissionError, match="PROPOSAL_REVIEWS_PENDING"):
        _request(store, patch_job.program_job_id)
    rejected, job_id = _store(security_decision=ProposalDecision.REJECTED)
    with pytest.raises(PermissionError, match="PROPOSAL_REVIEW_REJECTED"):
        _request(rejected, job_id)
    conflicted, job_id = _store(same_reviewer=True)
    with pytest.raises(PermissionError, match="PROPOSAL_REVIEW_REVIEWER_CONFLICT"):
        _request(conflicted, job_id)


def test_tampered_persisted_review_fails_closed():
    store, job_id = _store()
    row = store.db.scalar(select(ProposalAuthorizationDecisionRecord).where(ProposalAuthorizationDecisionRecord.review_class == "security"))
    assert row is not None
    row.payload_json = row.payload_json.replace("security review complete.", "tampered")
    store.db.commit()
    with pytest.raises(PermissionError, match="PROPOSAL_AUTH_DURABLE"):
        _request(store, job_id)


def test_merge_action_is_not_allowlisted():
    store, job_id = _store()
    with pytest.raises(PermissionError, match="ACTION_NOT_ALLOWED"):
        GitMutationAuthorizationGate.build_request(
            _manifest(job_id), review_store=store, actions=("merge_pull_request",), expires_at=(NOW + timedelta(minutes=15)).isoformat(), now=NOW
        )


def test_exact_external_owner_grant_verifies_but_expiry_and_bad_signature_fail():
    gate = _gate()
    store, job_id = _store()
    request = _request(store, job_id)
    grant = _owner_grant(request_digest=request.request_digest, decision="approved", issued_at=NOW.isoformat(), expires_at=request.expires_at)
    assert gate.verify_grant(request, grant, now=NOW + timedelta(minutes=1)).approved_by == OWNER
    with pytest.raises(PermissionError, match="EXPIRED_OR_INVALID"):
        gate.verify_grant(request, grant, now=NOW + timedelta(minutes=16))
    grant["signature"] = "0" * 64
    with pytest.raises(PermissionError, match="SIGNATURE_INVALID"):
        gate.verify_grant(request, grant, now=NOW + timedelta(minutes=1))


def test_runtime_gate_has_no_signing_secret_or_mutation_api():
    gate = _gate()
    assert not hasattr(gate, "_secret")
    assert not hasattr(gate, "sign_grant")
    assert not hasattr(gate, "approve")
    assert not hasattr(gate, "execute")
