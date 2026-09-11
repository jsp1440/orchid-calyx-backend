from runtime.self_audit import AuditFinding, AuditReport
from runtime.self_audit_queue_bridge import (
    finding_to_task,
    persist_report,
    report_to_tasks,
)


def _finding(
    action: str = "prepare_draft_work_item",
    finding_key: str = "github:ci_checks",
) -> AuditFinding:
    return AuditFinding(
        finding_key=finding_key,
        source="github",
        title="ci_checks is failed",
        severity="high",
        confidence=1.0,
        priority=75,
        recommended_action=action,
        requires_human_approval=action == "merge",
        evidence={"status": "failed"},
    )


def _report(*findings: AuditFinding) -> AuditReport:
    return AuditReport(
        generated_at="2026-09-11T00:00:00+00:00",
        status="attention_required" if findings else "healthy",
        findings=findings,
        inspected_sources=("github",),
    )


class FakeQueue:
    def __init__(self) -> None:
        self.keys: set[str] = set()
        self.calls: list[dict] = []

    def create_task_once(self, **task):
        self.calls.append(task)
        if task["task_key"] in self.keys:
            return {"status": "duplicate", "task_key": task["task_key"]}
        self.keys.add(task["task_key"])
        return {"status": "created", "task": task}


def test_queue_task_is_draft_only_and_idempotent():
    task = finding_to_task(_finding())
    assert task["task_key"] == "self-audit:github:ci_checks"
    assert task["status"] == "pending"
    assert task["payload"]["automatic_merge"] is False
    assert task["payload"]["action"] == "prepare_draft_work_item"


def test_risky_finding_requires_review():
    task = finding_to_task(_finding("merge"))
    assert task["required_approval"] is True
    assert task["status"] == "needs_review"
    assert task["payload"]["action"] == "merge"


def test_report_limit_is_bounded_and_duplicate_findings_collapse():
    findings = tuple(
        _finding(finding_key=f"github:check-{index}") for index in range(60)
    )
    assert len(report_to_tasks(_report(*findings), limit=100)) == 50
    assert len(report_to_tasks(_report(_finding(), _finding()), limit=10)) == 1


def test_repeated_report_reuses_one_durable_lineage():
    queue = FakeQueue()
    report = _report(_finding())

    first = persist_report(report, queue)
    second = persist_report(report, queue)

    assert first["schema"] == "oc.self-audit-queue.v1"
    assert first["status"] == "refill_planned"
    assert first["created_task_keys"] == ["self-audit:github:ci_checks"]
    assert second["status"] == "reserve_satisfied"
    assert second["created_task_keys"] == []
    assert second["duplicate_task_keys"] == ["self-audit:github:ci_checks"]
    assert len(queue.keys) == 1


def test_empty_report_is_healthy_depletion():
    result = persist_report(_report(), FakeQueue())

    assert result["status"] == "queue_empty_healthy"
    assert result["task_count"] == 0


def test_protected_work_is_persisted_fail_closed_for_review():
    queue = FakeQueue()

    result = persist_report(_report(_finding("deploy")), queue)

    assert result["protected_task_keys"] == ["self-audit:github:ci_checks"]
    assert queue.calls[0]["payload"]["action"] == "deploy"
