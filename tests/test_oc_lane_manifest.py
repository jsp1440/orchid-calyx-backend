"""Tests for the Orchid Continuum lane manifest builder.

Verifies:
- All five AGENTS.md lanes are present
- State classification is accurate
- Lane assignment is deterministic
- Counts are consistent
- Safety invariants are present in output
- Unassigned issues are captured
"""

from __future__ import annotations

from scripts.oc_lane_manifest import (
    LANES,
    SCHEMA_VERSION,
    _classify_lane,
    build_lane_manifest,
)


def _issue(number: int, title: str, labels: list[str]) -> dict:
    return {"number": number, "title": title, "labels": [{"name": lbl} for lbl in labels]}


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------


def test_five_lanes_always_present():
    manifest = build_lane_manifest([])
    ids = {lane["lane_id"] for lane in manifest["lanes"]}
    assert ids == {"L1", "L2", "L3", "L4", "L5"}


def test_schema_version_present():
    manifest = build_lane_manifest([])
    assert manifest["schema_version"] == SCHEMA_VERSION


def test_safety_invariants_present():
    manifest = build_lane_manifest([])
    assert manifest["automatic_publication"] is False
    assert manifest["knowledge_graph_mutation"] is False


def test_all_lane_ids_match_definition():
    manifest = build_lane_manifest([])
    defined_ids = {lane["lane_id"] for lane in LANES}
    result_ids = {lane["lane_id"] for lane in manifest["lanes"]}
    assert defined_ids == result_ids


# ---------------------------------------------------------------------------
# State classification
# ---------------------------------------------------------------------------


def test_running_issue_is_active():
    issues = [_issue(1, "P0 brain task", ["oc-running", "oc-p0"])]
    manifest = build_lane_manifest(issues)
    assert manifest["summary"]["active"] == 1


def test_queued_issue_is_ready():
    issues = [_issue(2, "P1 taxonomy work", ["oc-queued", "oc-p1"])]
    manifest = build_lane_manifest(issues)
    assert manifest["summary"]["ready"] == 1


def test_repair_backoff_is_blocked():
    issues = [_issue(3, "P0 stabilize", ["oc-repair-backoff", "oc-p0"])]
    manifest = build_lane_manifest(issues)
    assert manifest["summary"]["blocked"] == 1


def test_validating_is_waiting_validation():
    issues = [_issue(4, "P0 runtime", ["oc-validating", "oc-p0"])]
    manifest = build_lane_manifest(issues)
    assert manifest["summary"]["validating"] == 1


def test_done_is_complete():
    issues = [_issue(5, "completed work", ["oc-done"])]
    manifest = build_lane_manifest(issues)
    assert manifest["summary"]["complete"] == 1


# ---------------------------------------------------------------------------
# Lane assignment
# ---------------------------------------------------------------------------


def test_brain_issue_goes_to_l1():
    issues = [_issue(10, "CALYX-SYNTHESIS-001 brain ledger", ["oc-queued"])]
    manifest = build_lane_manifest(issues)
    l1 = next(lane for lane in manifest["lanes"] if lane["lane_id"] == "L1")
    assert any(t["number"] == 10 for t in l1["tasks"])


def test_taxonomy_issue_goes_to_l2():
    issues = [_issue(20, "Hassler release taxonomy", ["oc-queued"])]
    manifest = build_lane_manifest(issues)
    l2 = next(lane for lane in manifest["lanes"] if lane["lane_id"] == "L2")
    assert any(t["number"] == 20 for t in l2["tasks"])


def test_literature_issue_goes_to_l3():
    issues = [_issue(30, "literature corpus extraction", ["oc-queued"])]
    manifest = build_lane_manifest(issues)
    l3 = next(lane for lane in manifest["lanes"] if lane["lane_id"] == "L3")
    assert any(t["number"] == 30 for t in l3["tasks"])


def test_show_management_goes_to_l4():
    issues = [_issue(40, "OC-COMPLETE-008 show management UI", ["oc-queued"])]
    manifest = build_lane_manifest(issues)
    l4 = next(lane for lane in manifest["lanes"] if lane["lane_id"] == "L4")
    assert any(t["number"] == 40 for t in l4["tasks"])


def test_dispatch_event_goes_to_l5():
    issues = [_issue(50, "ORCHESTRATION-EVENT-DRIVEN-001 dispatch", ["oc-queued"])]
    manifest = build_lane_manifest(issues)
    l5 = next(lane for lane in manifest["lanes"] if lane["lane_id"] == "L5")
    assert any(t["number"] == 50 for t in l5["tasks"])


def test_unclassifiable_issue_is_unassigned():
    issues = [_issue(99, "something completely unrelated xyz", ["oc-queued"])]
    manifest = build_lane_manifest(issues)
    assert any(t["number"] == 99 for t in manifest["unassigned"])


# ---------------------------------------------------------------------------
# Active task and next eligible
# ---------------------------------------------------------------------------


def test_active_task_populated_for_running_issue():
    issues = [_issue(100, "P0 brain synthesis", ["oc-running", "oc-p0"])]
    manifest = build_lane_manifest(issues)
    l1 = next(lane for lane in manifest["lanes"] if lane["lane_id"] == "L1")
    assert l1["active_task"] is not None
    assert l1["active_task"]["number"] == 100


def test_next_eligible_populated_for_queued_issue():
    issues = [_issue(200, "P1 taxonomy backfill", ["oc-queued", "oc-p1"])]
    manifest = build_lane_manifest(issues)
    l2 = next(lane for lane in manifest["lanes"] if lane["lane_id"] == "L2")
    assert l2["next_eligible"] is not None
    assert l2["next_eligible"]["number"] == 200


# ---------------------------------------------------------------------------
# Summary counts are consistent
# ---------------------------------------------------------------------------


def test_summary_total_matches_input():
    issues = [
        _issue(1, "brain task", ["oc-running"]),
        _issue(2, "taxonomy task", ["oc-queued"]),
        _issue(3, "literature task", ["oc-blocked"]),
    ]
    manifest = build_lane_manifest(issues)
    assert manifest["summary"]["total_issues"] == 3


def test_summary_counts_add_up():
    issues = [
        _issue(1, "brain synthesis", ["oc-running"]),
        _issue(2, "hassler taxonomy", ["oc-queued"]),
        _issue(3, "taxonomy blocked", ["oc-repair-backoff"]),
        _issue(4, "literature validating", ["oc-validating"]),
    ]
    manifest = build_lane_manifest(issues)
    s = manifest["summary"]
    # active + ready + blocked + validating + complete + unassigned ≥ total
    # (unassigned are also counted in the lane-specific states)
    assert s["active"] == 1
    assert s["ready"] == 1
    assert s["blocked"] == 1
    assert s["validating"] == 1


# ---------------------------------------------------------------------------
# Word-boundary false-positive guards
# ---------------------------------------------------------------------------


def _ti(title: str) -> dict:
    """Minimal issue dict for _classify_lane testing."""
    return {"number": 0, "title": title, "labels": []}


def test_ui_keyword_does_not_match_fluid():
    # "ui" is a substring of "fluid" but must not classify it as L4.
    assert _classify_lane(_ti("hydraulic fluid dynamics study")) != "L4"


def test_ui_keyword_does_not_match_build():
    # "ui" is a substring of "build" but must not classify it as L4.
    assert _classify_lane(_ti("build pipeline optimisation")) != "L4"


def test_ui_keyword_matches_when_standalone():
    assert _classify_lane(_ti("UI redesign for operator interface")) == "L4"


def test_api_keyword_does_not_match_rapid():
    # "api" is a substring of "rapid" but must not classify it as L4.
    assert _classify_lane(_ti("rapid response workflow")) != "L4"


def test_api_keyword_does_not_match_apiary():
    # "api" at the start of a word "apiary" must not classify it as L4.
    # "apiary" contains no other L4 keyword, so result must not be L4.
    assert _classify_lane(_ti("apiary management practices")) != "L4"


def test_api_keyword_matches_when_standalone():
    assert _classify_lane(_ti("REST api endpoint certification")) == "L4"
