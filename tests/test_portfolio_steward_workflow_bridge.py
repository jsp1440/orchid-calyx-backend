"""Portfolio Steward Workflow Bridge — 10 required tests.

Proves that the workflow bridge (scripts/oc_portfolio_steward_reconcile.py):
  1. Parses oc-prepared issue input correctly
  2. Passes real issue structure to the reconciler
  3. Hands admitted items to LabelDispatcher (canonical audited path)
  4. Transitions admitted items to oc-queued
  5. Blocks/OWNER_GATED items receive no transition
  6. Unchanged fingerprint yields zero repeated transitions
  7. Already oc-queued items are not re-admitted
  8. Second unchanged cycle is idempotent
  9. Zero paid provider calls across the full cycle
 10. Dispatcher failure is fail-closed (no queue corruption)

All tests are provider-free.  NO-API MODE REMAINS IN FORCE.
"""

from __future__ import annotations

from typing import Any

from runtime.portfolio_steward_reconciler import _filter_prepared, _issue_to_leaf
from scripts.oc_portfolio_steward_reconcile import (
    LabelDispatcher,
    LabelDispatchReceipt,
    build_frontend_snapshot,
    run_reconciliation,
)

# ---------------------------------------------------------------------------
# Shared fixtures (mirror orchid-continuum-frontend issue state)
# ---------------------------------------------------------------------------

_ISSUE_660: dict[str, Any] = {
    "number": 660,
    "title": "P1 gate-journey-research-matrix — Research Station Navigator",
    "labels": [{"name": "oc-prepared"}, {"name": "oc-p1"}],
    "createdAt": "2026-08-01T00:00:00Z",
}
_ISSUE_1264: dict[str, Any] = {
    "number": 1264,
    "title": "P1 completion-observer-healer — Observatory Repair",
    "labels": [{"name": "oc-prepared"}, {"name": "oc-p1"}],
    "createdAt": "2026-08-15T00:00:00Z",
}
_ISSUE_1085: dict[str, Any] = {
    "number": 1085,
    "title": "P2 frontend-freshness-backfill-matrix — Data Freshness Layer",
    "labels": [{"name": "oc-prepared"}, {"name": "oc-p2"}],
    "createdAt": "2026-07-20T00:00:00Z",
}
_ISSUE_BLOCKED: dict[str, Any] = {
    "number": 503,
    "title": "Blocked issue",
    "labels": [{"name": "oc-prepared"}, {"name": "oc-blocked"}],
    "createdAt": "2026-01-01T00:00:00Z",
}
_ISSUE_OWNER_GATE: dict[str, Any] = {
    "number": 504,
    "title": "Owner-gated issue",
    "labels": [{"name": "oc-prepared"}, {"name": "oc-owner-gate"}],
    "createdAt": "2026-01-01T00:00:00Z",
}
_ISSUE_QUEUED: dict[str, Any] = {
    "number": 660,
    "title": "P1 gate-journey-research-matrix — Research Station Navigator",
    "labels": [{"name": "oc-queued"}, {"name": "oc-p1"}],
    "createdAt": "2026-08-01T00:00:00Z",
}

_EMPTY_SNAPSHOT: dict[str, Any] = {"issues": [], "leases": [], "dispatch_fingerprints": []}


# ---------------------------------------------------------------------------
# Test 1: oc-prepared issue input is parsed correctly
# ---------------------------------------------------------------------------


def test_1_oc_prepared_input_parsed_correctly():
    """_filter_prepared + _issue_to_leaf parse real issue format correctly."""
    prepared = _filter_prepared([_ISSUE_660, _ISSUE_1264, _ISSUE_1085, _ISSUE_BLOCKED])
    numbers = {i["number"] for i in prepared}
    assert 660 in numbers
    assert 1264 in numbers
    assert 1085 in numbers
    assert 503 not in numbers  # oc-blocked disqualifies

    leaf_660 = _issue_to_leaf(_ISSUE_660)
    assert leaf_660 is not None
    assert leaf_660.key == "issue-660:retrieve-evidence"
    assert leaf_660.issue_number == 660


# ---------------------------------------------------------------------------
# Test 2: reconciler receives real issue structure
# ---------------------------------------------------------------------------


def test_2_reconciler_receives_real_issue_structure():
    """run_reconciliation accepts the real frontend issue dict format."""
    result = run_reconciliation(
        [_ISSUE_660],
        [_ISSUE_660],
        reserve_depth=1,
    )
    assert result["schema"] == "oc.portfolio-steward-workflow-bridge.v1"
    assert result["source_count"] == 1
    assert result["no_api_mode"] is True
    assert result["provider_launch_authorized"] is False


# ---------------------------------------------------------------------------
# Test 3: admitted item is handed to LabelDispatcher
# ---------------------------------------------------------------------------


def test_3_admitted_item_handed_to_label_dispatcher():
    """Each admitted proposal triggers exactly one LabelDispatcher.add_oc_queued call."""
    dispatcher = LabelDispatcher(execute=False)
    result = run_reconciliation(
        [_ISSUE_660],
        [],  # no existing queued issues → empty snapshot
        dispatcher=dispatcher,
        reserve_depth=1,
    )
    receipts = dispatcher.receipts()
    assert result["admitted_count"] == 1
    assert len(receipts) == 1
    assert receipts[0].issue_number == 660
    assert receipts[0].operation == "add_oc_queued"


# ---------------------------------------------------------------------------
# Test 4: admitted item gets oc-queued transition
# ---------------------------------------------------------------------------


def test_4_admitted_item_gets_oc_queued_transition():
    """Admitted issue receipt has status=dry_run (would be oc-queued in live mode)."""
    dispatcher = LabelDispatcher(execute=False)
    run_reconciliation([_ISSUE_660], [], dispatcher=dispatcher, reserve_depth=1)
    receipts = dispatcher.receipts()
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt.issue_number == 660
    assert receipt.status in ("dry_run", "dispatched")
    assert receipt.error is None


# ---------------------------------------------------------------------------
# Test 5: blocked / OWNER_GATED items receive no executable transition
# ---------------------------------------------------------------------------


def test_5_blocked_owner_gated_no_transition():
    """oc-blocked and oc-owner-gate issues generate zero dispatcher receipts."""
    dispatcher = LabelDispatcher(execute=False)
    result = run_reconciliation(
        [_ISSUE_BLOCKED, _ISSUE_OWNER_GATE],
        [],
        dispatcher=dispatcher,
        reserve_depth=2,
    )
    receipts = dispatcher.receipts()
    assert result["admitted_count"] == 0
    assert len(receipts) == 0
    assert result["source_count"] == 0  # filter removes both before bridge


# ---------------------------------------------------------------------------
# Test 6: unchanged fingerprint yields zero repeated transitions
# ---------------------------------------------------------------------------


def test_6_unchanged_fingerprint_zero_repeated_transitions():
    """If issue #660 fingerprint already in snapshot, second pass emits nothing."""
    # First pass — establish fingerprint
    dispatcher1 = LabelDispatcher(execute=False)
    first = run_reconciliation([_ISSUE_660], [], dispatcher=dispatcher1, reserve_depth=1)
    assert first["admitted_count"] == 1
    assert len(dispatcher1.receipts()) == 1

    # Verify first pass produced at least one proposal
    proposals = first["report"]["bridge_result"].get("proposals", [])
    assert proposals, "First pass must yield at least one proposal"

    # Second pass — #660 now appears as oc-queued in all_issues; snapshot excludes it
    dispatcher2 = LabelDispatcher(execute=False)
    second = run_reconciliation(
        [_ISSUE_660], [_ISSUE_QUEUED], dispatcher=dispatcher2, reserve_depth=1
    )
    assert second["admitted_count"] == 0
    assert len(dispatcher2.receipts()) == 0


# ---------------------------------------------------------------------------
# Test 7: already oc-queued item is not re-admitted
# ---------------------------------------------------------------------------


def test_7_already_queued_not_readmitted():
    """Issue #660 in oc-queued state (all-issues list) → snapshot excludes re-admission."""
    snapshot = build_frontend_snapshot([_ISSUE_QUEUED])
    assert snapshot["issues"], "Snapshot should include #660 as queued"
    fingerprint_present = snapshot["issues"][0]["material_fingerprint"]
    assert fingerprint_present  # non-empty fingerprint registered

    dispatcher = LabelDispatcher(execute=False)
    result = run_reconciliation(
        [_ISSUE_660],  # still in prepared list
        [_ISSUE_QUEUED],  # but all-issues shows it's queued
        dispatcher=dispatcher,
        reserve_depth=1,
    )
    assert result["admitted_count"] == 0
    assert len(dispatcher.receipts()) == 0


# ---------------------------------------------------------------------------
# Test 8: second unchanged workflow cycle is idempotent
# ---------------------------------------------------------------------------


def test_8_second_cycle_idempotent():
    """Two consecutive reconciliation cycles with unchanged input emit same admitted_count."""
    # First cycle
    d1 = LabelDispatcher(execute=False)
    first = run_reconciliation([_ISSUE_660], [], dispatcher=d1, reserve_depth=1)

    # Build snapshot from first-cycle proposals for second cycle
    proposals = first["report"]["bridge_result"].get("proposals", [])
    all_issues_after: list[dict[str, Any]] = []
    for p in proposals:
        src = p.get("source_ref", "")
        if src.startswith("#"):
            num = int(src[1:])
            all_issues_after.append(
                {"number": num, "labels": ["oc-queued"],
                 "material_fingerprint": p["material_fingerprint"],
                 "semantic_key": p["semantic_key"]}
            )

    # Second cycle — same prepared input but items now appear as queued
    d2 = LabelDispatcher(execute=False)
    second = run_reconciliation(
        [_ISSUE_660],
        all_issues_after,
        dispatcher=d2,
        reserve_depth=1,
    )

    assert second["admitted_count"] == 0, (
        "Second unchanged cycle must emit zero new admissions (idempotency)"
    )
    assert len(d2.receipts()) == 0


# ---------------------------------------------------------------------------
# Test 9: zero paid provider calls
# ---------------------------------------------------------------------------


def test_9_zero_paid_provider_calls():
    """All three frontier issues produce evidence with provider_api_called=False."""
    result = run_reconciliation(
        [_ISSUE_660, _ISSUE_1264, _ISSUE_1085],
        [],
        reserve_depth=3,
    )
    assert result["no_api_mode"] is True
    assert result["provider_launch_authorized"] is False

    report = result["report"]
    for ev in report.get("evidence", []):
        assert not ev.get("provider_api_called"), (
            f"Paid provider call detected for {ev.get('task_key')}"
        )


# ---------------------------------------------------------------------------
# Test 10: dispatcher failure is fail-closed (no queue corruption)
# ---------------------------------------------------------------------------


def test_10_dispatcher_failure_fail_closed():
    """A failing LabelDispatcher emits an error receipt but does not corrupt queue state."""

    class FailingDispatcher(LabelDispatcher):
        def add_oc_queued(self, issue_number: int) -> LabelDispatchReceipt:
            receipt = LabelDispatchReceipt(
                issue_number=issue_number,
                operation="add_oc_queued",
                status="failed",
                error="simulated gh CLI failure",
            )
            self._receipts.append(receipt)  # type: ignore[attr-defined]
            return receipt

    dispatcher = FailingDispatcher(execute=False)
    result = run_reconciliation([_ISSUE_660], [], dispatcher=dispatcher, reserve_depth=1)

    receipts = dispatcher.receipts()
    assert len(receipts) == 1
    assert receipts[0].status == "failed"
    assert receipts[0].error == "simulated gh CLI failure"

    # The reconciler still completed — admitted_count reflects bridge proposals, not gh success
    assert result["admitted_count"] == 1

    # A second pass with no snapshot still shows the issue eligible (no phantom oc-queued)
    d2 = LabelDispatcher(execute=False)
    second = run_reconciliation([_ISSUE_660], [], dispatcher=d2, reserve_depth=1)
    assert second["admitted_count"] == 1, (
        "Queue state must not be corrupted by a dispatcher failure"
    )
