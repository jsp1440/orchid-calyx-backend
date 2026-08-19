from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base

from .git_proposal_mutation_executor import (
    FINAL_ACTION,
    FINAL_STATUSES,
    GitProposalMutationReceipt,
)
from .git_proposal_mutation_journal import (
    DurableGitProposalMutationJournal,
    GitProposalMutationJournalEventRecord,
)
from .models import utcnow
from .sandbox_supervisor_evidence import canonical_sha256

SCHEMA = "calyx-git-proposal-ci-repair-v1"
JOURNAL_SCHEMA = "calyx-git-proposal-ci-repair-journal-v1"


class CiConclusion(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class CiRepairDisposition(StrEnum):
    WAITING = "waiting"
    READY_FOR_OWNER_MERGE = "ready_for_owner_merge"
    REPAIR_REQUIRED = "repair_required"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class CiCheck:
    check_id: str
    name: str
    conclusion: CiConclusion
    details_url: str | None = None

    def __post_init__(self) -> None:
        if not self.check_id.strip():
            raise ValueError("CI_CHECK_ID_REQUIRED")
        if not self.name.strip():
            raise ValueError("CI_CHECK_NAME_REQUIRED")

    def snapshot(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "name": self.name,
            "conclusion": self.conclusion.value,
            "details_url": self.details_url,
        }


@dataclass(frozen=True, slots=True)
class CiObservation:
    repository: str
    pull_request_number: int
    head_sha: str
    checks: tuple[CiCheck, ...]
    observed_at: str

    def __post_init__(self) -> None:
        if not self.repository.strip():
            raise ValueError("CI_OBSERVATION_REPOSITORY_REQUIRED")
        if type(self.pull_request_number) is not int or self.pull_request_number <= 0:
            raise ValueError("CI_OBSERVATION_PULL_REQUEST_NUMBER_INVALID")
        if not _is_git_sha(self.head_sha):
            raise ValueError("CI_OBSERVATION_HEAD_SHA_INVALID")
        if not self.checks:
            raise ValueError("CI_OBSERVATION_CHECKS_REQUIRED")
        check_ids = [check.check_id for check in self.checks]
        if len(check_ids) != len(set(check_ids)):
            raise ValueError("CI_OBSERVATION_DUPLICATE_CHECK_ID")
        if not self.observed_at.strip():
            raise ValueError("CI_OBSERVATION_TIMESTAMP_REQUIRED")

    @property
    def observation_digest(self) -> str:
        return canonical_sha256(self.snapshot(include_digest=False))

    def snapshot(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "repository": self.repository,
            "pull_request_number": self.pull_request_number,
            "head_sha": self.head_sha,
            "checks": [check.snapshot() for check in self.checks],
            "observed_at": self.observed_at,
        }
        if include_digest:
            payload["observation_digest"] = canonical_sha256(payload)
        return payload


@dataclass(frozen=True, slots=True)
class CiRequiredCheckRoster:
    """Authoritative required-check identity captured from GitHub rules/protection."""

    repository: str
    pull_request_number: int
    head_sha: str
    check_ids: tuple[str, ...]
    source: str
    observed_at: str

    def __post_init__(self) -> None:
        if not self.repository.strip():
            raise ValueError("CI_REQUIRED_CHECK_ROSTER_REPOSITORY_REQUIRED")
        if type(self.pull_request_number) is not int or self.pull_request_number <= 0:
            raise ValueError("CI_REQUIRED_CHECK_ROSTER_PULL_REQUEST_NUMBER_INVALID")
        if not _is_git_sha(self.head_sha):
            raise ValueError("CI_REQUIRED_CHECK_ROSTER_HEAD_SHA_INVALID")
        normalized = tuple(item.strip() for item in self.check_ids if item.strip())
        if not normalized:
            raise ValueError("CI_REQUIRED_CHECK_ROSTER_EMPTY")
        if len(normalized) != len(set(normalized)) or normalized != self.check_ids:
            raise ValueError("CI_REQUIRED_CHECK_ROSTER_CHECK_IDS_INVALID")
        if self.source not in {"github_branch_protection", "github_rulesets"}:
            raise ValueError("CI_REQUIRED_CHECK_ROSTER_SOURCE_INVALID")
        if not self.observed_at.strip():
            raise ValueError("CI_REQUIRED_CHECK_ROSTER_TIMESTAMP_REQUIRED")

    @property
    def roster_digest(self) -> str:
        return canonical_sha256(self.snapshot(include_digest=False))

    @property
    def policy_digest(self) -> str:
        return canonical_sha256(
            {
                "repository": self.repository,
                "pull_request_number": self.pull_request_number,
                "check_ids": list(self.check_ids),
                "source": self.source,
            }
        )

    def snapshot(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "repository": self.repository,
            "pull_request_number": self.pull_request_number,
            "head_sha": self.head_sha,
            "check_ids": list(self.check_ids),
            "source": self.source,
            "observed_at": self.observed_at,
        }
        if include_digest:
            payload["roster_digest"] = canonical_sha256(payload)
            payload["policy_digest"] = self.policy_digest
        return payload


@dataclass(frozen=True, slots=True)
class CiRepairAssignment:
    repair_key: str
    source_plan_digest: str
    source_mutation_receipt_digest: str
    patch_program_job_id: str
    repository: str
    proposed_branch: str
    pull_request_number: int
    failed_head_sha: str
    failed_checks: tuple[Mapping[str, Any], ...]
    observation_digest: str
    required_check_policy_digest: str

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            **asdict(self),
            "failed_checks": [dict(item) for item in self.failed_checks],
            "assignment_kind": "governed_corrective_engineering",
            "requires_authoritative_coding_executor": True,
            "requires_fresh_validation_receipts": True,
            "requires_fresh_owner_authorization_for_git_mutation": True,
            "merge_authorized": False,
            "automatic_merge_authorized": False,
            "deployment_authorized": False,
            "publication_authorized": False,
            "taxonomy_activation_authorized": False,
            "production_database_mutation_authorized": False,
            "production_graph_mutation_authorized": False,
        }


@dataclass(frozen=True, slots=True)
class CiRepairDecision:
    disposition: CiRepairDisposition
    code: str
    assignment: CiRepairAssignment | None
    observation_digest: str
    source_mutation_receipt_digest: str

    def snapshot(self) -> dict[str, Any]:
        return {
            "schema": SCHEMA,
            "disposition": self.disposition.value,
            "code": self.code,
            "assignment": self.assignment.snapshot() if self.assignment else None,
            "observation_digest": self.observation_digest,
            "source_mutation_receipt_digest": self.source_mutation_receipt_digest,
            "merge_performed": False,
            "remote_git_mutation_performed": False,
        }


class CorrectiveMutationReceiptResolver(Protocol):
    def resolve(self, *, receipt_digest: str) -> GitProposalMutationReceipt | None: ...


class DurableCorrectiveMutationReceiptResolver:
    """Resolve an exact mutation receipt from the tamper-checked durable journal."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def resolve(self, *, receipt_digest: str) -> GitProposalMutationReceipt | None:
        digest = receipt_digest.strip().lower()
        if not _is_sha256(digest):
            raise ValueError("CI_REPAIR_CORRECTIVE_RECEIPT_DIGEST_INVALID")
        rows = list(
            self.db.scalars(
                select(GitProposalMutationJournalEventRecord)
                .where(GitProposalMutationJournalEventRecord.receipt_digest == digest)
                .limit(2)
            ).all()
        )
        if not rows:
            return None
        if len(rows) != 1:
            raise PermissionError("CI_REPAIR_CORRECTIVE_RECEIPT_AMBIGUOUS")
        return DurableGitProposalMutationJournal._decode(rows[0])


class GitProposalCiRepairEventRecord(Base):
    __tablename__ = "calyx_git_proposal_ci_repair_events"
    __table_args__ = (
        UniqueConstraint(
            "repair_key", "event_kind", name="uq_calyx_ci_repair_key_kind"
        ),
        UniqueConstraint("event_digest", name="uq_calyx_ci_repair_event_digest"),
    )

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    repair_key: Mapped[str] = mapped_column(String(64), index=True)
    event_kind: Mapped[str] = mapped_column(String(40), index=True)
    source_plan_digest: Mapped[str] = mapped_column(String(64), index=True)
    source_receipt_digest: Mapped[str] = mapped_column(String(64), index=True)
    repository: Mapped[str] = mapped_column(String(240), index=True)
    proposed_branch: Mapped[str] = mapped_column(String(240))
    pull_request_number: Mapped[int] = mapped_column(Integer, index=True)
    head_sha: Mapped[str] = mapped_column(String(40), index=True)
    payload_json: Mapped[str] = mapped_column(Text)
    event_digest: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )


class DurableGitProposalCiRepairJournal:
    """Append-only, idempotent CI repair evidence persisted independently of GitHub."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def record_assignment(
        self,
        assignment: CiRepairAssignment,
    ) -> GitProposalCiRepairEventRecord:
        payload = assignment.snapshot()
        return self._record(
            repair_key=assignment.repair_key,
            event_kind="assignment",
            source_plan_digest=assignment.source_plan_digest,
            source_receipt_digest=assignment.source_mutation_receipt_digest,
            repository=assignment.repository,
            proposed_branch=assignment.proposed_branch,
            pull_request_number=assignment.pull_request_number,
            head_sha=assignment.failed_head_sha,
            payload=payload,
        )

    def record_revalidation(
        self,
        *,
        assignment: CiRepairAssignment,
        observation: CiObservation,
        required_checks: CiRequiredCheckRoster,
        authoritative_corrective_receipt_digest: str,
        corrective_receipts: CorrectiveMutationReceiptResolver,
    ) -> GitProposalCiRepairEventRecord:
        digest = authoritative_corrective_receipt_digest.strip().lower()
        if not _is_sha256(digest):
            raise ValueError("CI_REPAIR_CORRECTIVE_RECEIPT_DIGEST_INVALID")
        if observation.repository != assignment.repository:
            raise PermissionError("CI_REPAIR_REVALIDATION_REPOSITORY_MISMATCH")
        if observation.pull_request_number != assignment.pull_request_number:
            raise PermissionError("CI_REPAIR_REVALIDATION_PULL_REQUEST_MISMATCH")
        if observation.head_sha == assignment.failed_head_sha:
            raise PermissionError("CI_REPAIR_REVALIDATION_HEAD_NOT_ADVANCED")
        required_state = _required_check_state(observation, required_checks)
        if required_state == "identity_mismatch":
            raise PermissionError("CI_REPAIR_REVALIDATION_REQUIRED_ROSTER_MISMATCH")
        if required_state == "incomplete":
            raise PermissionError("CI_REPAIR_REVALIDATION_REQUIRED_CHECKS_INCOMPLETE")
        if required_state != "green":
            raise PermissionError("CI_REPAIR_REVALIDATION_CHECKS_NOT_GREEN")
        if required_checks.policy_digest != assignment.required_check_policy_digest:
            raise PermissionError("CI_REPAIR_REVALIDATION_REQUIRED_POLICY_CHANGED")

        corrective_receipt = corrective_receipts.resolve(receipt_digest=digest)
        if corrective_receipt is None:
            raise PermissionError("CI_REPAIR_CORRECTIVE_RECEIPT_NOT_FOUND")
        _verify_corrective_receipt(
            assignment=assignment,
            observation=observation,
            corrective_receipt=corrective_receipt,
            expected_digest=digest,
        )
        payload = {
            "schema": JOURNAL_SCHEMA,
            "repair_key": assignment.repair_key,
            "observation": observation.snapshot(),
            "required_checks": required_checks.snapshot(),
            "authoritative_corrective_receipt_digest": digest,
            "corrective_plan_digest": corrective_receipt.plan_digest,
            "owner_merge_ready": True,
            "merge_performed": False,
        }
        return self._record(
            repair_key=assignment.repair_key,
            event_kind="revalidation",
            source_plan_digest=assignment.source_plan_digest,
            source_receipt_digest=assignment.source_mutation_receipt_digest,
            repository=assignment.repository,
            proposed_branch=assignment.proposed_branch,
            pull_request_number=assignment.pull_request_number,
            head_sha=observation.head_sha,
            payload=payload,
        )

    def latest(self, *, repair_key: str) -> GitProposalCiRepairEventRecord | None:
        return self.db.scalar(
            select(GitProposalCiRepairEventRecord)
            .where(GitProposalCiRepairEventRecord.repair_key == repair_key)
            .order_by(GitProposalCiRepairEventRecord.event_id.desc())
            .limit(1)
        )

    def _record(
        self,
        *,
        repair_key: str,
        event_kind: str,
        source_plan_digest: str,
        source_receipt_digest: str,
        repository: str,
        proposed_branch: str,
        pull_request_number: int,
        head_sha: str,
        payload: Mapping[str, Any],
    ) -> GitProposalCiRepairEventRecord:
        canonical_payload = json.dumps(
            dict(payload), sort_keys=True, separators=(",", ":")
        )
        event_digest = canonical_sha256(
            {
                "repair_key": repair_key,
                "event_kind": event_kind,
                "payload": dict(payload),
            }
        )
        existing = self._existing(repair_key=repair_key, event_kind=event_kind)
        if existing is not None:
            return self._verify_exact_replay(
                existing,
                event_digest=event_digest,
                canonical_payload=canonical_payload,
            )
        record = GitProposalCiRepairEventRecord(
            repair_key=repair_key,
            event_kind=event_kind,
            source_plan_digest=source_plan_digest,
            source_receipt_digest=source_receipt_digest,
            repository=repository,
            proposed_branch=proposed_branch,
            pull_request_number=pull_request_number,
            head_sha=head_sha,
            payload_json=canonical_payload,
            event_digest=event_digest,
        )
        self.db.add(record)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            winner = self._existing(repair_key=repair_key, event_kind=event_kind)
            if winner is None:
                raise
            return self._verify_exact_replay(
                winner,
                event_digest=event_digest,
                canonical_payload=canonical_payload,
            )
        self.db.refresh(record)
        return record

    def _existing(
        self,
        *,
        repair_key: str,
        event_kind: str,
    ) -> GitProposalCiRepairEventRecord | None:
        return self.db.scalar(
            select(GitProposalCiRepairEventRecord).where(
                GitProposalCiRepairEventRecord.repair_key == repair_key,
                GitProposalCiRepairEventRecord.event_kind == event_kind,
            )
        )

    @staticmethod
    def _verify_exact_replay(
        record: GitProposalCiRepairEventRecord,
        *,
        event_digest: str,
        canonical_payload: str,
    ) -> GitProposalCiRepairEventRecord:
        if (
            record.event_digest != event_digest
            or record.payload_json != canonical_payload
        ):
            raise PermissionError("CI_REPAIR_JOURNAL_IDEMPOTENCY_CONFLICT")
        return record


class GitProposalCiRepairCoordinator:
    """Turn exact draft-PR CI evidence into bounded governed repair assignments."""

    def evaluate(
        self,
        *,
        mutation_receipt: GitProposalMutationReceipt,
        observation: CiObservation,
        required_checks: CiRequiredCheckRoster,
        journal: DurableGitProposalCiRepairJournal | None = None,
    ) -> CiRepairDecision:
        expected = _proposal_identity(mutation_receipt)
        if expected is None:
            return self._blocked(
                mutation_receipt,
                observation,
                "CI_REPAIR_DRAFT_PR_EVIDENCE_REQUIRED",
            )
        expected_pr, expected_head = expected
        if observation.repository != mutation_receipt.repository:
            return self._blocked(
                mutation_receipt, observation, "CI_REPAIR_REPOSITORY_MISMATCH"
            )
        if observation.pull_request_number != expected_pr:
            return self._blocked(
                mutation_receipt, observation, "CI_REPAIR_PULL_REQUEST_MISMATCH"
            )
        if observation.head_sha != expected_head:
            return self._blocked(
                mutation_receipt, observation, "CI_REPAIR_STALE_OR_MOVED_HEAD"
            )

        required_state = _required_check_state(observation, required_checks)
        if required_state == "identity_mismatch":
            return self._blocked(
                mutation_receipt, observation, "CI_REPAIR_REQUIRED_ROSTER_MISMATCH"
            )
        if required_state == "incomplete":
            return self._blocked(
                mutation_receipt, observation, "CI_REPAIR_REQUIRED_CHECKS_INCOMPLETE"
            )

        checks_by_id = {check.check_id: check for check in observation.checks}
        required = [checks_by_id[check_id] for check_id in required_checks.check_ids]
        pending = [
            check for check in required if check.conclusion == CiConclusion.PENDING
        ]
        failed = [
            check
            for check in required
            if check.conclusion in {CiConclusion.FAILURE, CiConclusion.CANCELLED}
        ]
        if pending:
            return CiRepairDecision(
                CiRepairDisposition.WAITING,
                "CI_REPAIR_CHECKS_PENDING",
                None,
                observation.observation_digest,
                mutation_receipt.receipt_digest,
            )
        if not failed:
            return CiRepairDecision(
                CiRepairDisposition.READY_FOR_OWNER_MERGE,
                "CI_REPAIR_ALL_REQUIRED_CHECKS_GREEN",
                None,
                observation.observation_digest,
                mutation_receipt.receipt_digest,
            )

        assignment = _repair_assignment(
            mutation_receipt, observation, required_checks, failed
        )
        if journal is not None:
            journal.record_assignment(assignment)
        return CiRepairDecision(
            CiRepairDisposition.REPAIR_REQUIRED,
            "CI_REPAIR_AUTHORITATIVE_CORRECTION_REQUIRED",
            assignment,
            observation.observation_digest,
            mutation_receipt.receipt_digest,
        )

    @staticmethod
    def _blocked(
        receipt: GitProposalMutationReceipt,
        observation: CiObservation,
        code: str,
    ) -> CiRepairDecision:
        return CiRepairDecision(
            CiRepairDisposition.BLOCKED,
            code,
            None,
            observation.observation_digest,
            receipt.receipt_digest,
        )


def _required_check_state(
    observation: CiObservation,
    roster: CiRequiredCheckRoster,
) -> str:
    if (
        roster.repository != observation.repository
        or roster.pull_request_number != observation.pull_request_number
        or roster.head_sha != observation.head_sha
    ):
        return "identity_mismatch"
    checks_by_id = {check.check_id: check for check in observation.checks}
    if any(check_id not in checks_by_id for check_id in roster.check_ids):
        return "incomplete"
    required = [checks_by_id[check_id] for check_id in roster.check_ids]
    if any(check.conclusion == CiConclusion.PENDING for check in required):
        return "pending"
    if any(
        check.conclusion in {CiConclusion.FAILURE, CiConclusion.CANCELLED}
        for check in required
    ):
        return "failed"
    return "green"


def _verify_corrective_receipt(
    *,
    assignment: CiRepairAssignment,
    observation: CiObservation,
    corrective_receipt: GitProposalMutationReceipt,
    expected_digest: str,
) -> None:
    if corrective_receipt.receipt_digest != expected_digest:
        raise PermissionError("CI_REPAIR_CORRECTIVE_RECEIPT_DIGEST_MISMATCH")
    if expected_digest == assignment.source_mutation_receipt_digest:
        raise PermissionError("CI_REPAIR_CORRECTIVE_RECEIPT_NOT_FRESH")
    if corrective_receipt.status not in FINAL_STATUSES:
        raise PermissionError("CI_REPAIR_CORRECTIVE_RECEIPT_NOT_FINAL")
    if corrective_receipt.repository != assignment.repository:
        raise PermissionError("CI_REPAIR_CORRECTIVE_RECEIPT_REPOSITORY_MISMATCH")
    if corrective_receipt.proposed_branch != assignment.proposed_branch:
        raise PermissionError("CI_REPAIR_CORRECTIVE_RECEIPT_BRANCH_MISMATCH")
    commit_payloads = [
        dict(item.payload)
        for item in corrective_receipt.operation_evidence
        if item.action == "create_commit"
        and item.status in {"created", "already_exists_exact"}
    ]
    push_payloads = [
        dict(item.payload)
        for item in corrective_receipt.operation_evidence
        if item.action == "push_branch"
        and item.status in {"created", "already_exists_exact"}
    ]
    if len(commit_payloads) != 1 or len(push_payloads) != 1:
        raise PermissionError("CI_REPAIR_CORRECTIVE_RECEIPT_PUSH_EVIDENCE_REQUIRED")
    commit = commit_payloads[0]
    push = push_payloads[0]
    if (
        str(commit.get("commit_sha") or "") != observation.head_sha
        or str(push.get("commit_sha") or "") != observation.head_sha
    ):
        raise PermissionError("CI_REPAIR_CORRECTIVE_RECEIPT_HEAD_MISMATCH")
    if (
        str(commit.get("repair_key") or "") != assignment.repair_key
        or str(push.get("repair_key") or "") != assignment.repair_key
    ):
        raise PermissionError("CI_REPAIR_CORRECTIVE_RECEIPT_ASSIGNMENT_MISMATCH")


def _proposal_identity(receipt: GitProposalMutationReceipt) -> tuple[int, str] | None:
    if (
        receipt.status not in FINAL_STATUSES
        or FINAL_ACTION not in receipt.completed_actions
    ):
        return None
    pr_payloads = [
        dict(item.payload)
        for item in receipt.operation_evidence
        if item.action == "open_pull_request"
        and item.status in {"created", "already_exists_exact"}
    ]
    commit_payloads = [
        dict(item.payload)
        for item in receipt.operation_evidence
        if item.action == "create_commit"
        and item.status in {"created", "already_exists_exact"}
    ]
    if len(pr_payloads) != 1 or len(commit_payloads) != 1:
        return None
    pr_number = pr_payloads[0].get("pull_request_number")
    head_sha = str(commit_payloads[0].get("commit_sha") or "").strip()
    if type(pr_number) is not int or pr_number <= 0 or not _is_git_sha(head_sha):
        return None
    if pr_payloads[0].get("draft") is not True:
        return None
    if str(pr_payloads[0].get("head_commit_sha") or "").strip() != head_sha:
        return None
    if str(pr_payloads[0].get("head_branch") or "").strip() != receipt.proposed_branch:
        return None
    return pr_number, head_sha


def _repair_assignment(
    receipt: GitProposalMutationReceipt,
    observation: CiObservation,
    required_checks: CiRequiredCheckRoster,
    failed: Sequence[CiCheck],
) -> CiRepairAssignment:
    failed_checks = tuple(
        check.snapshot() for check in sorted(failed, key=lambda item: item.check_id)
    )
    material = {
        "source_plan_digest": receipt.plan_digest,
        "source_mutation_receipt_digest": receipt.receipt_digest,
        "repository": receipt.repository,
        "proposed_branch": receipt.proposed_branch,
        "pull_request_number": observation.pull_request_number,
        "failed_head_sha": observation.head_sha,
        "failed_checks": list(failed_checks),
        "observation_digest": observation.observation_digest,
        "required_check_policy_digest": required_checks.policy_digest,
    }
    return CiRepairAssignment(
        repair_key=canonical_sha256(material),
        source_plan_digest=receipt.plan_digest,
        source_mutation_receipt_digest=receipt.receipt_digest,
        patch_program_job_id=receipt.patch_program_job_id,
        repository=receipt.repository,
        proposed_branch=receipt.proposed_branch,
        pull_request_number=observation.pull_request_number,
        failed_head_sha=observation.head_sha,
        failed_checks=failed_checks,
        observation_digest=observation.observation_digest,
        required_check_policy_digest=required_checks.policy_digest,
    )


def _is_git_sha(value: str) -> bool:
    return len(value) == 40 and all(
        character in "0123456789abcdef" for character in value
    )


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )
