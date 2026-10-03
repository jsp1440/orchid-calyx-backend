"""ORCHESTRATION-AUDIT-FOLLOWTHROUGH-001: audits must auto-create remediation work.

These tests exercise the pure classification engine
(``AuditFollowthroughEngine``) and the constitutional narrative-only-completion
gate (``evaluate_audit_completion``) without a database, mirroring how
``DefaultTaskExecutor`` is tested for BUILD-044.
"""

from runtime.autonomous_orchestrator import (
    FINDING_DISPOSITIONS,
    NON_TASK_DISPOSITIONS,
    AuditFollowthroughEngine,
    DefaultTaskExecutor,
    finding_key,
)
from runtime.constitutional_orchestrator import (
    TERMINAL_FINDING_DISPOSITIONS,
    ConstitutionalMissionOrchestrator,
)


def test_dispositions_stay_in_sync_across_the_two_orchestrators():
    assert set(FINDING_DISPOSITIONS) == TERMINAL_FINDING_DISPOSITIONS
    assert NON_TASK_DISPOSITIONS.issubset(TERMINAL_FINDING_DISPOSITIONS)


def test_actionable_finding_with_no_existing_task_is_queued_automatically():
    engine = AuditFollowthroughEngine()
    finding = {
        "title": "Occurrence source selection is wrong",
        "category": "data_integration",
        "task_type": "relationship_data_audit",
    }

    plans = engine.plan("AUDIT-MEASUREMENT-002", [finding], existing_tasks_by_key={})

    assert len(plans) == 1
    plan = plans[0]
    assert plan.disposition == "auto_remediation_queued"
    assert plan.task_action == "create"
    assert plan.task_key == finding_key("AUDIT-MEASUREMENT-002", finding)


def test_repeat_audit_dedupes_the_same_unresolved_finding():
    engine = AuditFollowthroughEngine()
    finding = {"title": "Pollinator taxonomy IDs are broken", "category": "data_integration"}
    key = finding_key("AUDIT-MEASUREMENT-002", finding)

    first_pass = engine.plan("AUDIT-MEASUREMENT-002", [finding], existing_tasks_by_key={})
    assert first_pass[0].task_action == "create"

    # Simulate the task that ingest_audit_findings() would have created still
    # sitting unresolved in the queue.
    existing_tasks = {key: {"id": 1, "status": "pending", "evaluation_result": None, "payload": {}}}
    second_pass = engine.plan("AUDIT-MEASUREMENT-002", [finding], existing_tasks_by_key=existing_tasks)

    assert second_pass[0].task_action is None, "a second audit run must not create a duplicate task"
    assert second_pass[0].disposition == "auto_remediation_queued"


def test_safe_finding_moves_to_execution_without_a_second_owner_prompt():
    engine = AuditFollowthroughEngine()
    finding = {"title": "Relationship is unmeasured", "task_type": "relationship_data_audit"}

    plans = engine.plan("AUDIT-1", [finding], existing_tasks_by_key={})

    assert plans[0].disposition == "auto_remediation_queued"
    # A safe/reversible task is created directly as "pending", not gated behind
    # a review step that would need another owner prompt to release.
    assert plans[0].task_action == "create"


def test_high_risk_finding_stops_at_the_existing_approval_gate():
    engine = AuditFollowthroughEngine()
    finding = {
        "title": "Deployment is required to pick up the fix",
        "task_type": "deploy",
        "payload": {"action": "deploy"},
    }

    plans = engine.plan("AUDIT-1", [finding], existing_tasks_by_key={})

    assert plans[0].disposition == "owner_approval_required"
    assert plans[0].task_action == "create"


def test_cross_repository_findings_are_also_owner_gated():
    engine = AuditFollowthroughEngine()
    finding = {
        "title": "Frontend must add a status panel",
        "task_type": "frontend_integration_audit",
        "payload": {"cross_repository": True},
    }

    plans = engine.plan("AUDIT-1", [finding], existing_tasks_by_key={})

    assert plans[0].disposition == "owner_approval_required"


def test_resolved_task_triggers_verified_resolved_disposition():
    engine = AuditFollowthroughEngine()
    finding = {"title": "Relationship is unmeasured", "task_type": "relationship_data_audit"}
    key = finding_key("AUDIT-1", finding)
    existing_tasks = {key: {"id": 5, "status": "completed", "evaluation_result": "pass", "payload": {}}}

    plans = engine.plan("AUDIT-1", [finding], existing_tasks_by_key=existing_tasks)

    assert plans[0].disposition == "verified_resolved"
    assert plans[0].task_action is None


def test_failed_verification_reopens_the_task_with_evidence_instead_of_completing():
    engine = AuditFollowthroughEngine()
    finding = {
        "title": "Relationship is unmeasured",
        "task_type": "relationship_data_audit",
        "evidence": ["re-audit still shows zero measured rows"],
    }
    key = finding_key("AUDIT-1", finding)
    existing_tasks = {key: {"id": 5, "status": "completed", "evaluation_result": "fail", "payload": {}}}

    plans = engine.plan("AUDIT-1", [finding], existing_tasks_by_key=existing_tasks)

    assert plans[0].task_action == "requeue"
    assert plans[0].disposition == "auto_remediation_queued"
    assert plans[0].evidence == ["re-audit still shows zero measured rows"]


def test_running_task_is_reported_as_in_progress():
    engine = AuditFollowthroughEngine()
    finding = {"title": "Relationship is unmeasured", "task_type": "relationship_data_audit"}
    key = finding_key("AUDIT-1", finding)
    existing_tasks = {key: {"id": 5, "status": "running", "evaluation_result": None, "payload": {}}}

    plans = engine.plan("AUDIT-1", [finding], existing_tasks_by_key=existing_tasks)

    assert plans[0].disposition == "auto_remediation_in_progress"


def test_scientific_data_gap_never_fabricates_a_code_task():
    engine = AuditFollowthroughEngine()
    finding = {
        "title": "Genuine scientific source data does not exist",
        "category": "scientific_data_gap",
        "actionable": True,
    }

    plans = engine.plan("AUDIT-1", [finding], existing_tasks_by_key={})

    assert plans[0].disposition == "scientific_data_gap"
    assert plans[0].task_action is None
    assert plans[0].task_key is None


def test_external_blocker_never_fabricates_a_code_task():
    engine = AuditFollowthroughEngine()
    finding = {"title": "Depends on a third-party API outage", "category": "external_blocker"}

    plans = engine.plan("AUDIT-1", [finding], existing_tasks_by_key={})

    assert plans[0].disposition == "external_blocker"
    assert plans[0].task_action is None


def test_non_actionable_finding_is_marked_no_action_needed():
    engine = AuditFollowthroughEngine()
    finding = {"title": "Informational note only", "actionable": False}

    plans = engine.plan("AUDIT-1", [finding], existing_tasks_by_key={})

    assert plans[0].disposition == "no_action_needed"
    assert plans[0].task_action is None


def test_explicit_finding_key_is_used_verbatim_for_stable_dedupe():
    assert finding_key("AUDIT-1", {"finding_key": "custom-key"}) == "custom-key"


def test_finding_key_is_stable_for_the_same_audit_and_title():
    finding = {"title": "Same finding text"}
    assert finding_key("AUDIT-1", finding) == finding_key("AUDIT-1", dict(finding))


def test_engine_uses_the_same_risky_action_rules_as_the_task_executor():
    engine = AuditFollowthroughEngine(DefaultTaskExecutor())
    finding = {"title": "Credential rotation needed", "task_type": "credential_sensitive"}

    plans = engine.plan("AUDIT-1", [finding], existing_tasks_by_key={})

    assert plans[0].disposition == "owner_approval_required"


# --- Constitutional narrative-only-completion gate -------------------------------------


def test_policy_registry_includes_audit_requires_followthrough():
    mission_orchestrator = ConstitutionalMissionOrchestrator()
    registry = mission_orchestrator.policy_registry()
    policy_ids = {policy["policy_id"] for policy in registry["policies"]}
    assert "audit_requires_followthrough" in policy_ids


def test_narrative_only_completed_audit_is_impossible_while_findings_lack_dispositions():
    mission_orchestrator = ConstitutionalMissionOrchestrator()

    result = mission_orchestrator.evaluate_audit_completion(
        mission_id="engineering",
        audit_id="AUDIT-1",
        findings=[{"finding_key": "f1", "actionable": True, "disposition": None}],
    )

    assert result["decision"]["status"] == "blocked_narrative_only"
    assert "f1" in result["undispositioned_findings"]
    assert result["governance_question"]["status"] == "open"


def test_audit_completion_is_approved_once_every_actionable_finding_has_a_terminal_disposition():
    mission_orchestrator = ConstitutionalMissionOrchestrator()

    result = mission_orchestrator.evaluate_audit_completion(
        mission_id="engineering",
        audit_id="AUDIT-1",
        findings=[
            {"finding_key": "f1", "actionable": True, "disposition": "auto_remediation_queued"},
            {"finding_key": "f2", "actionable": True, "disposition": "owner_approval_required"},
            {"finding_key": "f3", "actionable": False, "disposition": None},
        ],
    )

    assert result["decision"]["status"] == "approved"
    assert "governance_question" not in result


def test_non_actionable_findings_never_block_audit_completion():
    mission_orchestrator = ConstitutionalMissionOrchestrator()

    result = mission_orchestrator.evaluate_audit_completion(
        mission_id="engineering",
        audit_id="AUDIT-1",
        findings=[{"finding_key": "f1", "actionable": False}],
    )

    assert result["decision"]["status"] == "approved"
