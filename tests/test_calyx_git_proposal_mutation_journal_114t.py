from __future__ import annotations

import json
from datetime import timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

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
from tests.test_calyx_git_proposal_execution_plan_114r import BASE_REF, NOW, REPOSITORY
from tests.test_calyx_git_proposal_mutation_executor_114s import (
    FakeMutationAdapter,
    _execution_inputs,
)


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[GitProposalMutationJournalEventRecord.__table__],
    )
    return Session(engine)


def _receipt(
    plan,
    status: str,
    count: int,
    *,
    failure_code: str | None = None,
) -> GitProposalMutationReceipt:
    actions = tuple(operation.action for operation in plan.operations[:count])
    evidence = []
    for action in actions:
        payload = {
            "action": action,
            "status": "created",
            "repository": plan.repository,
            "branch": plan.proposed_branch,
        }
        if action == "create_branch":
            payload["base_commit_sha"] = plan.base_commit_sha
        elif action == "create_commit":
            payload.update(
                {
                    "parent_commit_sha": plan.base_commit_sha,
                    "commit_sha": "9" * 40,
                    "patch_program_job_id": plan.patch_program_job_id,
                    "change_hashes": [
                        {"path": path, "after_sha256": digest}
                        for path, digest in plan.change_hashes
                    ],
                }
            )
        elif action == "push_branch":
            payload["commit_sha"] = "9" * 40
        elif action == "open_pull_request":
            payload.update(
                {
                    "head_branch": plan.proposed_branch,
                    "base_ref": plan.base_ref,
                    "base_commit_sha": plan.base_commit_sha,
                    "head_commit_sha": "9" * 40,
                    "pull_request_number": 1234,
                }
            )
        evidence.append(
            GitProposalOperationEvidence(
                action=action,
                status="created",
                evidence_digest=canonical_sha256(payload),
                payload=payload,
            )
        )
    return GitProposalMutationReceipt(
        plan_digest=plan.plan_digest,
        patch_program_job_id=plan.patch_program_job_id,
        repository=plan.repository,
        proposed_branch=plan.proposed_branch,
        base_commit_sha=plan.base_commit_sha,
        base_ref=plan.base_ref,
        status=status,
        completed_actions=actions,
        operation_evidence=tuple(evidence),
        failure_code=failure_code,
    )


def test_progress_and_completed_receipts_survive_restart() -> None:
    _, _, _, _, _, plan, _ = _execution_inputs()
    session = _session()
    journal = DurableGitProposalMutationJournal(session)
    for index in range(1, 5):
        journal.record(_receipt(plan, "in_progress", index), event_index=index)
    final = journal.record(_receipt(plan, "completed", 4), event_index=5)

    restarted = DurableGitProposalMutationJournal(session)
    assert restarted.latest(plan_digest=plan.plan_digest) == final
    state = restarted.recovery_state(plan)
    assert state.classification == "completed"
    assert state.next_action is None
    assert state.terminal is True
    assert restarted.next_event_index(plan_digest=plan.plan_digest) == 6


def test_partial_failure_is_explicitly_resumable() -> None:
    _, _, _, _, _, plan, _ = _execution_inputs()
    journal = DurableGitProposalMutationJournal(_session())
    journal.record(_receipt(plan, "in_progress", 1), event_index=1)
    journal.record(
        _receipt(plan, "partial_failure", 1, failure_code="REMOTE_FAILURE"),
        event_index=2,
    )
    state = journal.recovery_state(plan)
    assert state.classification == "resumable_partial"
    assert state.completed_actions == ("create_branch",)
    assert state.next_action == "create_commit"
    assert state.terminal is False

    resumed = journal.record(_receipt(plan, "in_progress", 2), event_index=3)
    assert resumed.completed_actions == ("create_branch", "create_commit")


def test_failed_before_side_effect_can_resume_without_rewriting_history() -> None:
    _, _, _, _, _, plan, _ = _execution_inputs()
    journal = DurableGitProposalMutationJournal(_session())
    journal.record(
        _receipt(plan, "failed", 0, failure_code="TRANSIENT_FAILURE"),
        event_index=1,
    )
    state = journal.recovery_state(plan)
    assert state.classification == "failed_before_side_effect"
    assert state.next_action == "create_branch"
    assert state.terminal is False
    journal.record(_receipt(plan, "in_progress", 1), event_index=2)


def test_identical_replay_is_idempotent_and_divergent_replay_fails() -> None:
    _, _, _, _, _, plan, _ = _execution_inputs()
    journal = DurableGitProposalMutationJournal(_session())
    original = _receipt(plan, "in_progress", 1)
    assert journal.record(original, event_index=1) == journal.record(
        original,
        event_index=1,
    )
    divergent = _receipt(plan, "partial_failure", 1, failure_code="OTHER")
    with pytest.raises(ValueError, match="DIVERGENT_REPLAY"):
        journal.record(divergent, event_index=1)


def test_payload_row_base_ref_and_patch_job_tampering_fail_closed() -> None:
    _, _, _, _, _, plan, _ = _execution_inputs()
    session = _session()
    journal = DurableGitProposalMutationJournal(session)
    original = _receipt(plan, "in_progress", 1)
    journal.record(original, event_index=1)
    row = session.scalar(select(GitProposalMutationJournalEventRecord))
    assert row is not None

    payload = json.loads(row.payload_json)
    payload["receipt"]["base_ref"] = "release/wrong"
    row.payload_json = json.dumps(payload)
    session.commit()
    with pytest.raises(PermissionError):
        journal.latest(plan_digest=plan.plan_digest)

    row.payload_json = json.dumps(
        {
            "schema": "calyx-git-proposal-mutation-journal-event-v3",
            "event_index": 1,
            "receipt": original.snapshot(),
        }
    )
    row.patch_program_job_id = "other-job"
    session.commit()
    with pytest.raises(PermissionError, match="ROW_IDENTITY_MISMATCH"):
        journal.latest(plan_digest=plan.plan_digest)


def test_event_index_rejects_boolean_gaps_and_appends_after_final() -> None:
    _, _, _, _, _, plan, _ = _execution_inputs()
    journal = DurableGitProposalMutationJournal(_session())
    with pytest.raises(ValueError, match="EVENT_INDEX_INVALID"):
        journal.record(_receipt(plan, "in_progress", 1), event_index=True)
    journal.record(_receipt(plan, "in_progress", 1), event_index=1)
    with pytest.raises(ValueError, match="EVENT_GAP"):
        journal.record(_receipt(plan, "in_progress", 2), event_index=3)
    journal.record(_receipt(plan, "completed_subset", 1), event_index=2)
    with pytest.raises(ValueError, match="FINAL_ALREADY_RECORDED"):
        journal.record(_receipt(plan, "in_progress", 2), event_index=3)


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
    assert [row.event_index for row in rows] == [1, 2, 3, 4, 5]
    assert all(row.patch_program_job_id == patch_job_id for row in rows)
    assert journal.latest(plan_digest=plan.plan_digest) == receipt
    assert receipt.status == "completed"
    assert receipt.base_ref == BASE_REF


def test_executor_restart_resumes_after_verified_partial_failure() -> None:
    session = _session()
    journal = DurableGitProposalMutationJournal(session)
    store, gate, request, grant, manifest, plan, _ = _execution_inputs()

    first_adapter = FakeMutationAdapter(fail_action="create_commit")
    with pytest.raises(GitProposalMutationError):
        GitProposalMutationExecutor(
            adapter=first_adapter,
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
    assert first_adapter.calls == ["create_branch", "create_commit"]

    resumed_adapter = FakeMutationAdapter()
    receipt = GitProposalMutationExecutor(
        adapter=resumed_adapter,
        repository_allowlist=(REPOSITORY,),
        journal=DurableGitProposalMutationJournal(session),
    ).execute(
        plan=plan,
        manifest_snapshot=manifest,
        review_store=store,
        authorization_gate=gate,
        request=request,
        grant_mapping=grant,
        now=NOW + timedelta(minutes=1),
    )
    assert resumed_adapter.calls == [
        "create_commit",
        "push_branch",
        "open_pull_request",
    ]
    assert receipt.status == "completed"
    assert receipt.completed_actions == (
        "create_branch",
        "create_commit",
        "push_branch",
        "open_pull_request",
    )


def test_completed_restart_is_idempotent_without_remote_calls() -> None:
    session = _session()
    journal = DurableGitProposalMutationJournal(session)
    store, gate, request, grant, manifest, plan, _ = _execution_inputs()
    first = FakeMutationAdapter()
    receipt = GitProposalMutationExecutor(
        adapter=first,
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

    second = FakeMutationAdapter()
    replayed = GitProposalMutationExecutor(
        adapter=second,
        repository_allowlist=(REPOSITORY,),
        journal=DurableGitProposalMutationJournal(session),
    ).execute(
        plan=plan,
        manifest_snapshot=manifest,
        review_store=store,
        authorization_gate=gate,
        request=request,
        grant_mapping=grant,
        now=NOW + timedelta(minutes=1),
    )
    assert replayed == receipt
    assert second.calls == []


def test_executor_rejects_journal_that_returns_different_receipt() -> None:
    _, _, _, _, _, plan, _ = _execution_inputs()

    class BadJournal:
        def record(self, receipt, *, event_index):
            del receipt, event_index
            return _receipt(plan, "failed", 0, failure_code="tampered")

        def latest(self, *, plan_digest):
            del plan_digest

        def next_event_index(self, *, plan_digest):
            del plan_digest
            return 1

    executor = GitProposalMutationExecutor(
        adapter=object(),
        repository_allowlist=(REPOSITORY,),
        journal=BadJournal(),
    )
    with pytest.raises(PermissionError, match="JOURNAL_MISMATCH"):
        executor._record(_receipt(plan, "in_progress", 1), event_index=1)
