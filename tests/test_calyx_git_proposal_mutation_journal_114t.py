from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.calyx_orchestrator.git_proposal_execution_plan import (
    GitProposalExecutionPlan,
    GitProposalPlanOperation,
)
from app.calyx_orchestrator.git_proposal_mutation_executor import (
    GitProposalMutationExecutor,
    GitProposalMutationReceipt,
    GitProposalOperationEvidence,
)
from app.calyx_orchestrator.git_proposal_mutation_journal import (
    DurableGitProposalMutationJournal,
    GitProposalMutationJournalEventRecord,
)
from app.calyx_orchestrator.sandbox_supervisor_evidence import canonical_sha256
from app.database import Base

PLAN_DIGEST = "a" * 64
BASE = "b" * 40
REPOSITORY = "jsp1440/orchid-calyx-backend"
BRANCH = "autonomy/proposal/work-123"
COMMIT = "c" * 40


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[GitProposalMutationJournalEventRecord.__table__])
    return Session(engine)


def _plan() -> GitProposalExecutionPlan:
    operations = (
        GitProposalPlanOperation("create_branch", {}),
        GitProposalPlanOperation("create_commit", {}),
        GitProposalPlanOperation("push_branch", {}),
        GitProposalPlanOperation("open_pull_request", {}),
    )
    return GitProposalExecutionPlan(
        manifest_digest="1" * 64,
        authorization_request_digest="2" * 64,
        repository=REPOSITORY,
        base_commit_sha=BASE,
        proposed_branch=BRANCH,
        change_hashes=(("app/example.py", "3" * 64),),
        validation_receipt_digests=("4" * 64,),
        review_authorization_digests=("5" * 64, "6" * 64),
        owner_approved_by="principal:owner",
        owner_grant_expires_at="2026-08-09T03:00:00+00:00",
        owner_grant_signature_digest="7" * 64,
        commit_title="Bounded change",
        pr_title="Bounded change",
        summary="Proposal evidence.",
        operations=operations,
    )


def _evidence(action: str) -> GitProposalOperationEvidence:
    payload = {"action": action, "status": "created", "repository": REPOSITORY, "branch": BRANCH}
    return GitProposalOperationEvidence(
        action=action,
        status="created",
        evidence_digest=canonical_sha256(payload),
        payload=payload,
    )


def _receipt(status: str, count: int, *, failure_code: str | None = None) -> GitProposalMutationReceipt:
    plan = _plan()
    actions = tuple(operation.action for operation in plan.operations[:count])
    evidence = tuple(_evidence(action) for action in actions)
    return GitProposalMutationReceipt(
        plan_digest=plan.plan_digest,
        repository=REPOSITORY,
        proposed_branch=BRANCH,
        base_commit_sha=BASE,
        status=status,
        completed_actions=actions,
        operation_evidence=evidence,
        failure_code=failure_code,
    )


def test_progress_and_completed_receipts_survive_restart() -> None:
    session = _session()
    first = DurableGitProposalMutationJournal(session)
    first.record(_receipt("in_progress", 1), event_index=1)
    first.record(_receipt("in_progress", 2), event_index=2)
    final = first.record(_receipt("completed", 4), event_index=3)

    restarted = DurableGitProposalMutationJournal(session)
    assert restarted.latest(plan_digest=_plan().plan_digest) == final
    state = restarted.recovery_state(_plan())
    assert state.classification == "completed"
    assert state.next_action is None
    assert state.terminal is True


def test_partial_failure_reloads_with_next_action() -> None:
    journal = DurableGitProposalMutationJournal(_session())
    journal.record(_receipt("in_progress", 1), event_index=1)
    partial = _receipt("partial_failure", 1, failure_code="REMOTE_FAILURE")
    journal.record(partial, event_index=2)
    state = journal.recovery_state(_plan())
    assert state.classification == "resumable_partial"
    assert state.completed_actions == ("create_branch",)
    assert state.next_action == "create_commit"


def test_identical_replay_is_idempotent_and_divergent_replay_fails() -> None:
    journal = DurableGitProposalMutationJournal(_session())
    original = _receipt("in_progress", 1)
    assert journal.record(original, event_index=1) == journal.record(original, event_index=1)
    divergent = _receipt("partial_failure", 1, failure_code="OTHER")
    with pytest.raises(ValueError, match="DIVERGENT_REPLAY"):
        journal.record(divergent, event_index=1)


def test_payload_and_row_tampering_fail_closed() -> None:
    session = _session()
    journal = DurableGitProposalMutationJournal(session)
    journal.record(_receipt("in_progress", 1), event_index=1)
    row = session.scalar(select(GitProposalMutationJournalEventRecord))
    assert row is not None
    payload = json.loads(row.payload_json)
    payload["receipt"]["completed_actions"] = []
    row.payload_json = json.dumps(payload)
    session.commit()
    with pytest.raises(PermissionError):
        journal.latest(plan_digest=_plan().plan_digest)


def test_evidence_digest_tampering_fails_closed() -> None:
    receipt = _receipt("in_progress", 1)
    snapshot = receipt.snapshot()
    snapshot["operation_evidence"][0]["evidence_digest"] = "0" * 64
    with pytest.raises(PermissionError, match="RECEIPT_DIGEST_MISMATCH|EVIDENCE_DIGEST_MISMATCH"):
        DurableGitProposalMutationJournal._validate_snapshot(snapshot)


def test_executor_rejects_journal_that_does_not_return_exact_receipt() -> None:
    class BadJournal:
        def record(self, receipt, *, event_index):
            del event_index
            return _receipt("failed", 0, failure_code="tampered")

    executor = GitProposalMutationExecutor(
        adapter=object(),
        repository_allowlist=(REPOSITORY,),
        journal=BadJournal(),
    )
    with pytest.raises(PermissionError, match="JOURNAL_MISMATCH"):
        executor._record(_receipt("in_progress", 1), event_index=1)
