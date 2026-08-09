from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Integer, String, Text, UniqueConstraint, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.database import Base

from .git_proposal_execution_plan import ACTION_ORDER, GitProposalExecutionPlan
from .git_proposal_mutation_executor import (
    GitProposalMutationReceipt,
    GitProposalOperationEvidence,
)
from .sandbox_supervisor_evidence import canonical_sha256

JOURNAL_SCHEMA = "calyx-git-proposal-mutation-journal-event-v1"
TERMINAL_STATUSES = frozenset({"completed", "completed_subset", "partial_failure", "failed"})


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


class GitProposalMutationJournalEventRecord(Base):
    __tablename__ = "calyx_git_proposal_mutation_journal"
    __table_args__ = (
        UniqueConstraint(
            "plan_digest",
            "event_index",
            name="uq_calyx_git_proposal_mutation_journal_plan_event",
        ),
    )

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    plan_digest: Mapped[str] = mapped_column(String(64), index=True)
    event_index: Mapped[int] = mapped_column(Integer)
    receipt_digest: Mapped[str] = mapped_column(String(64), index=True)
    payload_json: Mapped[str] = mapped_column(Text)


@dataclass(frozen=True, slots=True)
class GitProposalMutationRecoveryState:
    classification: str
    plan_digest: str
    completed_actions: tuple[str, ...]
    next_action: str | None
    terminal: bool
    receipt_digest: str | None


class DurableGitProposalMutationJournal:
    """Append-only, tamper-checked 114S receipt journal used for safe restart recovery."""

    def __init__(self, db: Session) -> None:
        self.db = db

    def record(self, receipt: GitProposalMutationReceipt, *, event_index: int) -> GitProposalMutationReceipt:
        if event_index <= 0:
            raise ValueError("GIT_PROPOSAL_JOURNAL_EVENT_INDEX_INVALID")
        snapshot = receipt.snapshot()
        self._validate_snapshot(snapshot)
        latest_row = self._latest_row(receipt.plan_digest)
        if latest_row is not None:
            if event_index < latest_row.event_index:
                raise ValueError("GIT_PROPOSAL_JOURNAL_EVENT_ORDER_INVALID")
            if event_index == latest_row.event_index:
                persisted = self._decode(latest_row)
                if persisted.snapshot() != snapshot:
                    raise ValueError("GIT_PROPOSAL_JOURNAL_EVENT_DIVERGENT_REPLAY")
                return persisted
            latest = self._decode(latest_row)
            if latest.status in TERMINAL_STATUSES:
                raise ValueError("GIT_PROPOSAL_JOURNAL_TERMINAL_ALREADY_RECORDED")
            if event_index != latest_row.event_index + 1:
                raise ValueError("GIT_PROPOSAL_JOURNAL_EVENT_GAP")
            if tuple(receipt.completed_actions[: len(latest.completed_actions)]) != latest.completed_actions:
                raise ValueError("GIT_PROPOSAL_JOURNAL_COMPLETED_ACTIONS_REGRESSED")

        payload = {
            "schema": JOURNAL_SCHEMA,
            "event_index": event_index,
            "receipt": snapshot,
        }
        row = GitProposalMutationJournalEventRecord(
            plan_digest=receipt.plan_digest,
            event_index=event_index,
            receipt_digest=receipt.receipt_digest,
            payload_json=json.dumps(payload, sort_keys=True, separators=(",", ":")),
        )
        self.db.add(row)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            existing = self.db.scalar(
                select(GitProposalMutationJournalEventRecord).where(
                    GitProposalMutationJournalEventRecord.plan_digest == receipt.plan_digest,
                    GitProposalMutationJournalEventRecord.event_index == event_index,
                )
            )
            if existing is None:
                raise
            persisted = self._decode(existing)
            if persisted.snapshot() != snapshot:
                raise ValueError("GIT_PROPOSAL_JOURNAL_EVENT_DIVERGENT_REPLAY")
            return persisted
        return self._decode(row)

    def latest(self, *, plan_digest: str) -> GitProposalMutationReceipt | None:
        digest = plan_digest.strip().lower()
        if not _is_sha256(digest):
            raise ValueError("GIT_PROPOSAL_JOURNAL_PLAN_DIGEST_INVALID")
        row = self._latest_row(digest)
        return None if row is None else self._decode(row)

    def recovery_state(self, plan: GitProposalExecutionPlan) -> GitProposalMutationRecoveryState:
        latest = self.latest(plan_digest=plan.plan_digest)
        if latest is None:
            return GitProposalMutationRecoveryState(
                classification="not_started",
                plan_digest=plan.plan_digest,
                completed_actions=(),
                next_action=plan.operations[0].action if plan.operations else None,
                terminal=False,
                receipt_digest=None,
            )
        if latest.repository != plan.repository or latest.proposed_branch != plan.proposed_branch:
            raise PermissionError("GIT_PROPOSAL_JOURNAL_PLAN_IDENTITY_MISMATCH")
        expected_prefix = tuple(operation.action for operation in plan.operations[: len(latest.completed_actions)])
        if latest.completed_actions != expected_prefix:
            raise PermissionError("GIT_PROPOSAL_JOURNAL_ACTION_PREFIX_MISMATCH")
        next_action = None
        if len(latest.completed_actions) < len(plan.operations):
            next_action = plan.operations[len(latest.completed_actions)].action
        if latest.status == "completed":
            classification = "completed"
            terminal = True
        elif latest.status == "completed_subset":
            classification = "completed_subset"
            terminal = True
        elif latest.status == "partial_failure":
            classification = "resumable_partial"
            terminal = True
        elif latest.status == "failed":
            classification = "failed_before_side_effect"
            terminal = True
        else:
            classification = "resumable_partial" if latest.completed_actions else "not_started"
            terminal = False
        return GitProposalMutationRecoveryState(
            classification=classification,
            plan_digest=plan.plan_digest,
            completed_actions=latest.completed_actions,
            next_action=next_action,
            terminal=terminal,
            receipt_digest=latest.receipt_digest,
        )

    def _latest_row(self, plan_digest: str) -> GitProposalMutationJournalEventRecord | None:
        return self.db.scalar(
            select(GitProposalMutationJournalEventRecord)
            .where(GitProposalMutationJournalEventRecord.plan_digest == plan_digest)
            .order_by(GitProposalMutationJournalEventRecord.event_index.desc())
            .limit(1)
        )

    @staticmethod
    def _validate_snapshot(snapshot: Mapping[str, Any]) -> None:
        payload = dict(snapshot)
        supplied = str(payload.pop("receipt_digest", "") or "").strip().lower()
        if not _is_sha256(supplied):
            raise ValueError("GIT_PROPOSAL_JOURNAL_RECEIPT_DIGEST_INVALID")
        if canonical_sha256(payload) != supplied:
            raise PermissionError("GIT_PROPOSAL_JOURNAL_RECEIPT_DIGEST_MISMATCH")
        completed = payload.get("completed_actions")
        evidence = payload.get("operation_evidence")
        if not isinstance(completed, list) or not isinstance(evidence, list):
            raise PermissionError("GIT_PROPOSAL_JOURNAL_RECEIPT_SHAPE_INVALID")
        if len(completed) != len(evidence):
            raise PermissionError("GIT_PROPOSAL_JOURNAL_EVIDENCE_COUNT_MISMATCH")
        if completed != list(ACTION_ORDER[: len(completed)]):
            raise PermissionError("GIT_PROPOSAL_JOURNAL_ACTION_ORDER_INVALID")
        for action, item in zip(completed, evidence, strict=True):
            if not isinstance(item, Mapping) or item.get("action") != action:
                raise PermissionError("GIT_PROPOSAL_JOURNAL_EVIDENCE_ACTION_MISMATCH")
            raw_payload = item.get("payload")
            supplied_evidence = str(item.get("evidence_digest") or "").strip().lower()
            if not isinstance(raw_payload, Mapping) or not _is_sha256(supplied_evidence):
                raise PermissionError("GIT_PROPOSAL_JOURNAL_EVIDENCE_INVALID")
            if canonical_sha256(raw_payload) != supplied_evidence:
                raise PermissionError("GIT_PROPOSAL_JOURNAL_EVIDENCE_DIGEST_MISMATCH")

    @classmethod
    def _decode(cls, row: GitProposalMutationJournalEventRecord) -> GitProposalMutationReceipt:
        try:
            payload = json.loads(row.payload_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise PermissionError("GIT_PROPOSAL_JOURNAL_PAYLOAD_INVALID") from exc
        if not isinstance(payload, dict) or payload.get("schema") != JOURNAL_SCHEMA:
            raise PermissionError("GIT_PROPOSAL_JOURNAL_PAYLOAD_INVALID")
        if payload.get("event_index") != row.event_index:
            raise PermissionError("GIT_PROPOSAL_JOURNAL_ROW_IDENTITY_MISMATCH")
        raw = payload.get("receipt")
        if not isinstance(raw, dict):
            raise PermissionError("GIT_PROPOSAL_JOURNAL_PAYLOAD_INVALID")
        cls._validate_snapshot(raw)
        if raw.get("plan_digest") != row.plan_digest or raw.get("receipt_digest") != row.receipt_digest:
            raise PermissionError("GIT_PROPOSAL_JOURNAL_ROW_IDENTITY_MISMATCH")
        try:
            evidence = tuple(
                GitProposalOperationEvidence(
                    action=str(item["action"]),
                    status=str(item["status"]),
                    evidence_digest=str(item["evidence_digest"]),
                    payload=dict(item["payload"]),
                )
                for item in raw["operation_evidence"]
            )
            receipt = GitProposalMutationReceipt(
                plan_digest=str(raw["plan_digest"]),
                repository=str(raw["repository"]),
                proposed_branch=str(raw["proposed_branch"]),
                base_commit_sha=str(raw["base_commit_sha"]),
                status=str(raw["status"]),
                completed_actions=tuple(str(item) for item in raw["completed_actions"]),
                operation_evidence=evidence,
                failure_code=None if raw.get("failure_code") is None else str(raw["failure_code"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise PermissionError("GIT_PROPOSAL_JOURNAL_RECEIPT_INVALID") from exc
        if receipt.snapshot() != raw:
            raise PermissionError("GIT_PROPOSAL_JOURNAL_RECEIPT_SHAPE_MISMATCH")
        return receipt
