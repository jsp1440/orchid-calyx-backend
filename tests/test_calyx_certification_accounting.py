from __future__ import annotations

from scripts.calyx_engineering_certify import _repair_outcome


def test_repair_outcome_requires_verified_commit() -> None:
    assert _repair_outcome({"status": "repair_committed_waiting_for_ci", "commits": 1}) == "repair_committed"
    assert _repair_outcome({"status": "repair_committed_waiting_for_ci", "commits": 0}) == "repair_not_applied"


def test_repair_outcome_preserves_not_applied_states() -> None:
    assert _repair_outcome({"status": "repair_not_applied_no_failed_checks", "commits": 0}) == "repair_not_applied"
    assert _repair_outcome({"status": "repair_not_applied_branch_unchanged", "commits": 0}) == "repair_not_applied"


def test_repair_outcome_marks_uncommitted_generated_work() -> None:
    assert _repair_outcome({"status": "provider_changes_generated", "commits": 1}) == "repair_generated"
