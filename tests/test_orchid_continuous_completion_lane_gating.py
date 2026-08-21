"""Structural regression contract for the live continuous-completion control plane."""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

SCHEDULER = Path(".github/workflows/orchid-continuous-completion.yml")
LANE = Path(".github/workflows/orchid-completion-lane.yml")
CANARY = Path(".github/workflows/orchid-claude-runtime-canary.yml")


@pytest.fixture(scope="module")
def scheduler_text() -> str:
    return SCHEDULER.read_text()


@pytest.fixture(scope="module")
def lane_text() -> str:
    return LANE.read_text()


@pytest.fixture(scope="module")
def canary_text() -> str:
    return CANARY.read_text()


@pytest.fixture(scope="module")
def scheduler() -> dict:
    return yaml.safe_load(SCHEDULER.read_text())


@pytest.fixture(scope="module")
def lane() -> dict:
    return yaml.safe_load(LANE.read_text())


def test_workflows_are_valid_yaml(scheduler, lane):
    assert isinstance(scheduler, dict)
    assert isinstance(lane, dict)
    assert isinstance(yaml.safe_load(CANARY.read_text()), dict)


def test_scheduler_never_runs_claude_inline(scheduler_text):
    assert "anthropics/claude-code-action" not in scheduler_text
    assert "gh workflow run orchid-completion-lane.yml" in scheduler_text


def test_scheduler_uses_canonical_priority_aware_portfolio(scheduler_text):
    assert "name: Dispatch priority-aware portfolio workers" in scheduler_text
    assert "BACKLOG=(" not in scheduler_text
    assert "--label oc-queued" in scheduler_text
    assert "oc-p0" in scheduler_text and "oc-p5" in scheduler_text
    assert "for p in 0 1 2 3 4 5; do" in scheduler_text
    assert "sort -t'|' -k1,1n -k2,2 -k3,3n" in scheduler_text


def test_scheduler_caps_active_execution_width_at_five(scheduler_text):
    assert "MAX_ACTIVE_LANES: 5" in scheduler_text
    assert "capacity=$(( MAX_ACTIVE_LANES - running_count ))" in scheduler_text
    assert "All ${MAX_ACTIVE_LANES} implementation lanes are occupied." in scheduler_text


def test_scheduler_has_bounded_starvation_protection(scheduler_text):
    assert "age >= 259200" in scheduler_text
    assert "effective=$(( effective - 1 ))" in scheduler_text


def test_completion_lane_is_serialized_per_issue(lane_text):
    assert "group: orchid-completion-lane-${{ github.repository }}-${{ inputs.issue_number }}" in lane_text
    assert "cancel-in-progress: false" in lane_text


def test_stale_duplicate_dispatch_is_suppressed_before_claude(lane_text):
    assert "name: Verify scheduler lease" in lane_text
    assert '[[ "$labels" == *oc-running* ]]' in lane_text
    assert "if: steps.lease.outputs.execute == 'true'" in lane_text
    assert lane_text.index("name: Verify scheduler lease") < lane_text.index("uses: anthropics/claude-code-action@v1")


def test_stale_reclaim_exceeds_worker_timeout(lane_text, scheduler_text):
    assert "timeout-minutes: 70" in lane_text
    assert "4800" in scheduler_text
    assert 4800 > 70 * 60


def test_durable_pr_lineage_is_reconciled_before_dispatch(scheduler_text):
    reconcile_pos = scheduler_text.index("name: Reconcile queue labels against durable PR lineage")
    dispatch_pos = scheduler_text.index("name: Dispatch priority-aware portfolio workers")
    assert reconcile_pos < dispatch_pos
    assert "duplicate worker dispatch suppressed" in scheduler_text


def test_pipefail_paths_do_not_use_early_exit_head(scheduler_text, lane_text):
    assert "| head -1" not in scheduler_text
    assert "| head -1" not in lane_text


def test_validation_dispatch_outage_does_not_requeue_claude(lane_text):
    marker = "Durable PR #$pr exists, but validation dispatch failed"
    start = lane_text.index(marker)
    window = lane_text[max(0, start - 1000) : start + 1000]
    assert "--add-label oc-validating" in window
    assert "--add-label oc-queued" not in window
    assert "without redispatching Claude" in window


def test_red_validation_authorizes_bounded_repair(scheduler_text):
    red = 'if [[ "$result" != "completed success" ]]; then'
    start = scheduler_text.index(red)
    assert "--add-label oc-queued --add-label oc-repair" in scheduler_text[start : start + 500]


def test_durable_pr_suppression_exempts_explicit_repair(scheduler_text):
    reconcile_start = scheduler_text.index("name: Reconcile queue labels against durable PR lineage")
    dispatch_start = scheduler_text.index("name: Dispatch priority-aware portfolio workers")
    reconcile = scheduler_text[reconcile_start:dispatch_start]
    dispatch = scheduler_text[dispatch_start:]
    assert '[[ "$labels" == *oc-repair* ]] && continue' in reconcile
    assert 'if [[ -n "$durable" && "$repair" != true ]]; then' in dispatch


def test_orphaned_repair_self_heal_respects_runtime_backoff(scheduler_text):
    heal_start = scheduler_text.index("name: Heal portfolio queue invariants")
    runtime_start = scheduler_text.index("name: Manage Claude runtime circuit")
    heal = scheduler_text[heal_start:runtime_start]
    assert '[[ "$labels" == *oc-repair*' in heal
    assert '"$labels" != *oc-runtime-backoff*' in heal
    assert "--remove-label oc-validating --add-label oc-queued" in heal


def test_runtime_failure_opens_global_circuit_and_parks_issue(lane_text):
    assert 'CLAUDE_OUTCOME: ${{ steps.claude.outcome }}' in lane_text
    assert 'elif [[ "$CLAUDE_OUTCOME" != "success" ]]; then' in lane_text
    assert "--add-label oc-runtime-backoff" in lane_text
    assert "--add-label oc-runtime-degraded" in lane_text
    assert "repository runtime circuit opened" in lane_text


def test_runtime_circuit_pauses_dispatch_and_probes_slowly(scheduler_text):
    assert "name: Manage Claude runtime circuit" in scheduler_text
    assert "oc-runtime-degraded" in scheduler_text
    assert 'echo "paused=true" >> "$GITHUB_OUTPUT"' in scheduler_text
    assert "age >= 1800" in scheduler_text
    assert "gh workflow run orchid-claude-runtime-canary.yml" in scheduler_text
    assert "if: steps.runtime.outputs.paused != 'true'" in scheduler_text


def test_passing_canary_closes_circuit_and_scheduler_recovers_parked_work(canary_text, scheduler_text):
    assert "workflow_dispatch:" in canary_text
    assert "--remove-label oc-runtime-degraded" in canary_text
    assert "--add-label oc-runtime-degraded" in canary_text
    assert "--label oc-runtime-backoff" in scheduler_text
    assert "--remove-label oc-runtime-backoff --add-label oc-queued" in scheduler_text


def test_runtime_backoff_is_excluded_from_selection(scheduler_text):
    dispatch = scheduler_text[scheduler_text.index("name: Dispatch priority-aware portfolio workers") :]
    assert '[[ "$labels" == *oc-runtime-backoff* ]] && continue' in dispatch


def test_state_is_reread_immediately_before_dispatch(scheduler_text):
    dispatch = scheduler_text[scheduler_text.index("name: Dispatch priority-aware portfolio workers") :]
    assert '[[ "$labels" == *oc-queued* ]] || continue' in dispatch
    assert '[[ "$labels" == *oc-running* ]] && continue' in dispatch
    assert '[[ "$labels" == *oc-validating* ]] && continue' in dispatch
    assert '[[ "$labels" == *oc-blocked* ]] && continue' in dispatch
    assert '[[ "$labels" == *oc-owner-gate* ]] && continue' in dispatch
    assert '[[ "$labels" == *oc-done* ]] && continue' in dispatch


def test_main_and_production_remain_owner_gated(scheduler_text, lane_text):
    assert "Maintain integration-to-main owner gate" in scheduler_text
    assert "OC-AUTO-INTEGRATION-GATE" in scheduler_text
    assert "Never merge to `main`, deploy production" in lane_text
