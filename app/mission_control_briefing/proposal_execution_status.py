from __future__ import annotations

from typing import Any

from sqlalchemy import func, inspect, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.calyx_orchestrator.git_proposal_execution_plan import ACTION_ORDER
from app.calyx_orchestrator.git_proposal_mutation_executor import (
    GitProposalMutationReceipt,
)
from app.calyx_orchestrator.git_proposal_mutation_journal import (
    FINAL_STATUSES,
    DurableGitProposalMutationJournal,
    GitProposalMutationJournalEventRecord,
)

STATUS_SCHEMA = "calyx-mission-control-proposal-execution-status-v1"
MAX_RECENT_PLANS = 25


def _operation_payload(
    receipt: GitProposalMutationReceipt,
    action: str,
) -> dict[str, Any] | None:
    matches = [item for item in receipt.operation_evidence if item.action == action]
    if len(matches) != 1:
        return None
    return dict(matches[0].payload)


def _receipt_snapshot(receipt: GitProposalMutationReceipt) -> dict[str, Any]:
    completed = tuple(receipt.completed_actions)
    next_action = None
    if receipt.status not in FINAL_STATUSES and len(completed) < len(ACTION_ORDER):
        next_action = ACTION_ORDER[len(completed)]

    commit = _operation_payload(receipt, "create_commit") or {}
    pull_request = _operation_payload(receipt, "open_pull_request") or {}
    number = pull_request.get("pull_request_number")
    if type(number) is not int or number <= 0:
        number = None
    url = str(pull_request.get("pull_request_url") or "").strip() or None

    return {
        "plan_digest": receipt.plan_digest,
        "patch_program_job_id": receipt.patch_program_job_id,
        "repository": receipt.repository,
        "base_ref": receipt.base_ref,
        "base_commit_sha": receipt.base_commit_sha,
        "proposed_branch": receipt.proposed_branch,
        "status": receipt.status,
        "completed_actions": list(completed),
        "current_remote_operation": next_action,
        "failure_code": receipt.failure_code,
        "receipt_digest": receipt.receipt_digest,
        "commit_sha": str(commit.get("commit_sha") or "").strip() or None,
        "draft_pull_request": {
            "number": number,
            "url": url,
            "draft": pull_request.get("draft") is True if pull_request else None,
        },
        "remote_side_effects_recorded": bool(completed),
        "terminal": receipt.status in FINAL_STATUSES,
    }


def _blocked_status(code: str) -> dict[str, Any]:
    return {
        "schema": STATUS_SCHEMA,
        "journal_available": False,
        "journal_error": code,
        "active_execution": None,
        "latest_execution": None,
        "recent_executions": [],
        "recent_execution_count": 0,
        "read_only": True,
        "mutation_performed_by_status_read": False,
        "secret_material_exposed": False,
        "bounded_recent_plan_limit": MAX_RECENT_PLANS,
    }


def proposal_execution_mission_control_status(db: Session) -> dict[str, Any]:
    """Read durable proposal-operation evidence without performing remote mutation."""

    try:
        bind = db.get_bind()
        if not inspect(bind).has_table(GitProposalMutationJournalEventRecord.__tablename__):
            return _blocked_status("durable_mutation_journal_table_unavailable")

        latest_event = func.max(GitProposalMutationJournalEventRecord.event_id).label(
            "latest_event"
        )
        rows = db.execute(
            select(
                GitProposalMutationJournalEventRecord.plan_digest,
                latest_event,
            )
            .group_by(GitProposalMutationJournalEventRecord.plan_digest)
            .order_by(latest_event.desc())
            .limit(MAX_RECENT_PLANS)
        ).all()
        journal = DurableGitProposalMutationJournal(db)
        snapshots: list[dict[str, Any]] = []
        for plan_digest, _ in rows:
            receipt = journal.latest(plan_digest=str(plan_digest))
            if receipt is None:
                continue
            snapshots.append(_receipt_snapshot(receipt))
    except (SQLAlchemyError, LookupError, PermissionError, TypeError, ValueError) as exc:
        db.rollback()
        return _blocked_status(str(exc) or type(exc).__name__)

    active = next((item for item in snapshots if not item["terminal"]), None)
    latest = snapshots[0] if snapshots else None
    return {
        "schema": STATUS_SCHEMA,
        "journal_available": True,
        "journal_error": None,
        "active_execution": active,
        "latest_execution": latest,
        "recent_executions": snapshots,
        "recent_execution_count": len(snapshots),
        "read_only": True,
        "mutation_performed_by_status_read": False,
        "secret_material_exposed": False,
        "bounded_recent_plan_limit": MAX_RECENT_PLANS,
    }
