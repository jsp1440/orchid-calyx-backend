"""Structural regression contract for the live continuous-completion control plane."""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

SCHEDULER = Path(".github/workflows/orchid-continuous-completion.yml")
LANE = Path(".github/workflows/orchid-completion-lane.yml")
PLANNER = Path("scripts/oc_portfolio_scheduler.py")
HEAL_STEP = "name: Heal portfolio queue invariants"
DISPATCH_STEP = "name: Dispatch priority-aware portfolio workers"
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
    assert "oc-p0" in scheduler_text and "oc-p5" in scheduler_text
    # Ranking moved from inline bash into a deterministic planner whose policy is
    # proven behaviourally in tests/test_oc_portfolio_scheduler.py.
    dispatch = scheduler_text[scheduler_text.index(DISPATCH_STEP) :]
    assert 'python3 "$PLANNER"' in dispatch
    assert "--mode plan" in dispatch
    assert "jq -r '.selected[].number'" in dispatch
    assert "PLANNER: scripts/oc_portfolio_scheduler.py" in scheduler_text
    assert PLANNER.exists()


def test_planner_is_the_single_source_of_selection_policy(scheduler_text):
    dispatch = scheduler_text[scheduler_text.index(DISPATCH_STEP) :]
    # No second, divergent ranking implementation may live in the workflow.
    assert "priority_of ()" not in dispatch
    assert "sort -t'|'" not in dispatch


def test_planner_excludes_runtime_backed_off_work_from_ranking(scheduler_text):
    # Runtime and bounded-repair backoff are both non-executable states. Inspect
    # the tuple body rather than punctuation/order so fail-closed additions do
    # not make this regression test stale.
    source = PLANNER.read_text()
    assert 'RUNTIME_BACKOFF = "oc-runtime-backoff"' in source
    assert 'REPAIR_BACKOFF = "oc-repair-backoff"' in source
    tuple_start = source.index("NON_EXECUTABLE_LABELS = (")
    tuple_end = source.index(")", tuple_start)
    tuple_source = source[tuple_start:tuple_end]
    assert "RUNTIME_BACKOFF" in tuple_source
    assert "REPAIR_BACKOFF" in tuple_source
    assert "blocking = [label for label in NON_EXECUTABLE_LABELS if label in labels]" in source
    assert "if blocking:" in source
    assert '[[ "$labels" == *oc-runtime-backoff* ]] && continue' in scheduler_text


def test_scheduler_publishes_a_read_only_status_surface(scheduler_text):
    dispatch = scheduler_text[scheduler_text.index(DISPATCH_STEP) :]
    for field in ("active_lane_count", "available_capacity", "eligible_count",
                  ".ranking[]", ".selected[]", ".suppressed[]", "priority_source",
                  "waited_hours", "selection_reason"):
        assert field in dispatch
    assert "$GITHUB_STEP_SUMMARY" in dispatch


def test_a_missing_planner_fails_closed_instead_of_dispatching_blind(scheduler_text):
    dispatch = scheduler_text[scheduler_text.index(DISPATCH_STEP) :]
    guard = dispatch.index('if [[ ! -f "$PLANNER" ]]; then')
    assert guard < dispatch.index("gh workflow run orchid-completion-lane.yml")
    assert "no worker dispatched this cycle" in dispatch
    heal = scheduler_text[scheduler_text.index(HEAL_STEP) : scheduler_text.index("name: Manage Claude runtime circuit")]
    assert 'if [[ -f "$PLANNER" ]]; then' in heal
    assert "leaving priority labels untouched" in heal


def test_durable_priority_labels_are_provisioned_and_backfilled(scheduler_text):
    for level in range(6):
        assert f"ensure_label oc-p{level} " in scheduler_text
    heal = scheduler_text[scheduler_text.index(HEAL_STEP) : scheduler_text.index("name: Manage Claude runtime circuit")]
    assert "--mode priority-labels" in heal
    assert "an explicit label is authoritative" in heal


def test_completed_work_cannot_carry_a_queue_lease_or_repair_authorization(scheduler_text):
    heal = scheduler_text[scheduler_text.index(HEAL_STEP) : scheduler_text.index("name: Manage Claude runtime circuit")]
    assert "--label oc-done --label oc-queued" in heal
    assert "--remove-label oc-queued --remove-label oc-repair" in heal


def test_queue_healing_does_not_spend_a_request_per_issue(scheduler_text):
    # This runs every five minutes against a repository with hundreds of open
    # issues; per-issue lookups made the heal step outlast its own schedule.
    heal = scheduler_text[scheduler_text.index(HEAL_STEP) : scheduler_text.index("name: Manage Claude runtime circuit")]
    assert "gh issue view" not in heal
    assert "--json number,labels" in heal


def test_integration_base_maintenance_restores_the_control_plane_checkout(scheduler_text):
    # Maintaining the integration base switches branches; without restoring the
    # checkout every later step reads that branch's tree instead of the
    # control-plane code this workflow file belongs to.
    step = scheduler_text[
        scheduler_text.index("name: Ensure orchestration labels and current integration base")
        : scheduler_text.index("name: Reclaim abandoned lanes")
    ]
    assert "control_plane=$(git rev-parse HEAD)" in step
    assert 'git checkout --force --detach "$control_plane"' in step
    assert step.index("control_plane=$(git rev-parse HEAD)") < step.index('git checkout -B "$INTEGRATION_BRANCH"')
    assert step.rindex('git checkout --force --detach "$control_plane"') > step.rindex("git merge --abort")


def test_checkout_matches_the_ref_the_workflow_file_came_from(scheduler_text):
    assert (
        "ref: ${{ (github.event_name == 'workflow_dispatch' || "
        "github.event_name == 'pull_request') && github.sha || 'main' }}"
    ) in scheduler_text


def test_owner_only_gate_permission_warns_instead_of_reddening_the_control_plane(scheduler_text):
    gate = scheduler_text[scheduler_text.index("name: Maintain integration-to-main owner gate") :]
    assert "if ! gh pr create" in gate
    assert "::warning::Could not open the integration->main gate PR" in gate
    assert "main remains owner-gated either way" in gate


def test_recovery_scheduler_caps_active_execution_width_at_one(scheduler_text):
    assert "MAX_ACTIVE_LANES: 1" in scheduler_text
    assert "STABILIZATION_ISSUE: 1193" in scheduler_text
    assert "capacity=$(( MAX_ACTIVE_LANES - running_count ))" in scheduler_text
    assert "All ${MAX_ACTIVE_LANES} implementation lanes are occupied." in scheduler_text


def test_scheduler_has_bounded_starvation_protection():
    # A single one-band promotion can still be outrun by a continuous P0/P1
    # stream, so fairness now reserves a lane outright. Bounded to one lane per
    # cycle, and never ahead of fresh higher-priority work for the other lanes.
    source = PLANNER.read_text()
    assert "FAIRNESS_RESERVED_LANES = 1" in source
    assert "FAIRNESS_WAIT_HOURS" in source
    assert "REPAIR_RESERVED_LANES = 1" in source


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
    # Labels are the authoritative behavior: validation stays durable and the
    # implementation worker is not made dispatchable again.
    assert "--add-label oc-validating" in window
    assert "--add-label oc-queued" not in window


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
    # Labels and the failure branch are the contract; operator-facing prose may
    # change without changing the fail-closed circuit behavior.
    assert 'CLAUDE_OUTCOME: ${{ steps.claude.outcome }}' in lane_text
    assert 'elif [[ "$CLAUDE_OUTCOME" != "success" ]]; then' in lane_text
    assert "--add-label oc-runtime-backoff" in lane_text
    assert "--add-label oc-runtime-degraded" in lane_text


def test_runtime_circuit_pauses_dispatch_and_probes_slowly(scheduler_text):
    runtime_start = scheduler_text.index("name: Manage Claude runtime circuit")
    dispatch_start = scheduler_text.index("name: Dispatch priority-aware portfolio workers")
    runtime = scheduler_text[runtime_start:dispatch_start]
    # Preferred-provider degradation alone must not halt the portfolio. The
    # scheduler pauses only when every authorized provider is blocked, and its
    # slow recovery probe uses the governed provider-chain canary.
    assert "oc-provider-chain-blocked" in runtime
    assert 'if [[ "$tracker_labels" == *oc-provider-chain-blocked* ]]; then' in runtime
    assert 'echo "paused=true" >> "$GITHUB_OUTPUT"' in runtime
    assert "age >= 1800" in runtime
    assert "gh workflow run orchid-gemini-runtime-canary.yml" in runtime
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
