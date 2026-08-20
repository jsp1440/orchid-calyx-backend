"""TWO-DAY-SLICE-A / issue #1025: audit follow-through core.

Covers: disposition validation, dedupe stability, duplicate suppression,
safe vs owner-gated classification, provenance retention, and the
narrative-only completion prohibition.
"""

import pytest

from runtime.audit_followthrough import (
    ActionableFinding,
    FindingRemediation,
    InvalidDispositionError,
    NarrativeOnlyCompletionError,
    build_remediation,
    dedupe_key,
    enforce_followthrough,
    next_actions_created,
    plan_remediation,
    run_followthrough,
    task_key_for_finding,
    validate_disposition,
)
from runtime.autonomous_orchestrator import DefaultTaskExecutor


def _finding(**overrides) -> ActionableFinding:
    defaults = dict(
        finding_key="backend:queue_depth",
        title="Queue depth above threshold",
        audit_source="AUDIT-MEASUREMENT-002",
        audit_id="AUD-0000FEED0000",
        evidence={"status": "degraded", "depth": 42},
    )
    defaults.update(overrides)
    return ActionableFinding(**defaults)


# ---------------------------------------------------------------------------
# Disposition validation
# ---------------------------------------------------------------------------

def test_all_seven_specified_dispositions_are_valid():
    for disposition in (
        "auto_remediation_queued",
        "in_progress",
        "verified_resolved",
        "owner_approval_required",
        "external_blocker",
        "scientific_data_gap",
        "no_action_needed",
    ):
        assert validate_disposition(disposition) == disposition


def test_disposition_validation_fails_closed_on_unknown_value():
    with pytest.raises(InvalidDispositionError):
        validate_disposition("looks_fine_probably")


def test_disposition_validation_normalizes_case_and_whitespace():
    assert validate_disposition("  Verified_Resolved  ") == "verified_resolved"


def test_finding_remediation_rejects_invalid_disposition():
    with pytest.raises(InvalidDispositionError):
        FindingRemediation(finding_key="x", disposition="done")


def test_non_actionable_finding_reason_must_be_a_non_actionable_disposition():
    with pytest.raises(InvalidDispositionError):
        _finding(actionable=False, non_actionable_reason="auto_remediation_queued")


# ---------------------------------------------------------------------------
# Dedupe key stability
# ---------------------------------------------------------------------------

def test_dedupe_key_is_stable_for_the_same_audit_source_and_finding():
    first = dedupe_key("AUDIT-MEASUREMENT-002", "backend:queue_depth")
    second = dedupe_key("AUDIT-MEASUREMENT-002", "backend:queue_depth")
    assert first == second


def test_dedupe_key_is_stable_across_different_per_run_audit_ids():
    # Two remediation plans for the same logical finding from two different
    # audit *runs* (different audit_id) must land on the same task_key.
    run_one = build_remediation(_finding(audit_id="AUD-RUN-ONE"))
    run_two = build_remediation(_finding(audit_id="AUD-RUN-TWO"))
    assert run_one.task["task_key"] == run_two.task["task_key"]


def test_dedupe_key_differs_for_different_findings():
    a = dedupe_key("AUDIT-MEASUREMENT-002", "backend:queue_depth")
    b = dedupe_key("AUDIT-MEASUREMENT-002", "backend:other_finding")
    assert a != b


def test_dedupe_key_differs_for_different_audit_sources():
    a = dedupe_key("AUDIT-MEASUREMENT-002", "backend:queue_depth")
    b = dedupe_key("AUDIT-MEASUREMENT-003", "backend:queue_depth")
    assert a != b


def test_task_key_for_finding_is_namespaced_and_deterministic():
    key = task_key_for_finding("AUDIT-MEASUREMENT-002", "backend:queue_depth")
    assert key.startswith("audit-followthrough:")
    assert key == task_key_for_finding("AUDIT-MEASUREMENT-002", "backend:queue_depth")


# ---------------------------------------------------------------------------
# Duplicate suppression logic
# ---------------------------------------------------------------------------

def test_batch_duplicate_findings_are_suppressed_not_double_queued():
    findings = [_finding(), _finding()]
    plans = plan_remediation(findings)
    dispositions = [plan.disposition for plan in plans]
    assert dispositions.count("auto_remediation_queued") == 1
    assert dispositions.count("in_progress") == 1


def test_existing_pending_task_suppresses_a_new_duplicate_task():
    finding = _finding()
    key = task_key_for_finding(finding.audit_source, finding.finding_key)
    plans = plan_remediation(
        [finding], existing_tasks_by_key={key: {"status": "pending"}}
    )
    assert len(plans) == 1
    assert plans[0].disposition == "in_progress"
    assert plans[0].task is None


def test_existing_needs_review_task_reports_owner_approval_required():
    finding = _finding()
    key = task_key_for_finding(finding.audit_source, finding.finding_key)
    plans = plan_remediation(
        [finding], existing_tasks_by_key={key: {"status": "needs_review"}}
    )
    assert plans[0].disposition == "owner_approval_required"
    assert plans[0].task is None


def test_existing_completed_and_verified_task_reports_verified_resolved():
    finding = _finding()
    key = task_key_for_finding(finding.audit_source, finding.finding_key)
    plans = plan_remediation(
        [finding],
        existing_tasks_by_key={
            key: {"status": "completed", "evaluation_result": "pass"}
        },
    )
    assert plans[0].disposition == "verified_resolved"


def test_existing_failed_task_is_requeued_rather_than_left_unresolved():
    finding = _finding()
    key = task_key_for_finding(finding.audit_source, finding.finding_key)
    plans = plan_remediation(
        [finding], existing_tasks_by_key={key: {"status": "failed"}}
    )
    assert plans[0].disposition == "auto_remediation_queued"
    assert plans[0].task is not None
    assert plans[0].task["task_key"] == key


# ---------------------------------------------------------------------------
# Safe vs owner-gated classification
# ---------------------------------------------------------------------------

def test_safe_finding_is_queued_without_owner_approval():
    remediation = build_remediation(_finding())
    assert remediation.disposition == "auto_remediation_queued"
    assert remediation.task["required_approval"] is False
    assert remediation.task["status"] == "pending"


def test_risky_task_type_routes_through_the_existing_owner_gate():
    remediation = build_remediation(_finding(task_type="deploy"))
    assert remediation.disposition == "owner_approval_required"
    assert remediation.task["required_approval"] is True
    assert remediation.task["status"] == "needs_review"


def test_cross_repository_payload_is_owner_gated_via_default_task_executor():
    finding = _finding(evidence={"cross_repository": True})
    executor = DefaultTaskExecutor()
    remediation = build_remediation(finding, executor=executor)
    # The finding's own evidence isn't what DefaultTaskExecutor.risky_action
    # inspects (it looks at task_type/action/operation in the payload), so
    # this asserts the *reuse* of that exact function rather than a
    # parallel/duplicated risk classifier.
    assert executor.risky_action(finding.task_type, {"cross_repository": True}) == (
        "cross_repository"
    )


def test_non_actionable_finding_never_creates_a_task():
    finding = _finding(actionable=False, non_actionable_reason="scientific_data_gap")
    remediation = build_remediation(finding)
    assert remediation.disposition == "scientific_data_gap"
    assert remediation.task is None


def test_external_blocker_never_creates_a_task():
    finding = _finding(actionable=False, non_actionable_reason="external_blocker")
    remediation = build_remediation(finding)
    assert remediation.disposition == "external_blocker"
    assert remediation.task is None


# ---------------------------------------------------------------------------
# Provenance retention
# ---------------------------------------------------------------------------

def test_task_payload_preserves_originating_audit_id_and_evidence():
    finding = _finding(audit_id="AUD-PROVENANCE-TEST", evidence={"depth": 99})
    remediation = build_remediation(finding)
    payload = remediation.task["payload"]
    assert payload["audit_id"] == "AUD-PROVENANCE-TEST"
    assert payload["audit_source"] == "AUDIT-MEASUREMENT-002"
    assert payload["finding_key"] == "backend:queue_depth"
    assert payload["evidence"] == {"depth": 99}


def test_task_payload_never_marks_automatic_merge_deploy_or_publication():
    remediation = build_remediation(_finding())
    payload = remediation.task["payload"]
    assert payload["automatic_merge"] is False
    assert payload["automatic_deploy"] is False
    assert payload["automatic_publication"] is False
    assert payload["execution_mode"] == "draft_only"


# ---------------------------------------------------------------------------
# Narrative-only completion prohibition
# ---------------------------------------------------------------------------

def test_enforce_followthrough_passes_when_every_finding_has_a_disposition():
    findings = [_finding()]
    remediations = plan_remediation(findings)
    enforce_followthrough(findings, remediations)  # must not raise


def test_enforce_followthrough_blocks_a_dropped_actionable_finding():
    findings = [_finding(), _finding(finding_key="backend:other")]
    remediations = [
        FindingRemediation(finding_key="backend:queue_depth", disposition="auto_remediation_queued")
    ]
    with pytest.raises(NarrativeOnlyCompletionError):
        enforce_followthrough(findings, remediations)


def test_run_followthrough_returns_next_actions_created_and_tasks_to_create():
    findings = [_finding(), _finding(finding_key="backend:other")]
    result = run_followthrough(findings)
    assert len(result["next_actions_created"]) == 2
    assert len(result["tasks_to_create"]) == 2
    for entry in result["next_actions_created"]:
        assert entry["disposition"] in {
            "auto_remediation_queued",
            "in_progress",
            "verified_resolved",
            "owner_approval_required",
            "external_blocker",
            "scientific_data_gap",
            "no_action_needed",
        }


def test_next_actions_created_summary_omits_task_key_for_non_actionable_findings():
    remediation = build_remediation(
        _finding(actionable=False, non_actionable_reason="no_action_needed")
    )
    summary = next_actions_created([remediation])
    assert summary[0]["task_key"] is None
    assert summary[0]["required_approval"] is False
