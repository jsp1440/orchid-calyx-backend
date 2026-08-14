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

STATUS_SCHEMA = "calyx-mission-control-proposal-execution-status-v2"
MAX_RECENT_PLANS = 25
MAX_ACTIVE_SCAN_PLANS = 100


def _operation_payload(
    receipt: GitProposalMutationReceipt,
    action: str,
) -> dict[str, Any] | None:
    matches = [item for item in receipt.operation_evidence if item.action == action]
    if len(matches) != 1:
        return None
    return dict(matches[0].payload)


def _current_operation(receipt: GitProposalMutationReceipt) -> tuple[str | None, str]:
    """Return only an operation that is provably inside the authorized plan boundary."""

    completed = tuple(receipt.completed_actions)
    if receipt.status in FINAL_STATUSES:
        return None, "terminal"
    if len(completed) >= len(ACTION_ORDER):
        return None, "action_order_exhausted"
    if receipt.status in {"partial_failure", "failed"}:
        # A failure receipt exists only because the executor entered the next operation in
        # the reviewed plan. Therefore the next prefix action is known to be authorized.
        return ACTION_ORDER[len(completed)], "authorized_by_failed_attempt"
    # An in-progress receipt is committed after every successful operation. It may be the
    # last operation of a dependency-closed subset plan, so the global action order alone
    # cannot prove that another remote operation was authorized.
    return None, "authorization_boundary_unknown"


def _receipt_snapshot(receipt: GitProposalMutationReceipt) -> dict[str, Any]:
    completed = tuple(receipt.completed_actions)
    current_operation, operation_state = _current_operation(receipt)

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
        "current_remote_operation": current_operation,
        "current_remote_operation_state": operation_state,
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
        "active_execution_known": False,
        "active_execution_state": "blocked",
        "latest_execution": None,
        "recent_executions": [],
        "recent_execution_count": 0,
        "read_only": True,
        "mutation_performed_by_status_read": False,
        "secret_material_exposed": False,
        "bounded_recent_plan_limit": MAX_RECENT_PLANS,
        "bounded_active_scan_limit": MAX_ACTIVE_SCAN_PLANS,
        "checkpoint_validation": "latest_receipt_plus_event_index_continuity",
    }


def proposal_execution_mission_control_status(db: Session) -> dict[str, Any]:
    """Read bounded durable proposal-operation evidence without remote mutation."""

    try:
        bind = db.get_bind()
        if not inspect(bind).has_table(
            GitProposalMutationJournalEventRecord.__tablename__
        ):
            return _blocked_status("durable_mutation_journal_table_unavailable")

        latest_event_id = func.max(
            GitProposalMutationJournalEventRecord.event_id
        ).label("latest_event_id")
        latest_event_index = func.max(
            GitProposalMutationJournalEventRecord.event_index
        ).label("latest_event_index")
        event_count = func.count(GitProposalMutationJournalEventRecord.event_id).label(
            "event_count"
        )
        latest_by_plan = (
            select(
                GitProposalMutationJournalEventRecord.plan_digest.label("plan_digest"),
                latest_event_id,
                latest_event_index,
                event_count,
            )
            .group_by(GitProposalMutationJournalEventRecord.plan_digest)
            .subquery()
        )
        rows = db.execute(
            select(
                GitProposalMutationJournalEventRecord,
                latest_by_plan.c.latest_event_index,
                latest_by_plan.c.event_count,
            )
            .join(
                latest_by_plan,
                GitProposalMutationJournalEventRecord.event_id
                == latest_by_plan.c.latest_event_id,
            )
            .order_by(GitProposalMutationJournalEventRecord.event_id.desc())
            .limit(MAX_ACTIVE_SCAN_PLANS + 1)
        ).all()

        scan_truncated = len(rows) > MAX_ACTIVE_SCAN_PLANS
        scan_rows = rows[:MAX_ACTIVE_SCAN_PLANS]
        snapshots: list[dict[str, Any]] = []
        active: dict[str, Any] | None = None

        for row, max_event_index, count_events in scan_rows:
            if max_event_index != count_events:
                raise PermissionError("GIT_PROPOSAL_JOURNAL_HISTORY_GAP")
            receipt = DurableGitProposalMutationJournal.validate_checkpoint_receipt(row)
            snapshot = _receipt_snapshot(receipt)
            if len(snapshots) < MAX_RECENT_PLANS:
                snapshots.append(snapshot)
            if active is None and not snapshot["terminal"]:
                active = snapshot

    except (
        SQLAlchemyError,
        LookupError,
        PermissionError,
        TypeError,
        ValueError,
    ) as exc:
        db.rollback()
        return _blocked_status(str(exc) or type(exc).__name__)

    latest = snapshots[0] if snapshots else None
    if active is not None:
        active_known = True
        active_state = "active_found"
    elif scan_truncated:
        active_known = False
        active_state = "unknown_beyond_bounded_scan"
    else:
        active_known = True
        active_state = "none"

    return {
        "schema": STATUS_SCHEMA,
        "journal_available": True,
        "journal_error": None,
        "active_execution": active,
        "active_execution_known": active_known,
        "active_execution_state": active_state,
        "latest_execution": latest,
        "recent_executions": snapshots,
        "recent_execution_count": len(snapshots),
        "read_only": True,
        "mutation_performed_by_status_read": False,
        "secret_material_exposed": False,
        "bounded_recent_plan_limit": MAX_RECENT_PLANS,
        "bounded_active_scan_limit": MAX_ACTIVE_SCAN_PLANS,
        "checkpoint_validation": "latest_receipt_plus_event_index_continuity",
    }
