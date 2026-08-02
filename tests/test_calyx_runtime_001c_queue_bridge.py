from runtime.self_audit import AuditFinding, AuditReport
from runtime.self_audit_queue_bridge import finding_to_task, report_to_tasks


def _finding(action: str = "prepare_draft_work_item") -> AuditFinding:
    return AuditFinding(
        finding_key="github:ci_checks",
        source="github",
        title="ci_checks is failed",
        severity="high",
        confidence=1.0,
        priority=75,
        recommended_action=action,
        requires_human_approval=action == "merge",
        evidence={"status": "failed"},
    )


def test_queue_task_is_draft_only_and_idempotent():
    task = finding_to_task(_finding())
    assert task["task_key"] == "self-audit:github:ci_checks"
    assert task["status"] == "pending"
    assert task["payload"]["automatic_merge"] is False


def test_risky_finding_requires_review():
    task = finding_to_task(_finding("merge"))
    assert task["required_approval"] is True
    assert task["status"] == "needs_review"


def test_report_limit_is_bounded():
    report = AuditReport(
        generated_at="now",
        status="attention_required",
        findings=tuple(_finding() for _ in range(60)),
        inspected_sources=("github",),
    )
    assert len(report_to_tasks(report, limit=100)) == 50
