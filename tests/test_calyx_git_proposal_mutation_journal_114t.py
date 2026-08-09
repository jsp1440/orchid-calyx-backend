from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.calyx_orchestrator.git_proposal_execution_plan import (
    GitProposalExecutionPlan,
    GitProposalPlanOperation,
)
from app.calyx_orchestrator.git_proposal_mutation_executor import (
    GitProposalMutationError,
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
from tests.test_calyx_git_proposal_execution_plan_114r import NOW, REPOSITORY
from tests.test_calyx_git_proposal_mutation_executor_114s import (
    FakeMutationAdapter,
    _execution_inputs,
)

PATCH_JOB = "program-job-123"
BASE = "b" * 40
BRANCH = "autonomy/proposal/work-123"


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[GitProposalMutationJournalEventRecord.__table__],
    )
    return Session(engine)


def _plan() -> GitProposalExecutionPlan:
    operations = (
        GitProposalPlanOperation("create_branch", {}),
        GitProposalPlanOperation(
            "create_commit",
            {"patch_program_job_id": PATCH_JOB},
        ),
        GitProposalPlanOperation("push_branch", {}),
        GitProposalPlanOperation("open_pull_request", {}),
    )
    return GitProposalExecutionPlan(
        manifest_digest="1" * 64,
        patch_program_job_id=PATCH_JOB,
        authorization_request_digest="2" * 64,
        repository=REPOSITORY,
        base_commit_sha=BASE,
        proposed_branch=BRANCH,
        change_hashes=(("app/example.py", "3" * 64),),
        validation_receipt_digests=("4" * 64,),
        review_authorization_digests=("5" * 64, "6" * 64),
        owner_approved_by="principal:owner",
        owner_grant_expires_at="2026-08-09T23:00:00+00:00",
        owner_grant_signature_digest="7" * 64,
        commit_title="Bounded change",
        pr_title="Bounded change",
        summary="Proposal evidence.",
        operations=operations,
    )


def _evidence(action: str) -> GitProposalOperationEvidence:
    payload = {
        "action": action,
        "status": "created",
        "repository": REPOSITORY,
        "branch": BRANCH,
    }
    return GitProposalOperationEvidence(
        action=action,
        status="created",
        evidence_digest=canonical_sha256(payload),
        payload=payload,
    )


def _receipt(
    status: str,
    count: int,
    *,
    failure_code: str | None = None,
) -> GitProposalMutationReceipt:
    plan = _plan()
    actions = tuple(operation.action for operation in plan.operations[:count])
    evidence = tuple(_evidence(action) for action in actions)
    return GitProposalMutationReceipt(
        plan_digest=plan.plan_digest,
        patch_program_job_id=PATCH_JOB,
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
    first.record(_receipt("in_progress", 3), event_index=3)
    first.record(_receipt("in_progress", 4), event_index=4)
    final = first.record(_receipt("completed", 4), event_index=5)

    restarted = DurableGitProposalMutationJournal(session)
    assert restarted.latest(plan_digest=_plan().plan_digest) == final
    state = restarted.recovery_state(_plan())
    assert state.classification == "completed"
    assert state.patch_program_job_id == PATCH_JOB
    assert state.next_action is None
    assert state.terminal is True


def test_partial_failure_reloads_with_exact_next_action() -> None:
    journal = DurableGitProposalMutationJournal(_session())
    journal.record(_receipt("in_progress", 1), event_index=1)
    partial = _receipt("partial_failure", 1, failure_code="REMOTE_FAILURE")
    journal.record(partial, event_index=2)
    state = journal.recovery_state(_plan())
    assert state.classification == "resumable_partial"
    assert state.completed_actions == ("create_branch",)
    assert state.next_action == "create_commit"
    assert state.terminal is True


def test_identical_replay_is_idempotent_and_divergent_replay_fails() -> None:
    journal = DurableGitProposalMutationJournal(_session())
    original = _receipt("in_progress", 1)
    assert journal.record(original, event_index=1) == journal.record(
        original,
        event_index=1,
    )
    divergent = _receipt("partial_failure", 1, failure_code="OTHER")
    with pytest.raises(ValueError, match="DIVERGENT_REPLAY"):
        journal.record(divergent, event_index=1)


def test_payload_row_and_patch_job_tampering_fail_closed() -> None:
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

    session.rollback()
    row.payload_json = json.dumps(
        {
            "schema": "calyx-git-proposal-mutation-journal-event-v2",
            "event_index": 1,
            "receipt": _receipt("in_progress", 1).snapshot(),
        }
    )
    row.patch_program_job_id = "other-job"
    session.commit()
    with pytest.raises(PermissionError, match="ROW_IDENTITY_MISMATCH"):
        journal.latest(plan_digest=_plan().plan_digest)


def test_evidence_digest_and_history_changes_fail_closed() -> None:
    receipt = _receipt("in_progress", 1)
    snapshot = receipt.snapshot()
    snapshot["operation_evidence"][0]["evidence_digest"] = "0" * 64
    with pytest.raises(
        PermissionError,
        match="RECEIPT_DIGEST_MISMATCH|EVIDENCE_DIGEST_MISMATCH",
    ):
        DurableGitProposalMutationJournal._validate_snapshot(snapshot)

    journal = DurableGitProposalMutationJournal(_session())
    journal.record(_receipt("in_progress", 1), event_index=1)
    changed = _receipt("in_progress", 2)
    changed_first = GitProposalOperationEvidence(
        action="create_branch",
        status="already_exists_exact",
        evidence_digest=changed.operation_evidence[0].evidence_digest,
        payload=changed.operation_evidence[0].payload,
    )
    altered = GitProposalMutationReceipt(
        plan_digest=changed.plan_digest,
        patch_program_job_id=changed.patch_program_job_id,
        repository=changed.repository,
        proposed_branch=changed.proposed_branch,
        base_commit_sha=changed.base_commit_sha,
        status=changed.status,
        completed_actions=changed.completed_actions,
        operation_evidence=(changed_first, changed.operation_evidence[1]),
        failure_code=None,
    )
    with pytest.raises(ValueError, match="EVIDENCE_HISTORY_CHANGED"):
        journal.record(altered, event_index=2)


def test_event_index_rejects_boolean_and_gaps() -> None:
    journal = DurableGitProposalMutationJournal(_session())
    with pytest.raises(ValueError, match="EVENT_INDEX_INVALID"):
        journal.record(_receipt("in_progress", 1), event_index=True)
    journal.record(_receipt("in_progress", 1), event_index=1)
    with pytest.raises(ValueError, match="EVENT_GAP"):
        journal.record(_receipt("in_progress", 2), event_index=3)


def test_executor_persists_verified_progress_and_final_receipt() -> None:
    session = _session()
    journal = DurableGitProposalMutationJournal(session)
    store, gate, request, grant, manifest, plan, patch_job_id = _execution_inputs()
    receipt = GitProposalMutationExecutor(
        adapter=FakeMutationAdapter(),
        repository_allowlist=(REPOSITORY,),
        journal=journal,
    ).execute(
        plan=plan,
        manifest_snapshot=manifest,
        review_store=store,
        authorization_gate=gate,
        request=request,
        grant_mapping=grant,
        now=NOW + timedelta(minutes=1),
    )
    rows = session.scalars(
        select(GitProposalMutationJournalEventRecord).order_by(
            GitProposalMutationJournalEventRecord.event_index
        )
    ).all()
    assert len(rows) == 5
    assert [row.event_index for row in rows] == [1, 2, 3, 4, 5]
    assert all(row.patch_program_job_id == patch_job_id for row in rows)
    assert journal.latest(plan_digest=plan.plan_digest) == receipt
    assert receipt.status == "completed"


def test_executor_persists_partial_failure_before_raising() -> None:
    session = _session()
    journal = DurableGitProposalMutationJournal(session)
    store, gate, request, grant, manifest, plan, _ = _execution_inputs()
    executor = GitProposalMutationExecutor(
        adapter=FakeMutationAdapter(fail_action="create_commit"),
        repository_allowlist=(REPOSITORY,),
        journal=journal,
    )
    with pytest.raises(GitProposalMutationError):
        executor.execute(
            plan=plan,
            manifest_snapshot=manifest,
            review_store=store,
            authorization_gate=gate,
            request=request,
            grant_mapping=grant,
            now=NOW + timedelta(minutes=1),
        )
    latest = journal.latest(plan_digest=plan.plan_digest)
    assert latest is not None
    assert latest.status == "partial_failure"
    assert latest.completed_actions == ("create_branch",)
    state = journal.recovery_state(plan)
    assert state.classification == "resumable_partial"
    assert state.next_action == "create_commit"


def test_executor_rejects_journal_that_does_not_return_exact_receipt() -> None:
    class BadJournal:
        def record(self, receipt, *, event_index):
            del receipt, event_index
            return _receipt("failed", 0, failure_code="tampered")

    executor = GitProposalMutationExecutor(
        adapter=object(),
        repository_allowlist=(REPOSITORY,),
        journal=BadJournal(),
    )
    with pytest.raises(PermissionError, match="JOURNAL_MISMATCH"):
        executor._record(_receipt("in_progress", 1), event_index=1)
