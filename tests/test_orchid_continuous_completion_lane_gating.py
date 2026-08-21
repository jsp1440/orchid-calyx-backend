"""Structural regression contract for the live continuous-completion control plane.

The original version of this test described the retired inline planner/prepare/
lane1-lane3 architecture. The production engine now has a lightweight scheduler
(`orchid-continuous-completion.yml`) which dispatches one parameterized worker
workflow (`orchid-completion-lane.yml`). These tests pin the safety properties
that matter in that architecture: one worker per issue, durable-PR reconciliation,
no premature lease stealing, bounded repair authorization, repair-state self-heal,
and no Claude retry for a validation-dispatch outage.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

SCHEDULER = Path(".github/workflows/orchid-continuous-completion.yml")
NORMALIZE_STEP = "name: Normalize portfolio priority and heal orphaned repair authorizations"
DISPATCH_STEP = "name: Dispatch priority-aware completion workers"
LANE = Path(".github/workflows/orchid-completion-lane.yml")


@pytest.fixture(scope="module")
def scheduler_text() -> str:
    return SCHEDULER.read_text()


@pytest.fixture(scope="module")
def lane_text() -> str:
    return LANE.read_text()


@pytest.fixture(scope="module")
def scheduler() -> dict:
    return yaml.safe_load(SCHEDULER.read_text())


@pytest.fixture(scope="module")
def lane() -> dict:
    return yaml.safe_load(LANE.read_text())


def test_both_workflows_are_valid_yaml(scheduler, lane):
    assert isinstance(scheduler, dict)
    assert isinstance(lane, dict)


def test_scheduler_never_runs_claude_inline(scheduler_text):
    assert "anthropics/claude-code-action" not in scheduler_text
    assert "gh workflow run orchid-completion-lane.yml" in scheduler_text


def test_completion_lane_is_serialized_per_issue(lane_text):
    assert "group: orchid-completion-lane-${{ github.repository }}-${{ inputs.issue_number }}" in lane_text
    assert "cancel-in-progress: false" in lane_text


def test_stale_duplicate_dispatch_is_suppressed_before_claude(lane_text):
    assert "name: Verify scheduler lease" in lane_text
    assert '[[ "$labels" == *oc-running* ]]' in lane_text
    assert "if: steps.lease.outputs.execute == 'true'" in lane_text
    claude_pos = lane_text.index("uses: anthropics/claude-code-action@v1")
    lease_pos = lane_text.index("name: Verify scheduler lease")
    assert lease_pos < claude_pos


def test_scheduler_does_not_steal_an_active_repair_lease(scheduler_text):
    assert "if (( now - epoch <= 4800 )); then" in scheduler_text
    assert 'if [[ "$labels" == *oc-running* ]]; then' in scheduler_text
    assert "repair worker is still active" in scheduler_text


def test_stale_reclaim_exceeds_worker_timeout(lane_text, scheduler_text):
    assert "timeout-minutes: 70" in lane_text
    assert "4800" in scheduler_text
    assert 4800 > 70 * 60


def test_durable_pr_lineage_is_reconciled_before_dispatch(scheduler_text):
    reconcile_pos = scheduler_text.index("name: Reconcile queue labels against durable PR lineage")
    dispatch_pos = scheduler_text.index(DISPATCH_STEP)
    assert reconcile_pos < dispatch_pos
    assert "duplicate worker dispatch suppressed" in scheduler_text


def test_pipefail_paths_do_not_use_early_exit_head(scheduler_text, lane_text):
    assert "| head -1" not in scheduler_text
    assert "| head -1" not in lane_text


def test_validation_dispatch_outage_does_not_requeue_claude(lane_text):
    marker = "Durable PR #$pr exists, but validation dispatch failed"
    start = lane_text.index(marker)
    branch_start = lane_text.rindex("else", 0, start)
    branch_end = lane_text.index("exit 1", start)
    window = lane_text[branch_start:branch_end]
    assert "--add-label oc-validating" in window
    assert "--add-label oc-queued" not in window
    assert "without redispatching Claude" in window


def test_completed_red_validation_authorizes_exactly_one_repair_state(scheduler_text):
    red = 'if [[ "$result" != "completed success" ]]; then'
    start = scheduler_text.index(red)
    window = scheduler_text[start : start + 500]
    assert "--add-label oc-queued --add-label oc-repair" in window


def test_durable_pr_suppression_exempts_only_explicit_repair(scheduler_text):
    reconcile_start = scheduler_text.index("name: Reconcile queue labels against durable PR lineage")
    dispatch_start = scheduler_text.index(DISPATCH_STEP)
    reconcile = scheduler_text[reconcile_start:dispatch_start]
    dispatch = scheduler_text[dispatch_start:]
    assert '[[ "$labels" == *oc-repair* ]] && continue' in reconcile
    # Durable-PR suppression now lives in the deterministic planner; the workflow
    # only applies the plan's suppression decisions.
    assert 'select(.reason == "durable-pr")' in dispatch
    assert "--remove-label oc-queued --add-label oc-validating" in dispatch


def test_orphaned_repair_authorization_self_heals_into_queue_before_selection(scheduler_text):
    normalize_start = scheduler_text.index(NORMALIZE_STEP)
    dispatch_start = scheduler_text.index(DISPATCH_STEP)
    normalize = scheduler_text[normalize_start:dispatch_start]
    assert normalize_start < dispatch_start
    assert 'index("oc-repair")' in normalize
    assert 'index("oc-running")) | not' in normalize
    assert 'index("oc-queued")) | not' in normalize
    assert "--remove-label oc-validating --add-label oc-queued" in normalize
    assert "must never be a" in normalize and "terminal state by itself" in normalize


def test_scheduler_no_longer_carries_a_hard_coded_legacy_backlog(scheduler_text):
    assert "BACKLOG=(" not in scheduler_text
    for legacy in (1030, 1029, 1025, 1026, 1027, 1008, 1021, 1022, 1023, 1024):
        assert f"{legacy} " not in scheduler_text
    assert "oc-queued" in scheduler_text


def test_selection_is_delegated_to_the_deterministic_priority_planner(scheduler_text):
    dispatch = scheduler_text[scheduler_text.index(DISPATCH_STEP) :]
    assert "python3 scripts/oc_portfolio_scheduler.py" in dispatch
    assert "--mode plan" in dispatch
    assert 'MAX_ACTIVE_LANES: "5"' in dispatch
    assert "jq -r '.selected[].number'" in dispatch


def test_durable_priority_labels_are_provisioned_and_backfilled(scheduler_text):
    for level in range(6):
        assert f"ensure_label oc-p{level} " in scheduler_text
    normalize = scheduler_text[scheduler_text.index(NORMALIZE_STEP) : scheduler_text.index(DISPATCH_STEP)]
    assert "--mode priority-labels" in normalize
    assert "an explicit label always wins" in normalize


def test_capacity_is_derived_from_active_leases_not_blind_redispatch(scheduler_text):
    dispatch = scheduler_text[scheduler_text.index(DISPATCH_STEP) :]
    assert "oc-running execution leases" in dispatch
    assert "never consume a lane" in dispatch


def test_abandoned_lane_reclamation_is_preserved(scheduler_text):
    reclaim = scheduler_text[scheduler_text.index("name: Reclaim abandoned lanes") :]
    assert "if (( now - epoch <= 4800 )); then" in reclaim
    assert "Lane reclaimed and returned to queue" in reclaim
    assert "Reclaimed the lane into validation rather than redispatching Claude" in reclaim


def test_scheduled_runs_still_execute_the_main_control_plane(scheduler, scheduler_text):
    assert scheduler[True]["schedule"] == [{"cron": "*/5 * * * *"}]
    assert "ref: ${{ github.sha }}" in scheduler_text


def test_repair_authorization_is_consumed_before_revalidation(lane_text):
    classification = lane_text[lane_text.index("name: Classify result") :]
    assert "--remove-label oc-repair" in classification
    assert "repair authorization is single-use" in classification


def test_main_and_production_remain_owner_gated(scheduler_text, lane_text):
    assert "Maintain integration-to-main owner gate" in scheduler_text
    assert "OC-AUTO-INTEGRATION-GATE" in scheduler_text
    assert "Never merge to `main`, deploy production" in lane_text
