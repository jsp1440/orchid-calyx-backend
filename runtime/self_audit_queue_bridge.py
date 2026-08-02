"""Bridge governed self-audit findings into BUILD-044 draft queue work items."""

from __future__ import annotations

from typing import Any

from runtime.self_audit import AuditFinding, AuditReport


def finding_to_task(finding: AuditFinding) -> dict[str, Any]:
    """Create a bounded draft task without executing the recommendation."""

    return {
        "task_key": f"self-audit:{finding.finding_key}",
        "task_type": "platform_self_audit_followup",
        "title": finding.title,
        "priority": finding.priority,
        "required_approval": finding.requires_human_approval,
        "status": "needs_review" if finding.requires_human_approval else "pending",
        "payload": {
            "finding": finding.as_dict(),
            "execution_mode": "draft_only",
            "automatic_merge": False,
            "automatic_deploy": False,
            "automatic_publication": False,
        },
    }


def report_to_tasks(report: AuditReport, limit: int = 10) -> list[dict[str, Any]]:
    """Convert the highest-priority findings into idempotent queue candidates."""

    safe_limit = max(0, min(50, int(limit)))
    return [finding_to_task(finding) for finding in report.findings[:safe_limit]]
