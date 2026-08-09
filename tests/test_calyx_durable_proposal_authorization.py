from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.calyx_orchestrator.assignment_factory import assignment_inputs_for_program_job
from app.calyx_orchestrator.engineering_core import TerminalOutcome
from app.calyx_orchestrator.execution_bridge import LeaseExecutionBridge
from app.calyx_orchestrator.executor import (
    ExecutionReceipt,
    ExecutionState,
    canonical_checksum,
)
from app.calyx_orchestrator.isolated_patch_executor import (
    ISOLATED_PATCH_ROLE,
    IsolatedWorkspacePatchExecutor,
)
from app.calyx_orchestrator.program_models import (
    CalyxProgram,
    CalyxProgramDependency,
    CalyxProgramJob,
)
from app.calyx_orchestrator.program_repository import (
    PersistentProgramRepository,
    ProgramJobSpec,
)
from app.calyx_orchestrator.program_worker import PersistentProgramWorker
from app.calyx_orchestrator.proposal_authorization import ProposalDecision
from app.calyx_orchestrator.proposal_authorization_models import (
    ProposalAuthorizationDecisionRecord,
)
from app.calyx_orchestrator.proposal_authorization_status import proposal_review_status
from app.calyx_orchestrator.proposal_authorization_store import (
    DurableProposalAuthorizationStore,
)
from app.calyx_orchestrator.sandbox_supervisor_evidence import canonical_sha256
from app.database import Base

REPOSITORY = "jsp1440/orchid-calyx-backend"
BRANCH = "autonomy/work-123"
BASE_COMMIT = "a" * 40
PATCH_CONTENT = "print('bounded review change')\n"
PATCH_BYTES = PATCH_CONTENT.encode("utf-8")
PATCH_BEFORE = "b" * 64
PATCH_AFTER = hashlib.sha256(PATCH_BYTES).hexdigest()
NOW = datetime(2026, 8, 8, 23, 0, tzinfo=timezone.utc)


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
        title="durable review patch",
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
    authoritative_input_checksum = canonical_checksum(
        assignment_inputs_for_program_job(program, claimed)
    )
    receipt = ExecutionReceipt(
        assignment_id=claimed.program_job_id,
        program_id=program.program_id,
        job_key=claimed.job_key,
        executor_key=IsolatedWorkspacePatchExecutor.executor_key,
        state=ExecutionState.DELIVERED,
        outcome=TerminalOutcome.DELIVERED,
        input_checksum=authoritative_input_checksum,
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
        "changes": [
            {
                "path": "app/example.py",
                "before_sha256": PATCH_BEFORE,
                "after_sha256": PATCH_AFTER,
                "created": False,
                "size_bytes": len(PATCH_BYTES),
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


def _record_review(
    store: DurableProposalAuthorizationStore,
    patch_program_job_id: str,
    *,
    review_class: str = "security",
    reviewer_id: str = "principal:security-reviewer",
    decision: ProposalDecision = ProposalDecision.APPROVED,
):
    return store.record_review(
        manifest_snapshot=_manifest(patch_program_job_id),
        requested_by="principal:requester",
        review_class=review_class,
        reviewer_id=reviewer_id,
        reviewer_roles=(review_class,),
        decision=decision,
        rationale=f"{review_class} review complete.",
        evidence_uris=(f"review:{review_class}-ticket",),
        decided_at=NOW,
    )


def _store_with_patch() -> tuple[Session, DurableProposalAuthorizationStore, str]:
    session = _session()
    patch_job = _persist_patch(session)
    return session, DurableProposalAuthorizationStore(session), patch_job.program_job_id


def test_strengthened_parent_input_checksum_allows_durable_review_reload() -> None:
    session, store, patch_job_id = _store_with_patch()
    item = _record_review(store, patch_job_id)
    engine = session.bind
    session.close()
    assert engine is not None
    reloaded_session = Session(engine)
    reloaded = DurableProposalAuthorizationStore(reloaded_session).require(
        manifest_digest=item.manifest_digest,
        review_class=item.review_class,
    )
    assert reloaded == item
    assert reloaded.patch_program_job_id == patch_job_id


def test_identical_replay_is_idempotent_and_conflicting_replacement_fails() -> None:
    _, store, patch_job_id = _store_with_patch()
    approved = _record_review(store, patch_job_id)
    assert _record_review(store, patch_job_id) == approved
    with pytest.raises(ValueError, match="DURABLE_DECISION_ALREADY_RECORDED"):
        _record_review(store, patch_job_id, decision=ProposalDecision.REJECTED)


def test_payload_and_patch_evidence_tampering_fail_closed() -> None:
    session, store, patch_job_id = _store_with_patch()
    item = _record_review(store, patch_job_id)
    row = session.scalar(select(ProposalAuthorizationDecisionRecord))
    assert row is not None
    payload = json.loads(row.payload_json)
    payload["rationale"] = "tampered"
    row.payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    session.commit()
    with pytest.raises(PermissionError, match="AUTHORIZATION_DIGEST_MISMATCH"):
        store.require(
            manifest_digest=item.manifest_digest, review_class=item.review_class
        )

    session.rollback()
    row.payload_json = json.dumps(
        item.snapshot(), sort_keys=True, separators=(",", ":")
    )
    session.commit()
    patch_job = session.get(CalyxProgramJob, patch_job_id)
    assert patch_job is not None and patch_job.evidence_json
    evidence = json.loads(patch_job.evidence_json)
    evidence["output"]["total_written_bytes"] = len(PATCH_BYTES) + 1
    patch_job.evidence_json = json.dumps(evidence, sort_keys=True)
    session.commit()
    with pytest.raises(PermissionError, match="PATCH_EVIDENCE_UNAVAILABLE"):
        store.require(
            manifest_digest=item.manifest_digest, review_class=item.review_class
        )


def test_dual_review_materialization_requires_independent_reviewers() -> None:
    _, store, patch_job_id = _store_with_patch()
    security = _record_review(store, patch_job_id)
    _record_review(
        store,
        patch_job_id,
        review_class="operational",
        reviewer_id="principal:ops-reviewer",
    )
    registry = store.materialize_registry(manifest_digest=security.manifest_digest)
    status = proposal_review_status(registry, manifest_digest=security.manifest_digest)
    assert status.review_evidence_complete is True
    assert status.code == "PROPOSAL_REVIEW_EVIDENCE_COMPLETE"
    assert status.git_mutation_authorized is False


def test_governed_write_path_rejects_self_approval_and_unknown_patch() -> None:
    _, store, patch_job_id = _store_with_patch()
    assert not hasattr(store, "record")
    with pytest.raises(PermissionError, match="SELF_APPROVAL_PROHIBITED"):
        store.record_review(
            manifest_snapshot=_manifest(patch_job_id),
            requested_by="principal:security-reviewer",
            review_class="security",
            reviewer_id="principal:security-reviewer",
            reviewer_roles=("security",),
            decision=ProposalDecision.APPROVED,
            rationale="invalid self approval",
            evidence_uris=("review:invalid",),
            decided_at=NOW,
        )
    with pytest.raises(PermissionError, match="PERSISTED_PATCH_REQUIRED"):
        store.record_review(
            manifest_snapshot=_manifest("22222222-2222-2222-2222-222222222222"),
            requested_by="principal:requester",
            review_class="security",
            reviewer_id="principal:security-reviewer",
            reviewer_roles=("security",),
            decision=ProposalDecision.APPROVED,
            rationale="invalid missing patch",
            evidence_uris=("review:invalid",),
            decided_at=NOW,
        )
