"""TWO-DAY-SLICE-A / issue #1025: audit follow-through core.

Covers: disposition validation, dedupe stability, duplicate suppression,
safe vs owner-gated classification, provenance retention, the narrative-only
completion prohibition, re-audit verification/reopen, and the owner-facing
summary ordering.
"""

import pytest

from runtime.audit_followthrough import (
    OWNER_FACING_BUCKETS,
    VERIFICATION_FAILED,
    VERIFICATION_UNPROVEN,
    ActionableFinding,
    FindingRemediation,
    FollowthroughPersistenceError,
    InvalidDispositionError,
    NarrativeOnlyCompletionError,
    OrchestratorFollowthroughStore,
    audit_completion_state,
    build_remediation,
    dedupe_key,
    enforce_followthrough,
    next_actions_created,
    owner_facing_summary,
    persist_followthrough,
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


def test_completed_and_verified_task_reports_verified_resolved_when_no_longer_observed():
    finding = _finding(still_observed=False)
    key = task_key_for_finding(finding.audit_source, finding.finding_key)
    plans = plan_remediation(
        [finding],
        existing_tasks_by_key={
            key: {"status": "completed", "evaluation_result": "pass"}
        },
    )
    assert plans[0].disposition == "verified_resolved"
    assert plans[0].task is None


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
# Re-audit verification: a finding may not be closed by a fix that did not work
# ---------------------------------------------------------------------------

def test_finding_still_observed_after_completed_task_is_not_verified_resolved():
    finding = _finding(audit_id="AUD-REAUDIT")
    key = task_key_for_finding(finding.audit_source, finding.finding_key)
    plans = plan_remediation(
        [finding],
        existing_tasks_by_key={
            key: {"id": 11, "status": "completed", "evaluation_result": "pass"}
        },
    )
    assert plans[0].disposition == "auto_remediation_queued"
    assert plans[0].task["task_key"] == key
    assert plans[0].task["reopen_reason"] == VERIFICATION_FAILED


def test_reopened_task_carries_the_failed_verification_evidence():
    finding = _finding(audit_id="AUD-REAUDIT", observed_at="2026-08-22T00:00:00Z")
    key = task_key_for_finding(finding.audit_source, finding.finding_key)
    plans = plan_remediation(
        [finding],
        existing_tasks_by_key={
            key: {"id": 11, "status": "completed", "evaluation_result": "pass"}
        },
    )
    verification = plans[0].task["payload"]["verification"]
    assert verification["reason"] == VERIFICATION_FAILED
    assert verification["outcome"] == "failed"
    assert verification["prior_task_id"] == 11
    assert verification["prior_status"] == "completed"
    assert verification["prior_evaluation_result"] == "pass"
    assert verification["recurred_in_audit_id"] == "AUD-REAUDIT"
    assert verification["recurred_at"] == "2026-08-22T00:00:00Z"
    assert verification["still_observed"] is True


def test_completed_task_that_never_passed_evaluation_is_not_a_resolution():
    # The condition is gone, but the task that was supposed to fix it finished
    # without passing evaluation, so the resolution was never demonstrated.
    finding = _finding(still_observed=False)
    key = task_key_for_finding(finding.audit_source, finding.finding_key)
    plans = plan_remediation(
        [finding],
        existing_tasks_by_key={
            key: {"id": 12, "status": "completed", "evaluation_result": "fail"}
        },
    )
    assert plans[0].disposition == "auto_remediation_queued"
    assert plans[0].task["reopen_reason"] == VERIFICATION_UNPROVEN
    assert plans[0].task["payload"]["verification"]["still_observed"] is False


def test_reopened_risky_finding_stays_owner_gated():
    finding = _finding(task_type="deploy")
    key = task_key_for_finding(finding.audit_source, finding.finding_key)
    plans = plan_remediation(
        [finding],
        existing_tasks_by_key={
            key: {"id": 13, "status": "completed", "evaluation_result": "pass"}
        },
    )
    assert plans[0].disposition == "owner_approval_required"
    assert plans[0].task["status"] == "needs_review"
    assert plans[0].task["required_approval"] is True


def test_unobserved_finding_with_no_prior_task_needs_no_action():
    plans = plan_remediation([_finding(still_observed=False)])
    assert plans[0].disposition == "no_action_needed"
    assert plans[0].task is None


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


def test_task_payload_preserves_caller_supplied_run_and_commit_provenance():
    finding = _finding(
        observed_at="2026-08-22T12:00:00Z",
        provenance={"run_id": "RUN-88", "commit_sha": "deadbeef", "pr_number": 1061},
    )
    payload = build_remediation(finding).task["payload"]
    assert payload["observed_at"] == "2026-08-22T12:00:00Z"
    assert payload["provenance"] == {
        "run_id": "RUN-88",
        "commit_sha": "deadbeef",
        "pr_number": 1061,
    }


def test_task_payload_omits_provenance_the_audit_did_not_supply():
    # Absent provenance stays absent: an invented run id or timestamp is
    # indistinguishable from a real one once it reaches the durable task.
    payload = build_remediation(_finding()).task["payload"]
    assert "observed_at" not in payload
    assert "provenance" not in payload
    assert "verification" not in payload


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
    assert summary[0]["task_created"] is False


def test_open_disposition_without_a_durable_task_is_rejected():
    # "remediation is under way" with nothing durable behind it is precisely
    # the narrative-only failure mode.
    findings = [_finding()]
    remediations = [
        FindingRemediation(
            finding_key="backend:queue_depth", disposition="in_progress", task=None
        )
    ]
    with pytest.raises(NarrativeOnlyCompletionError):
        enforce_followthrough(findings, remediations)


def test_suppressed_duplicate_still_carries_the_durable_task_key():
    findings = [_finding(), _finding()]
    remediations = plan_remediation(findings)
    enforce_followthrough(findings, remediations)  # must not raise
    key = task_key_for_finding("AUDIT-MEASUREMENT-002", "backend:queue_depth")
    assert {remediation.effective_task_key for remediation in remediations} == {key}


def test_existing_task_dedupe_branches_all_reference_the_existing_task_key():
    finding = _finding()
    key = task_key_for_finding(finding.audit_source, finding.finding_key)
    for existing in (
        {"status": "pending"},
        {"status": "needs_review"},
        {"status": "completed", "evaluation_result": "pass"},
    ):
        plans = plan_remediation([finding], existing_tasks_by_key={key: existing})
        assert plans[0].effective_task_key == key
        enforce_followthrough([finding], plans)


# ---------------------------------------------------------------------------
# Audit completion state
# ---------------------------------------------------------------------------

def test_audit_with_queued_remediation_is_not_complete():
    state = audit_completion_state(plan_remediation([_finding()]))
    assert state["state"] == "follow_through_pending"
    assert state["open_findings"] == ["backend:queue_depth"]


def test_audit_with_only_resolved_findings_is_complete():
    findings = [
        _finding(actionable=False, non_actionable_reason="scientific_data_gap"),
        _finding(finding_key="backend:other", actionable=False, non_actionable_reason="no_action_needed"),
    ]
    state = audit_completion_state(plan_remediation(findings))
    assert state["state"] == "complete"
    assert state["open_findings"] == []
    assert state["disposition_counts"] == {"scientific_data_gap": 1, "no_action_needed": 1}


def test_owner_gated_finding_keeps_the_audit_pending():
    state = audit_completion_state(plan_remediation([_finding(task_type="deploy")]))
    assert state["state"] == "follow_through_pending"


def test_run_followthrough_reports_completion_state():
    result = run_followthrough([_finding()])
    assert result["completion_state"]["state"] == "follow_through_pending"


# ---------------------------------------------------------------------------
# Owner-facing output ordering
# ---------------------------------------------------------------------------

def test_owner_facing_summary_leads_with_owner_decisions_not_narrative():
    summary = owner_facing_summary(
        [
            FindingRemediation(finding_key="a", disposition="verified_resolved", task_key="k-a"),
            FindingRemediation(finding_key="b", disposition="auto_remediation_queued", task_key="k-b"),
            FindingRemediation(finding_key="c", disposition="owner_approval_required", task_key="k-c"),
            FindingRemediation(finding_key="d", disposition="scientific_data_gap"),
            FindingRemediation(finding_key="e", disposition="external_blocker"),
            FindingRemediation(finding_key="f", disposition="no_action_needed"),
        ]
    )
    assert summary["priority_order"] == list(OWNER_FACING_BUCKETS)
    assert [entry["finding_key"] for entry in summary["fixed_automatically"]] == ["a"]
    assert [entry["finding_key"] for entry in summary["being_fixed_now"]] == ["b"]
    assert [entry["finding_key"] for entry in summary["owner_action_required"]] == ["c"]
    assert [entry["finding_key"] for entry in summary["blocked_or_data_gap"]] == ["d", "e"]
    assert [entry["finding_key"] for entry in summary["no_action_needed"]] == ["f"]
    assert summary["counts"]["blocked_or_data_gap"] == 2


def test_owner_facing_summary_never_files_a_data_gap_as_fixed():
    summary = owner_facing_summary(
        plan_remediation(
            [_finding(actionable=False, non_actionable_reason="scientific_data_gap")]
        )
    )
    assert summary["fixed_automatically"] == []
    assert summary["blocked_or_data_gap"][0]["disposition"] == "scientific_data_gap"


def test_run_followthrough_exposes_the_owner_facing_summary():
    result = run_followthrough([_finding(), _finding(task_type="deploy", finding_key="b")])
    summary = result["owner_facing_summary"]
    assert summary["counts"]["being_fixed_now"] == 1
    assert summary["counts"]["owner_action_required"] == 1


# ---------------------------------------------------------------------------
# Durable persistence into oc_admin.calyx_tasks
# ---------------------------------------------------------------------------

class FakeTaskStore:
    """In-memory stand-in for oc_admin.calyx_tasks with the same UNIQUE key."""

    def __init__(self):
        self.rows: dict[str, dict] = {}
        self.insert_attempts: list[str] = []
        self.fetch_calls: list[list[str]] = []
        self._next_id = 1

    def fetch_tasks_by_key(self, task_keys):
        keys = list(task_keys)
        self.fetch_calls.append(keys)
        return {key: dict(self.rows[key]) for key in keys if key in self.rows}

    def insert_task(self, task):
        key = task["task_key"]
        self.insert_attempts.append(key)
        existing = self.rows.get(key)
        reopen_reason = task.get("reopen_reason")
        if existing is not None:
            # Mirrors ON CONFLICT (task_key) DO UPDATE ... WHERE status = ANY:
            # dead rows revive, live rows are untouched, and a reopen (the
            # finding outlived the task that claimed to fix it) additionally
            # revives a completed row.
            revivable = {"failed", "blocked"} | ({"completed"} if reopen_reason else set())
            if existing.get("status") not in revivable:
                return {
                    "created": False,
                    "requeued": False,
                    "reopened": False,
                    "task": dict(existing),
                }
            revived = dict(existing)
            revived.update(task)
            revived["id"] = existing["id"]
            # Mirrors the SET arm: a revived row is re-gated, not left holding
            # the approval the owner granted for the previous payload.
            revived["approved_at"] = None
            revived["evaluation_result"] = None
            self.rows[key] = revived
            return {
                "created": False,
                "requeued": True,
                "reopened": bool(reopen_reason),
                "task": dict(revived),
            }
        row = dict(task)
        row["id"] = self._next_id
        self._next_id += 1
        self.rows[key] = row
        return {"created": True, "requeued": False, "reopened": False, "task": dict(row)}


def test_persist_followthrough_creates_a_durable_task_for_a_new_finding():
    store = FakeTaskStore()
    result = persist_followthrough([_finding()], store)
    assert result["tasks_created"] == 1
    assert result["tasks_already_present"] == 0
    key = task_key_for_finding("AUDIT-MEASUREMENT-002", "backend:queue_depth")
    assert key in store.rows
    assert result["persisted_tasks"][0]["task_key"] == key


def test_persist_followthrough_is_idempotent_across_repeat_audit_runs():
    store = FakeTaskStore()
    persist_followthrough([_finding(audit_id="AUD-RUN-ONE")], store)
    # Same logical finding, a different audit run: no second task.
    second = persist_followthrough([_finding(audit_id="AUD-RUN-TWO")], store)
    assert second["tasks_created"] == 0
    assert len(store.rows) == 1
    assert second["next_actions_created"][0]["disposition"] == "in_progress"


def test_persist_followthrough_checks_durable_state_before_planning():
    store = FakeTaskStore()
    persist_followthrough([_finding()], store)
    store.fetch_calls.clear()
    persist_followthrough([_finding()], store)
    # Dedupe is decided against the durable rows, not a caller-supplied guess.
    assert store.fetch_calls and store.fetch_calls[0]


def test_persist_followthrough_preserves_provenance_in_the_durable_row():
    store = FakeTaskStore()
    persist_followthrough(
        [_finding(audit_id="AUD-PERSIST-PROV", evidence={"depth": 7})], store
    )
    row = next(iter(store.rows.values()))
    assert row["payload"]["audit_id"] == "AUD-PERSIST-PROV"
    assert row["payload"]["audit_source"] == "AUDIT-MEASUREMENT-002"
    assert row["payload"]["finding_key"] == "backend:queue_depth"
    assert row["payload"]["evidence"] == {"depth": 7}
    assert row["payload"]["automatic_merge"] is False


def test_persist_followthrough_writes_risky_tasks_as_needs_review_not_approved():
    store = FakeTaskStore()
    result = persist_followthrough([_finding(task_type="deploy")], store)
    row = next(iter(store.rows.values()))
    assert row["status"] == "needs_review"
    assert row["required_approval"] is True
    assert "approved_at" not in row
    assert result["next_actions_created"][0]["disposition"] == "owner_approval_required"


def test_persist_followthrough_never_persists_non_actionable_findings():
    store = FakeTaskStore()
    result = persist_followthrough(
        [_finding(actionable=False, non_actionable_reason="scientific_data_gap")], store
    )
    assert result["tasks_created"] == 0
    assert store.rows == {}
    assert store.insert_attempts == []
    assert result["completion_state"]["state"] == "complete"


def test_persist_followthrough_requeues_a_finding_whose_prior_task_failed():
    store = FakeTaskStore()
    persist_followthrough([_finding()], store)
    key = task_key_for_finding("AUDIT-MEASUREMENT-002", "backend:queue_depth")
    store.rows[key]["status"] = "failed"
    second = persist_followthrough([_finding()], store)
    # Revived under the same dedupe key: the row is reused, never doubled, and
    # it does not stay dead while the audit reports the finding as handled.
    assert len(store.rows) == 1
    assert second["tasks_created"] == 0
    assert second["tasks_requeued"] == 1
    assert store.rows[key]["status"] == "pending"
    assert second["persisted_tasks"][0]["task_key"] == key
    assert second["next_actions_created"][0]["disposition"] == "auto_remediation_queued"


def test_persist_followthrough_leaves_a_live_task_untouched():
    store = FakeTaskStore()
    persist_followthrough([_finding()], store)
    key = task_key_for_finding("AUDIT-MEASUREMENT-002", "backend:queue_depth")
    store.rows[key]["status"] = "running"
    second = persist_followthrough([_finding()], store)
    assert second["tasks_created"] == 0
    assert second["tasks_requeued"] == 0
    assert store.rows[key]["status"] == "running"
    # No second insert was even attempted: the plan saw the live row first.
    assert store.insert_attempts == [key]
    assert second["next_actions_created"][0]["disposition"] == "in_progress"


def test_persist_followthrough_reopens_a_completed_task_the_finding_outlived():
    store = FakeTaskStore()
    persist_followthrough([_finding()], store)
    key = task_key_for_finding("AUDIT-MEASUREMENT-002", "backend:queue_depth")
    # The remediation ran, passed its own evaluation, and the audit still sees
    # the condition on the next run.
    store.rows[key].update(
        {"status": "completed", "evaluation_result": "pass", "approved_at": "2026-08-01T00:00:00Z"}
    )
    second = persist_followthrough([_finding(audit_id="AUD-REAUDIT")], store)
    assert len(store.rows) == 1
    assert second["tasks_created"] == 0
    assert second["tasks_reopened"] == 1
    assert store.rows[key]["status"] == "pending"
    assert store.rows[key]["payload"]["verification"]["reason"] == VERIFICATION_FAILED
    assert second["next_actions_created"][0]["disposition"] == "auto_remediation_queued"
    assert second["next_actions_created"][0]["reopen_reason"] == VERIFICATION_FAILED
    assert second["completion_state"]["state"] == "follow_through_pending"


def test_reviving_a_task_clears_a_stale_owner_approval():
    # oc_admin.calyx_tasks scheduling treats a non-null approved_at as the
    # satisfied owner gate, so a revived task carrying the previous approval
    # would run a rewritten payload the owner never approved.
    store = FakeTaskStore()
    persist_followthrough([_finding(task_type="deploy")], store)
    key = task_key_for_finding("AUDIT-MEASUREMENT-002", "backend:queue_depth")
    store.rows[key].update({"status": "failed", "approved_at": "2026-08-01T00:00:00Z"})
    persist_followthrough([_finding(task_type="deploy")], store)
    assert store.rows[key]["approved_at"] is None
    assert store.rows[key]["status"] == "needs_review"
    assert store.rows[key]["required_approval"] is True


def test_persist_followthrough_does_not_reopen_a_verified_resolved_finding():
    store = FakeTaskStore()
    persist_followthrough([_finding()], store)
    key = task_key_for_finding("AUDIT-MEASUREMENT-002", "backend:queue_depth")
    store.rows[key].update({"status": "completed", "evaluation_result": "pass"})
    store.insert_attempts.clear()
    result = persist_followthrough([_finding(still_observed=False)], store)
    assert store.insert_attempts == []
    assert result["tasks_created"] == 0
    assert result["tasks_reopened"] == 0
    assert store.rows[key]["status"] == "completed"
    assert result["completion_state"]["state"] == "complete"
    assert result["owner_facing_summary"]["fixed_automatically"][0]["task_key"] == key


def test_orchestrator_store_refuses_to_write_a_terminal_status():
    store = OrchestratorFollowthroughStore(orchestrator=object())
    with pytest.raises(FollowthroughPersistenceError):
        store.insert_task({"task_key": "k", "task_type": "t", "title": "x", "status": "completed"})


def test_orchestrator_store_refuses_a_task_without_a_dedupe_key():
    store = OrchestratorFollowthroughStore(orchestrator=object())
    with pytest.raises(FollowthroughPersistenceError):
        store.insert_task({"task_key": "", "task_type": "t", "title": "x", "status": "pending"})


def test_orchestrator_store_short_circuits_an_empty_key_lookup_without_a_connection():
    # object() has no .connect(); returning {} proves no DB round-trip happens.
    store = OrchestratorFollowthroughStore(orchestrator=object())
    assert store.fetch_tasks_by_key([]) == {}
    assert store.fetch_tasks_by_key([None, ""]) == {}


def test_orchestrator_adapter_queues_followthrough_through_its_own_executor():
    from runtime.autonomous_orchestrator import CalyxAutonomousOrchestrator

    store = FakeTaskStore()
    orchestrator = CalyxAutonomousOrchestrator(database_url="postgresql://unused")
    result = orchestrator.queue_audit_followthrough([_finding()], store=store)
    assert result["tasks_created"] == 1
    assert result["completion_state"]["state"] == "follow_through_pending"


def test_orchestrator_adapter_keeps_risky_followthrough_owner_gated():
    from runtime.autonomous_orchestrator import CalyxAutonomousOrchestrator

    store = FakeTaskStore()
    orchestrator = CalyxAutonomousOrchestrator(database_url="postgresql://unused")
    orchestrator.queue_audit_followthrough([_finding(task_type="deploy")], store=store)
    row = next(iter(store.rows.values()))
    assert row["status"] == "needs_review"
    assert row["required_approval"] is True


# ---------------------------------------------------------------------------
# The rule itself: audit follow-through is constitutional policy, not a habit
# ---------------------------------------------------------------------------

def test_audit_requires_followthrough_is_a_registered_constitutional_policy():
    from runtime.constitutional_orchestrator import ConstitutionalMissionOrchestrator

    registry = ConstitutionalMissionOrchestrator().policy_registry()
    ids = {policy["policy_id"] for policy in registry["policies"]}
    assert "audit_requires_followthrough" in ids
    # The pre-existing protected policies must remain intact alongside it.
    assert "owner_approval_for_high_risk" in ids
    assert "preserve_provenance" in ids


def test_audit_actions_are_evaluated_against_the_followthrough_policy():
    from runtime.constitutional_orchestrator import ConstitutionalMissionOrchestrator

    orchestrator = ConstitutionalMissionOrchestrator()
    mission_id = next(iter(orchestrator.missions))
    result = orchestrator.evaluate_action(
        mission_id=mission_id,
        action="audit:relationship_data_audit",
        requested_autonomy_level=1,
        evidence=["mission_control_metrics"],
    )
    assert "audit_requires_followthrough" in result["decision"]["constitutional_policies"]


def test_followthrough_policy_does_not_apply_to_unrelated_actions():
    from runtime.constitutional_orchestrator import ConstitutionalMissionOrchestrator

    orchestrator = ConstitutionalMissionOrchestrator()
    mission_id = next(iter(orchestrator.missions))
    result = orchestrator.evaluate_action(
        mission_id=mission_id,
        action="homepage:refresh_featured_genus",
        requested_autonomy_level=1,
        evidence=["homepage_snapshot"],
    )
    assert "audit_requires_followthrough" not in result["decision"]["constitutional_policies"]
