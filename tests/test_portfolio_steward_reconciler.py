"""Portfolio Steward reconciler — operational end-to-end tests.

Uses real issue data matching orchid-continuum-frontend issues:
  #660  gate-journey-research-matrix        oc-prepared, oc-p1
  #1264 completion-observer-healer          oc-prepared, oc-p1
  #1085 frontend-freshness-backfill-matrix  oc-prepared, oc-p2

These are the same issues used in test_durable_queue_bridge_acceptance.py.
All tests are provider-free and use SQLite in-memory.
"""

from __future__ import annotations

from typing import Any

from app.calyx_orchestrator.deep_orchestrate import Priority
from runtime.portfolio_steward_reconciler import (
    PortfolioStewardReport,
    _filter_prepared,
    _issue_to_leaf,
    _priority_from_labels,
    reconcile,
)

# ---------------------------------------------------------------------------
# Real-world issue fixtures matching orchid-continuum-frontend state
# ---------------------------------------------------------------------------

_ISSUE_660 = {
    "number": 660,
    "title": "P1 gate-journey-research-matrix — Research Station Navigator",
    "labels": [{"name": "oc-prepared"}, {"name": "oc-p1"}],
    "createdAt": "2026-08-01T00:00:00Z",
}
_ISSUE_1264 = {
    "number": 1264,
    "title": "P1 completion-observer-healer — Observatory Repair",
    "labels": [{"name": "oc-prepared"}, {"name": "oc-p1"}],
    "createdAt": "2026-08-15T00:00:00Z",
}
_ISSUE_1085 = {
    "number": 1085,
    "title": "P2 frontend-freshness-backfill-matrix — Data Freshness Layer",
    "labels": [{"name": "oc-prepared"}, {"name": "oc-p2"}],
    "createdAt": "2026-07-20T00:00:00Z",
}
_ISSUE_DONE = {
    "number": 501,
    "title": "Completed issue",
    "labels": [{"name": "oc-done"}],
    "createdAt": "2026-01-01T00:00:00Z",
}
_ISSUE_BLOCKED = {
    "number": 502,
    "title": "Blocked issue",
    "labels": [{"name": "oc-prepared"}, {"name": "oc-blocked"}],
    "createdAt": "2026-01-01T00:00:00Z",
}
_ISSUE_NO_NUMBER: dict[str, Any] = {
    "title": "Missing number issue",
    "labels": [{"name": "oc-prepared"}],
}

_ALL_ISSUES = [_ISSUE_660, _ISSUE_1264, _ISSUE_1085, _ISSUE_DONE, _ISSUE_BLOCKED]
_EMPTY_SNAPSHOT: dict[str, Any] = {"issues": [], "leases": [], "dispatch_fingerprints": []}


# ---------------------------------------------------------------------------
# Unit tests — helpers
# ---------------------------------------------------------------------------


def test_filter_prepared_excludes_done_and_blocked():
    result = _filter_prepared(_ALL_ISSUES)
    numbers = {i["number"] for i in result}
    assert numbers == {660, 1264, 1085}
    assert 501 not in numbers  # oc-done
    assert 502 not in numbers  # oc-blocked


def test_issue_to_leaf_maps_correctly():
    leaf = _issue_to_leaf(_ISSUE_660)
    assert leaf is not None
    assert leaf.key == "issue-660:retrieve-evidence"
    assert leaf.issue_number == 660
    assert leaf.priority == Priority.P1
    assert leaf.authority_class == "bounded_workspace_mutation"
    assert leaf.consequence_risk == "low"


def test_issue_to_leaf_returns_none_for_missing_number():
    leaf = _issue_to_leaf(_ISSUE_NO_NUMBER)
    assert leaf is None


def test_priority_from_labels():
    assert _priority_from_labels(["oc-prepared", "oc-p0"]) == Priority.P0
    assert _priority_from_labels(["oc-p3"]) == Priority.P3
    assert _priority_from_labels(["oc-prepared"]) == Priority.P2  # default


# ---------------------------------------------------------------------------
# Integration tests — reconcile()
# ---------------------------------------------------------------------------


def test_reconcile_admits_and_executes_prepared_issues():
    """Single oc-prepared issue (#660) admitted and executed end-to-end."""
    report = reconcile([_ISSUE_660], _EMPTY_SNAPSHOT, reserve_depth=1)

    assert isinstance(report, PortfolioStewardReport)
    assert report.schema == "oc.portfolio-steward-reconciler.v1"
    assert report.source_count == 1
    assert report.admitted_count == 1
    assert report.executed_count == 1
    assert report.blocked_count == 0
    assert report.rejected_count == 0
    assert report.provider_launch_authorized is False
    assert report.no_api_mode is True


def test_reconcile_filters_done_and_blocked_before_bridge():
    """oc-done and oc-blocked issues are never sourced to the bridge."""
    report = reconcile(_ALL_ISSUES, _EMPTY_SNAPSHOT, reserve_depth=3)

    assert report.source_count == 3  # only 660, 1264, 1085
    assert report.admitted_count <= 3
    assert report.provider_launch_authorized is False


def test_reconcile_zero_paid_provider_calls():
    """DeterministicResearchWorker produces zero paid provider calls."""
    report = reconcile([_ISSUE_660, _ISSUE_1264], _EMPTY_SNAPSHOT, reserve_depth=2)

    for ev in report.evidence:
        assert not ev.get("provider_api_called"), (
            f"Paid provider call detected in evidence: {ev}"
        )
    assert report.provider_launch_authorized is False


def test_reconcile_dedup_suppresses_already_queued_fingerprint():
    """Second reconcile with same fingerprint in snapshot → zero new proposals."""
    # First pass
    first = reconcile([_ISSUE_660], _EMPTY_SNAPSHOT, reserve_depth=1)
    assert first.admitted_count == 1

    # Build snapshot from first-pass bridge output
    bridge = first.bridge_result
    proposal = bridge["proposals"][0]
    snapshot_with_fp: dict[str, Any] = {
        "issues": [{"number": 660, "labels": ["oc-queued"],
                    "material_fingerprint": proposal["material_fingerprint"],
                    "semantic_key": proposal["semantic_key"]}],
        "leases": [],
        "dispatch_fingerprints": [],
    }

    # Second pass with same item in snapshot
    second = reconcile([_ISSUE_660], snapshot_with_fp, reserve_depth=1)
    assert second.admitted_count == 0
    assert second.source_count == 1
    # Status must indicate reserve is satisfied or no eligible candidates
    bridge_status = second.bridge_result.get("status", "")
    assert "satisfied" in bridge_status or "no_eligible" in bridge_status, bridge_status


def test_reconcile_depletion_refill_from_new_issue():
    """After #660 is complete (excluded from prepared pool), #1264 is admitted."""
    # Simulate depletion: only #1264 in the prepared pool (660 has been retired)
    report = reconcile([_ISSUE_1264], _EMPTY_SNAPSHOT, reserve_depth=1)

    assert report.source_count == 1
    assert report.admitted_count == 1
    assert report.bridge_result["proposals"][0]["source_ref"] == "#1264"
    assert report.executed_count == 1


def test_reconcile_terminal_state_no_orphaned_tasks():
    """All admitted tasks reach a terminal state (no LEASED or READY orphans)."""
    report = reconcile([_ISSUE_660, _ISSUE_1264], _EMPTY_SNAPSHOT, reserve_depth=2)

    for ev in report.evidence:
        state = ev.get("state")
        assert state in ("completed", "blocked"), (
            f"Non-terminal task state after reconcile: {state} for {ev.get('task_key')}"
        )


def test_reconcile_returns_structured_evidence():
    """Evidence records include issue_number, task_key, state, and output."""
    report = reconcile([_ISSUE_660], _EMPTY_SNAPSHOT, reserve_depth=1)

    assert len(report.evidence) == 1
    ev = report.evidence[0]
    assert ev["issue_number"] == 660
    assert ev["task_key"] == "issue-660:retrieve-evidence"
    assert ev["state"] == "completed"
    assert ev["evidence"] is not None
    assert ev["evidence"]["output"]["step"] == "retrieve_evidence"


def test_reconcile_empty_input_returns_zero_admitted():
    """Empty issue list produces a valid report with zero sourced/admitted."""
    report = reconcile([], _EMPTY_SNAPSHOT)
    assert report.source_count == 0
    assert report.admitted_count == 0
    assert report.executed_count == 0
    assert report.no_api_mode is True


def test_reconcile_all_three_frontier_issues():
    """All three frontier oc-prepared issues (#660, #1264, #1085) admitted and executed."""
    report = reconcile(
        [_ISSUE_660, _ISSUE_1264, _ISSUE_1085],
        _EMPTY_SNAPSHOT,
        reserve_depth=3,
        max_tasks=10,
        max_iterations=6,
    )

    assert report.source_count == 3
    assert report.admitted_count == 3
    assert report.executed_count == 3
    assert report.blocked_count == 0
    for ev in report.evidence:
        assert not ev.get("provider_api_called")
