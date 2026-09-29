"""Bridge governed self-audit findings into durable BUILD-044 queue work."""

from __future__ import annotations

import json
from typing import Any, Protocol

from runtime.self_audit import (
    PROHIBITED_AUTONOMOUS_ACTIONS,
    AuditFinding,
    AuditReport,
)


class IdempotentTaskQueue(Protocol):
    """The narrow durable queue contract required by the self-audit bridge."""

    def create_task_once(
        self,
        *,
        task_key: str,
        task_type: str,
        title: str,
        payload: dict[str, Any],
        priority: int = 0,
    ) -> dict[str, Any]: ...


class DurableSelfAuditQueue:
    """Persist keyed findings through the existing Calyx orchestrator store."""

    def __init__(self, orchestrator: Any) -> None:
        self.orchestrator = orchestrator

    def create_task_once(
        self,
        *,
        task_key: str,
        task_type: str,
        title: str,
        payload: dict[str, Any],
        priority: int = 0,
    ) -> dict[str, Any]:
        normalized_key = task_key.strip()
        if not normalized_key:
            raise ValueError("task_key is required")

        required_approval = (
            self.orchestrator.executor.risky_action(task_type, payload) is not None
        )
        status = "needs_review" if required_approval else "pending"
        task: dict[str, Any] | None = None

        with (
            self.orchestrator.connect() as conn,
            conn.cursor() as cur,
        ):
            self.orchestrator.ensure_schema(cur)
            cur.execute(
                """
                INSERT INTO oc_admin.calyx_tasks
                    (task_key, task_type, title, payload, status, priority, required_approval)
                VALUES (%s, %s, %s, %s::jsonb, %s, %s, %s)
                ON CONFLICT (task_key) DO NOTHING
                RETURNING *
                """,
                (
                    normalized_key,
                    task_type,
                    title,
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    status,
                    priority,
                    required_approval,
                ),
            )
            row = cur.fetchone()
            if row is not None:
                task = dict(row)
                self.orchestrator.log_observation(
                    cur,
                    task_id=task["id"],
                    agent_id=None,
                    event_type="task_created",
                    action="queued" if status == "pending" else "approval_required",
                    status=status,
                    details={
                        "task_key": normalized_key,
                        "required_approval": required_approval,
                    },
                )
            conn.commit()

        if task is None:
            return {"status": "duplicate", "task_key": normalized_key}
        return {"status": "created", "task": task}


def finding_to_task(finding: AuditFinding) -> dict[str, Any]:
    """Create a bounded draft task without executing the recommendation."""

    finding_key = finding.finding_key.strip()
    if not finding_key:
        raise ValueError("self-audit finding_key is required")

    action = finding.recommended_action.strip().lower()
    if not action:
        raise ValueError("self-audit recommended_action is required")

    requires_approval = (
        finding.requires_human_approval or action in PROHIBITED_AUTONOMOUS_ACTIONS
    )
    return {
        "task_key": f"self-audit:{finding_key}",
        "task_type": "platform_self_audit_followup",
        "title": finding.title,
        "priority": finding.priority,
        "required_approval": requires_approval,
        "status": "needs_review" if requires_approval else "pending",
        "payload": {
            "finding": finding.as_dict(),
            "source": finding.source,
            "recommended_action": action,
            "action": action,
            "execution_mode": "draft_only",
            "automatic_merge": False,
            "automatic_deploy": False,
            "automatic_publication": False,
        },
    }


def report_to_tasks(report: AuditReport, limit: int = 10) -> list[dict[str, Any]]:
    """Convert findings into a bounded, semantically deduplicated task plan."""

    safe_limit = max(0, min(50, int(limit)))
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()

    for finding in report.findings:
        task = finding_to_task(finding)
        task_key = task["task_key"]
        if task_key in seen:
            continue
        seen.add(task_key)
        tasks.append(task)
        if len(tasks) >= safe_limit:
            break

    return tasks


def persist_report(
    report: AuditReport,
    queue: IdempotentTaskQueue,
    limit: int = 10,
) -> dict[str, Any]:
    """Persist a report once through the canonical Calyx task queue.

    The orchestrator owns the database write and unique task-key constraint.
    Replayed reports therefore resolve to the same durable lineage.
    """

    tasks = report_to_tasks(report, limit=limit)
    created: list[str] = []
    duplicates: list[str] = []

    for task in tasks:
        result = queue.create_task_once(
            task_key=task["task_key"],
            task_type=task["task_type"],
            title=task["title"],
            payload=task["payload"],
            priority=task["priority"],
        )
        if result.get("status") == "created":
            created.append(task["task_key"])
        else:
            duplicates.append(task["task_key"])

    if created:
        status = "refill_planned"
    elif report.findings:
        status = "reserve_satisfied"
    else:
        status = "queue_empty_healthy"

    return {
        "schema": "oc.self-audit-queue.v1",
        "status": status,
        "report_generated_at": report.generated_at,
        "task_count": len(tasks),
        "created_task_keys": created,
        "duplicate_task_keys": duplicates,
        "protected_task_keys": [
            task["task_key"] for task in tasks if task["required_approval"]
        ],
    }
