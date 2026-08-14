from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.calyx_orchestrator.git_proposal_ci_repair import (
    CiCheck,
    CiConclusion,
    CiObservation,
    CiRepairDisposition,
    DurableGitProposalCiRepairJournal,
    GitProposalCiRepairCoordinator,
    GitProposalCiRepairEventRecord,
)
from app.calyx_orchestrator.git_proposal_mutation_executor import (
    GitProposalMutationReceipt,
    GitProposalOperationEvidence,
)
from app.calyx_orchestrator.sandbox_supervisor_evidence import canonical_sha256

REPOSITORY = "jsp1440/orchid-calyx-backend"
BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40
CORRECTED_SHA = "3" * 40
PLAN_DIGEST = "a" * 64
PATCH_JOB = "patch-job-114u-ci"
BRANCH = "autonomy/proposal/ci-repair-fixture"
PR_NUMBER = 4242
NOW = datetime(2026, 8, 13, 19, 0, tzinfo=UTC).isoformat()


def _evidence(action: str, payload: dict[str, object]) -> GitProposalOperationEvidence:
    return GitProposalOperationEvidence(
        action=action,
        status="created",
        evidence_digest=canonical_sha256(payload),
        payload=payload,
    )


def _receipt() -> GitProposalMutationReceipt:
    branch = {
        "action": "create_branch",
        "status": "created",
        "repository": REPOSITORY,
        "branch": BRANCH,
        "base_commit_sha": BASE_SHA,
    }
    commit = {
        "action": "create_commit",
        "status": "created",
        "repository": REPOSITORY,
        "branch": BRANCH,
        "parent_commit_sha": BASE_SHA,
        "commit_sha": HEAD_SHA,
        "patch_program_job_id": PATCH_JOB,
        "change_hashes": [],
    }
    push = {
        "action": "push_branch",
        "status": "created",
        "repository": REPOSITORY,
        "branch": BRANCH,
        "commit_sha": HEAD_SHA,
    }
    pr = {
        "action": "open_pull_request",
        "status": "created",
        "repository": REPOSITORY,
        "branch": BRANCH,
        "base_ref": "main",
        "base_commit_sha": BASE_SHA,
        "head_branch": BRANCH,
        "head_commit_sha": HEAD_SHA,
        "pull_request_number": PR_NUMBER,
        "pull_request_url": f"https://github.com/{REPOSITORY}/pull/{PR_NUMBER}",
        "draft": True,
    }
    return GitProposalMutationReceipt(
        plan_digest=PLAN_DIGEST,
        patch_program_job_id=PATCH_JOB,
        repository=REPOSITORY,
        proposed_branch=BRANCH,
        base_commit_sha=BASE_SHA,
        base_ref="main",
        status="completed",
        completed_actions=(
            "create_branch",
            "create_commit",
            "push_branch",
            "open_pull_request",
        ),
        operation_evidence=(
            _evidence("create_branch", branch),
            _evidence("create_commit", commit),
            _evidence("push_branch", push),
            _evidence("open_pull_request", pr),
        ),
        failure_code=None,
    )


def _observation(
    *conclusions: CiConclusion,
    head_sha: str = HEAD_SHA,
    repository: str = REPOSITORY,
    pr_number: int = PR_NUMBER,
) -> CiObservation:
    return CiObservation(
        repository=repository,
        pull_request_number=pr_number,
        head_sha=head_sha,
        checks=tuple(
            CiCheck(
                check_id=f"check-{index}",
                name=f"validation-{index}",
                conclusion=conclusion,
                details_url=f"https://example.invalid/check/{index}",
            )
            for index, conclusion in enumerate(conclusions, start=1)
        ),
        observed_at=NOW,
    )


def _journal() -> tuple[Session, DurableGitProposalCiRepairJournal]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    GitProposalCiRepairEventRecord.__table__.create(engine)
    db = Session(engine)
    return db, DurableGitProposalCiRepairJournal(db)


def test_green_ci_is_owner_merge_ready_without_mutation() -> None:
    decision = GitProposalCiRepairCoordinator().evaluate(
        mutation_receipt=_receipt(),
        observation=_observation(CiConclusion.SUCCESS, CiConclusion.SKIPPED),
    )

    assert decision.disposition == CiRepairDisposition.READY_FOR_OWNER_MERGE
    assert decision.assignment is None
    snapshot = decision.snapshot()
    assert snapshot["merge_performed"] is False
    assert snapshot["remote_git_mutation_performed"] is False


def test_pending_ci_waits_without_repair_assignment() -> None:
    decision = GitProposalCiRepairCoordinator().evaluate(
        mutation_receipt=_receipt(),
        observation=_observation(CiConclusion.SUCCESS, CiConclusion.PENDING),
    )

    assert decision.disposition == CiRepairDisposition.WAITING
    assert decision.code == "CI_REPAIR_CHECKS_PENDING"
    assert decision.assignment is None


def test_failed_ci_creates_deterministic_governed_assignment_and_durable_evidence() -> None:
    db, journal = _journal()
    try:
        observation = _observation(CiConclusion.FAILURE, CiConclusion.SUCCESS)
        coordinator = GitProposalCiRepairCoordinator()

        first = coordinator.evaluate(
            mutation_receipt=_receipt(), observation=observation, journal=journal
        )
        second = coordinator.evaluate(
            mutation_receipt=_receipt(), observation=observation, journal=journal
        )

        assert first.disposition == CiRepairDisposition.REPAIR_REQUIRED
        assert first.assignment is not None
        assert second.assignment == first.assignment
        records = db.scalars(select(GitProposalCiRepairEventRecord)).all()
        assert len(records) == 1
        assignment = first.assignment.snapshot()
        assert assignment["assignment_kind"] == "governed_corrective_engineering"
        assert assignment["requires_authoritative_coding_executor"] is True
        assert assignment["requires_fresh_validation_receipts"] is True
        assert assignment["requires_fresh_owner_authorization_for_git_mutation"] is True
        assert assignment["automatic_merge_authorized"] is False
    finally:
        db.close()


def test_stale_or_moved_head_fails_closed_before_assignment() -> None:
    decision = GitProposalCiRepairCoordinator().evaluate(
        mutation_receipt=_receipt(),
        observation=_observation(CiConclusion.FAILURE, head_sha="9" * 40),
    )

    assert decision.disposition == CiRepairDisposition.BLOCKED
    assert decision.code == "CI_REPAIR_STALE_OR_MOVED_HEAD"
    assert decision.assignment is None


@pytest.mark.parametrize(
    ("repository", "pr_number", "code"),
    [
        ("jsp1440/not-the-repo", PR_NUMBER, "CI_REPAIR_REPOSITORY_MISMATCH"),
        (REPOSITORY, PR_NUMBER + 1, "CI_REPAIR_PULL_REQUEST_MISMATCH"),
    ],
)
def test_observation_identity_mismatch_fails_closed(
    repository: str, pr_number: int, code: str
) -> None:
    decision = GitProposalCiRepairCoordinator().evaluate(
        mutation_receipt=_receipt(),
        observation=_observation(
            CiConclusion.FAILURE, repository=repository, pr_number=pr_number
        ),
    )

    assert decision.disposition == CiRepairDisposition.BLOCKED
    assert decision.code == code


def test_non_draft_or_incomplete_proposal_receipt_cannot_enter_ci_loop() -> None:
    receipt = _receipt()
    incomplete = GitProposalMutationReceipt(
        plan_digest=receipt.plan_digest,
        patch_program_job_id=receipt.patch_program_job_id,
        repository=receipt.repository,
        proposed_branch=receipt.proposed_branch,
        base_commit_sha=receipt.base_commit_sha,
        base_ref=receipt.base_ref,
        status="completed_subset",
        completed_actions=("create_branch", "create_commit", "push_branch"),
        operation_evidence=receipt.operation_evidence[:3],
        failure_code=None,
    )

    decision = GitProposalCiRepairCoordinator().evaluate(
        mutation_receipt=incomplete,
        observation=_observation(CiConclusion.FAILURE),
    )

    assert decision.disposition == CiRepairDisposition.BLOCKED
    assert decision.code == "CI_REPAIR_DRAFT_PR_EVIDENCE_REQUIRED"


def test_revalidation_requires_advanced_head_and_authoritative_receipt_digest() -> None:
    db, journal = _journal()
    try:
        failed = GitProposalCiRepairCoordinator().evaluate(
            mutation_receipt=_receipt(),
            observation=_observation(CiConclusion.FAILURE),
            journal=journal,
        )
        assert failed.assignment is not None

        with pytest.raises(PermissionError, match="HEAD_NOT_ADVANCED"):
            journal.record_revalidation(
                assignment=failed.assignment,
                observation=_observation(CiConclusion.SUCCESS),
                authoritative_corrective_receipt_digest="b" * 64,
            )
        with pytest.raises(ValueError, match="CORRECTIVE_RECEIPT_DIGEST_INVALID"):
            journal.record_revalidation(
                assignment=failed.assignment,
                observation=_observation(CiConclusion.SUCCESS, head_sha=CORRECTED_SHA),
                authoritative_corrective_receipt_digest="bad",
            )

        corrected = _observation(CiConclusion.SUCCESS, head_sha=CORRECTED_SHA)
        event = journal.record_revalidation(
            assignment=failed.assignment,
            observation=corrected,
            authoritative_corrective_receipt_digest="b" * 64,
        )
        replay = journal.record_revalidation(
            assignment=failed.assignment,
            observation=corrected,
            authoritative_corrective_receipt_digest="b" * 64,
        )
        assert replay.event_id == event.event_id
        assert event.event_kind == "revalidation"
        assert event.head_sha == CORRECTED_SHA
        assert '"owner_merge_ready":true' in event.payload_json
        assert '"merge_performed":false' in event.payload_json
    finally:
        db.close()


@pytest.mark.parametrize("conclusion", [CiConclusion.PENDING, CiConclusion.FAILURE])
def test_revalidation_refuses_non_green_corrected_head(conclusion: CiConclusion) -> None:
    db, journal = _journal()
    try:
        failed = GitProposalCiRepairCoordinator().evaluate(
            mutation_receipt=_receipt(),
            observation=_observation(CiConclusion.FAILURE),
            journal=journal,
        )
        assert failed.assignment is not None

        with pytest.raises(PermissionError, match="REVALIDATION_CHECKS_NOT_GREEN"):
            journal.record_revalidation(
                assignment=failed.assignment,
                observation=_observation(conclusion, head_sha=CORRECTED_SHA),
                authoritative_corrective_receipt_digest="b" * 64,
            )
    finally:
        db.close()


def test_changed_revalidation_evidence_conflicts_instead_of_overwriting_history() -> None:
    db, journal = _journal()
    try:
        failed = GitProposalCiRepairCoordinator().evaluate(
            mutation_receipt=_receipt(),
            observation=_observation(CiConclusion.FAILURE),
            journal=journal,
        )
        assert failed.assignment is not None
        corrected = _observation(CiConclusion.SUCCESS, head_sha=CORRECTED_SHA)
        journal.record_revalidation(
            assignment=failed.assignment,
            observation=corrected,
            authoritative_corrective_receipt_digest="b" * 64,
        )

        with pytest.raises(PermissionError, match="IDEMPOTENCY_CONFLICT"):
            journal.record_revalidation(
                assignment=failed.assignment,
                observation=corrected,
                authoritative_corrective_receipt_digest="c" * 64,
            )
    finally:
        db.close()
