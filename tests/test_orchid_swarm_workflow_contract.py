from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "orchid-swarm-controller.yml"


def test_swarm_workflow_uses_bounded_parallel_matrix():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "max-parallel: 12" in text
    assert 'default: "8"' in text
    assert "oc_swarm_controller.py" in text
    assert "orchid-completion-lane.yml" in text


def test_swarm_workflow_targets_integration_not_main():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "INTEGRATION_BRANCH: oc-autonomous-integration" in text
    # Trusted controls are pinned to the controller event revision. The canonical
    # dispatch runs on oc-autonomous-integration, so that revision is the
    # integration head; a mixed checkout of a mutable branch is never used.
    assert "ref: ${{ github.sha }}" in text
    assert "ref: main" not in text
    assert "gh pr merge" not in text
    assert "production deploy: disabled" in text.lower()


def test_swarm_claims_only_queue_leases_and_reports_resources():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "python3 -m scripts.oc_swarm_claim" in text
    claim = (ROOT / "scripts" / "oc_swarm_claim.py").read_text(encoding="utf-8")
    for label in (
        "oc-queued",
        "oc-running",
        "oc-owner-gate",
        "oc-blocked",
        "oc-runtime-backoff",
        "oc-repair-backoff",
    ):
        assert label in claim
    assert "Dependency/resource lease claimed" in claim
    assert "resource conflicts suppressed" in text


def test_swarm_summary_parses_plan_as_json_not_a_quoted_json_string():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert '<<<"$PLAN"' in text
    assert '<<<\\"$PLAN\\"' not in text


def test_no_api_mode_dispatches_only_provider_free_workers():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "--provider-free-only" in text
    assert "provider_free_workers:" in text
    assert "oc_swarm_provider_free_worker.py" in text
    # The paid lane is gated on providers being enabled AND a provider-dependent
    # claim existing; provider-free claims never reach it.
    assert (
        "needs.plan.outputs.provider_launch_count != '0' && needs.plan.outputs.provider_blocked == 'false'"
        in text
    )
    assert "needs.plan.outputs.provider_blocked == 'true'" in text
    # The provider-free worker verifies the actual write set against the lease:
    # empty outside edit mode, the edit lane's changed files inside it.
    assert "files_json='[]'" in text
    assert '--files-json "$files_json"' in text


def test_coding_executor_requires_governor_admission_before_planning_and_claims():
    text = WORKFLOW.read_text(encoding="utf-8")
    governor_start = text.index("      - name: Check governor admission before selecting coding work")
    plan_start = text.index("      - name: Plan dependency-aware resource wave")
    claim_start = text.index("      - name: Claim selected worker leases")
    assert governor_start < plan_start < claim_start
    governor = text[governor_start:plan_start]
    assert "id: coding_governor" in governor
    assert "steps.budget_ledger.outcome == 'success'" in governor
    assert "python3 scripts/swarm_governor_precheck.py" in governor
    assert "DEFAULT_ESTIMATED_COST_USD" in governor
    assert "print(max(costs))" in governor
    assert 'OC_GOVERNOR_RETRY_COUNT: "1"' in governor
    for key in (
        "NO_API_MODE", "OC_GOVERNOR_PAID_EXECUTION_ENABLED",
        "OC_GOVERNOR_EMERGENCY_KILL_SWITCH", "OC_GOVERNOR_PROVIDER_ALLOWLIST",
        "OC_GOVERNOR_PER_RUN_BUDGET_USD", "OC_GOVERNOR_DAILY_BUDGET_USD",
        "OC_GOVERNOR_MONTHLY_BUDGET_USD", "OC_GOVERNOR_MAX_RETRIES",
    ):
        assert f"{key}: ${{{{ vars.{key} }}}}" in governor
    assert 'OC_GOVERNOR_DAILY_SPEND_USD:?missing daily spend observation' in governor
    assert 'OC_GOVERNOR_MONTHLY_SPEND_USD:?missing monthly spend observation' in governor
    plan = text[plan_start:claim_start]
    guard = (
        'if [[ "${{ steps.no_api.outputs.blocked }}" == "false" && '
        '"${{ steps.coding_governor.outputs.authorized }}" == "true" ]]; then'
    )
    assert guard in plan
    assert plan.index(guard) < plan.index("provider_args+=(--coding-executor)")
    assert "else\n            provider_args+=(--provider-free-only)" in plan
    assert (
        "provider_blocked: ${{ steps.no_api.outputs.blocked == 'true' || "
        "steps.coding_governor.outputs.authorized != 'true' }}"
    ) in text


def test_every_launched_wave_gets_one_bounded_refill_attempt():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "needs.plan.outputs.launch_count != '0'" in text
    assert "current >= maximum" in text
    # The refill wave targets the revision that launched the wave and falls
    # back to the canonical integration branch for event-driven runs.
    assert '--ref "$refill_ref"' in text
    assert 'refill_ref="$INTEGRATION_BRANCH"' in text


def _plan_job_steps():
    text = WORKFLOW.read_text(encoding="utf-8")
    return text.split("  plan:", 1)[1].split("\n  provider_free_workers:", 1)[0]


def test_coding_executor_is_admitted_only_on_the_governors_verdict():
    steps = _plan_job_steps()
    governor_start = steps.index("        id: coding_governor")
    plan_start = steps.index("      - name: Plan dependency-aware resource wave")
    governor = steps[governor_start:plan_start]
    plan = steps[plan_start:]
    # The governor verdict is computed before planning, can only deny on error,
    # and sees the same paid-execution policy inputs the completion lane checks.
    assert governor_start < plan_start
    assert "python3 scripts/swarm_governor_precheck.py" in governor
    assert "continue-on-error: true" in governor
    assert "steps.no_api.outputs.blocked == 'false'" in governor
    assert "steps.budget_ledger.outcome == 'success'" in governor
    for name in (
        "NO_API_MODE",
        "OC_GOVERNOR_EMERGENCY_KILL_SWITCH",
        "OC_GOVERNOR_PAID_EXECUTION_ENABLED",
        "OC_GOVERNOR_PROVIDER_ALLOWLIST",
        "OC_GOVERNOR_PER_RUN_BUDGET_USD",
        "OC_GOVERNOR_DAILY_BUDGET_USD",
        "OC_GOVERNOR_MONTHLY_BUDGET_USD",
    ):
        assert name + ":" in governor, name
    script = plan
    # NO_API_MODE=false alone must not pass the flag: it is guarded by the verdict.
    assert '"${{ steps.coding_governor.outputs.authorized }}" == "true"' in script
    assert script.count("--coding-executor") == 1
    assert script.index("--coding-executor") > script.index("steps.coding_governor.outputs.authorized")
    # No branch passes the flag unconditionally.
    assert "else\n            # Providers are authorised" not in script


def test_governor_denies_when_paid_execution_is_not_enabled(tmp_path):
    """The verdict the workflow consumes: NO_API_MODE=false is not authorization."""
    import os
    import subprocess
    import sys

    output = tmp_path / "out"
    env = {
        "PATH": os.environ["PATH"],
        "NO_API_MODE": "false",
        "OC_GOVERNOR_PAID_EXECUTION_ENABLED": "false",
        "OC_GOVERNOR_PROVIDER": "anthropic",
        "OC_GOVERNOR_PROVIDER_ALLOWLIST": "anthropic",
        "OC_GOVERNOR_PER_RUN_ESTIMATED_COST_USD": "2.00",
        "OC_GOVERNOR_PER_RUN_BUDGET_USD": "5",
        "OC_GOVERNOR_DAILY_BUDGET_USD": "20",
        "OC_GOVERNOR_MONTHLY_BUDGET_USD": "100",
        "GITHUB_OUTPUT": str(output),
    }
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "swarm_governor_precheck.py")],
        env=env, check=True, capture_output=True, cwd=ROOT,
    )
    text = output.read_text(encoding="utf-8")
    assert "authorized=false" in text
    assert "reason=BLOCKED_PAID_EXECUTION_DISABLED" in text
