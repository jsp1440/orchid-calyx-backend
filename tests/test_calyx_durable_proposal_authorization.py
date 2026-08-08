from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.calyx_orchestrator.executor import canonical_checksum
from app.calyx_orchestrator.proposal_authorization import (
    ProposalAuthorizationBuilder,
    ProposalDecision,
)
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
BASE_COMMIT = "a" * 40
NOW = datetime(2026, 8, 8, 23, 0, tzinfo=timezone.utc)


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


def _review(
    *,
    review_class: str = "security",
    reviewer_id: str = "principal:security-reviewer",
    decision: ProposalDecision = ProposalDecision.APPROVED,
):
    return ProposalAuthorizationBuilder().build(
        manifest_snapshot=_manifest(),
        patch_receipt=_patch_receipt(),
        requested_by="principal:requester",
        review_class=review_class,
        reviewer_id=reviewer_id,
        reviewer_roles=(review_class,),
        decision=decision,
        rationale=f"{review_class} review complete.",
        evidence_uris=(f"review:{review_class}-ticket",),
        decided_at=NOW,
    )


def test_record_survives_session_restart_and_rehydrates_exactly() -> None:
    session = _session()
    item = _review()
    store = DurableProposalAuthorizationStore(session)
    assert store.record(item) == item
    session.close()

    session = Session(session.bind)
    reloaded = DurableProposalAuthorizationStore(session).require(
        manifest_digest=item.manifest_digest,
        review_class=item.review_class,
    )
    assert reloaded == item
    assert reloaded.authorization_digest == item.authorization_digest


def test_identical_replay_is_idempotent_but_conflicting_decision_is_terminal() -> None:
    session = _session()
    store = DurableProposalAuthorizationStore(session)
    approved = _review()
    assert store.record(approved) == approved
    assert store.record(approved) == approved

    rejected = _review(decision=ProposalDecision.REJECTED)
    with pytest.raises(
        ValueError,
        match="PROPOSAL_AUTH_DURABLE_DECISION_ALREADY_RECORDED",
    ):
        store.record(rejected)


def test_payload_tampering_is_detected_on_read() -> None:
    session = _session()
    item = _review()
    store = DurableProposalAuthorizationStore(session)
    store.record(item)
    row = session.scalar(select(ProposalAuthorizationDecisionRecord))
    assert row is not None
    payload = json.loads(row.payload_json)
    payload["rationale"] = "tampered after persistence"
    row.payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    session.commit()

    with pytest.raises(
        PermissionError,
        match="PROPOSAL_AUTH_DURABLE_AUTHORIZATION_DIGEST_MISMATCH",
    ):
        store.require(
            manifest_digest=item.manifest_digest,
            review_class=item.review_class,
        )


def test_row_identity_tampering_is_detected() -> None:
    session = _session()
    item = _review()
    store = DurableProposalAuthorizationStore(session)
    store.record(item)
    row = session.scalar(select(ProposalAuthorizationDecisionRecord))
    assert row is not None
    row.authorization_digest = "f" * 64
    session.commit()

    with pytest.raises(PermissionError, match="ROW_DIGEST_MISMATCH"):
        store.require(
            manifest_digest=item.manifest_digest,
            review_class=item.review_class,
        )


def test_dual_review_status_survives_materialization_from_durable_store() -> None:
    session = _session()
    store = DurableProposalAuthorizationStore(session)
    security = _review()
    operational = _review(
        review_class="operational",
        reviewer_id="principal:ops-reviewer",
    )
    store.record(security)
    store.record(operational)

    registry = store.materialize_registry(manifest_digest=security.manifest_digest)
    status = proposal_review_status(registry, manifest_digest=security.manifest_digest)
    assert status.review_evidence_complete is True
    assert status.code == "PROPOSAL_REVIEW_EVIDENCE_COMPLETE"
    assert status.reviewer_conflict is False


def test_invalid_manifest_digest_and_review_class_fail_closed() -> None:
    store = DurableProposalAuthorizationStore(_session())
    with pytest.raises(ValueError, match="MANIFEST_DIGEST_INVALID"):
        store.require(manifest_digest="not-a-digest", review_class="security")
    with pytest.raises(ValueError, match="REVIEW_CLASS_INVALID"):
        store.require(manifest_digest="a" * 64, review_class="scientific")
