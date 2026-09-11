"""Static enforcement tests for Swarm Execution Governor workflow integration.

Parses the five named provider workflows and asserts that each one:
  1. Has the global paid-execution concurrency group.
  2. Has a NO-API mode guard step before any provider steps.
  3. Has a governor precheck step before any provider steps.
  4. Provider steps are conditional on the governor output.

These tests are deliberately static (parse YAML, no I/O) so they run fast
and do not require GitHub Actions secrets or network access.
"""

from __future__ import annotations

import importlib
import os
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"

# The five named provider workflows
PROVIDER_WORKFLOWS = [
    "claude-code-governed.yml",
    "orchid-claude-runtime-canary.yml",
    "orchid-openai-runtime-canary.yml",
    "orchid-gemini-runtime-canary.yml",
    "orchid-completion-lane.yml",
]

GLOBAL_CONCURRENCY_GROUP = "swarm-paid-execution-"
NO_API_GUARD_SCRIPT = "oc_no_api_guard.py"
GOVERNOR_PRECHECK_SCRIPT = "swarm_governor_precheck.py"

# Workflows that have governor precheck step
# (canary/recovery workflows + all new guarded ones)
WORKFLOWS_WITH_GOVERNOR_PRECHECK = set(PROVIDER_WORKFLOWS)

# All five workflows must have the global concurrency group and NO-API guard
WORKFLOWS_REQUIRING_NO_API_GUARD = set(PROVIDER_WORKFLOWS)
WORKFLOWS_REQUIRING_CONCURRENCY = set(PROVIDER_WORKFLOWS)


def load_workflow(name: str) -> dict:
    path = WORKFLOWS_DIR / name
    assert path.exists(), f"Workflow file not found: {path}"
    with open(path) as f:
        return yaml.safe_load(f)


def all_steps(workflow: dict) -> list[dict]:
    """Flatten all steps from all jobs."""
    steps = []
    for job in workflow.get("jobs", {}).values():
        steps.extend(job.get("steps", []))
    return steps


def step_runs_script(step: dict, script_name: str) -> bool:
    run = step.get("run", "") or ""
    uses = step.get("uses", "") or ""
    return script_name in run or script_name in uses


def get_concurrency(workflow: dict) -> dict | None:
    return workflow.get("concurrency")


# ─── concurrency group ───────────────────────────────────────────────────────


@pytest.mark.parametrize("workflow_name", PROVIDER_WORKFLOWS)
def test_global_concurrency_group_present(workflow_name: str) -> None:
    wf = load_workflow(workflow_name)
    concurrency = get_concurrency(wf)
    assert concurrency is not None, (
        f"{workflow_name}: missing top-level 'concurrency:' block; "
        "all provider workflows must serialise via swarm-paid-execution group"
    )
    group = concurrency.get("group", "")
    assert GLOBAL_CONCURRENCY_GROUP in group, (
        f"{workflow_name}: concurrency group {group!r} does not contain "
        f"{GLOBAL_CONCURRENCY_GROUP!r}"
    )


@pytest.mark.parametrize("workflow_name", PROVIDER_WORKFLOWS)
def test_concurrency_cancel_in_progress_false(workflow_name: str) -> None:
    wf = load_workflow(workflow_name)
    concurrency = get_concurrency(wf)
    assert concurrency is not None
    assert concurrency.get("cancel-in-progress") is False, (
        f"{workflow_name}: cancel-in-progress must be false to queue rather than cancel "
        "in-flight executions"
    )


# ─── NO-API mode guard ────────────────────────────────────────────────────────


@pytest.mark.parametrize("workflow_name", WORKFLOWS_REQUIRING_NO_API_GUARD)
def test_no_api_guard_step_present(workflow_name: str) -> None:
    wf = load_workflow(workflow_name)
    steps = all_steps(wf)
    has_guard = any(step_runs_script(s, NO_API_GUARD_SCRIPT) for s in steps)
    assert has_guard, (
        f"{workflow_name}: no step runs {NO_API_GUARD_SCRIPT!r}; "
        "all provider workflows must include the NO-API mode guard"
    )


@pytest.mark.parametrize("workflow_name", WORKFLOWS_REQUIRING_NO_API_GUARD)
def test_no_api_guard_has_no_api_mode_env(workflow_name: str) -> None:
    wf = load_workflow(workflow_name)
    steps = all_steps(wf)
    guard_steps = [s for s in steps if step_runs_script(s, NO_API_GUARD_SCRIPT)]
    assert guard_steps, f"{workflow_name}: no NO-API guard step found"
    for gs in guard_steps:
        env = gs.get("env", {}) or {}
        job_env = {}
        for job in wf.get("jobs", {}).values():
            job_env.update(job.get("env", {}) or {})
        combined = {**job_env, **env}
        assert "NO_API_MODE" in combined, (
            f"{workflow_name}: NO-API guard step does not have NO_API_MODE in env; "
            "the variable must be explicitly sourced from vars.NO_API_MODE"
        )


# ─── governor precheck ────────────────────────────────────────────────────────


@pytest.mark.parametrize("workflow_name", WORKFLOWS_WITH_GOVERNOR_PRECHECK)
def test_governor_precheck_step_present(workflow_name: str) -> None:
    wf = load_workflow(workflow_name)
    steps = all_steps(wf)
    has_precheck = any(step_runs_script(s, GOVERNOR_PRECHECK_SCRIPT) for s in steps)
    assert has_precheck, (
        f"{workflow_name}: no step runs {GOVERNOR_PRECHECK_SCRIPT!r}; "
        "paid provider workflows must include the governor precheck"
    )


@pytest.mark.parametrize("workflow_name", WORKFLOWS_WITH_GOVERNOR_PRECHECK)
def test_governor_precheck_step_has_no_api_mode_env(workflow_name: str) -> None:
    wf = load_workflow(workflow_name)
    steps = all_steps(wf)
    precheck_steps = [s for s in steps if step_runs_script(s, GOVERNOR_PRECHECK_SCRIPT)]
    assert precheck_steps, f"{workflow_name}: no governor precheck step found"
    for ps in precheck_steps:
        env = ps.get("env", {}) or {}
        job_env = {}
        for job in wf.get("jobs", {}).values():
            job_env.update(job.get("env", {}) or {})
        combined = {**job_env, **env}
        assert "NO_API_MODE" in combined, (
            f"{workflow_name}: governor precheck step does not expose NO_API_MODE; "
            "the precheck must be able to evaluate the NO_API_MODE guard"
        )


@pytest.mark.parametrize("workflow_name", WORKFLOWS_WITH_GOVERNOR_PRECHECK)
def test_governor_precheck_step_has_kill_switch_env(workflow_name: str) -> None:
    wf = load_workflow(workflow_name)
    steps = all_steps(wf)
    precheck_steps = [s for s in steps if step_runs_script(s, GOVERNOR_PRECHECK_SCRIPT)]
    assert precheck_steps, f"{workflow_name}: no governor precheck step found"
    for ps in precheck_steps:
        env = ps.get("env", {}) or {}
        assert "OC_GOVERNOR_EMERGENCY_KILL_SWITCH" in env, (
            f"{workflow_name}: governor precheck step missing OC_GOVERNOR_EMERGENCY_KILL_SWITCH; "
            "the kill switch must be evaluated at the precheck layer"
        )


# ─── step ordering: guard before provider ────────────────────────────────────


def _step_index(steps: list[dict], script_name: str) -> int | None:
    for i, s in enumerate(steps):
        if step_runs_script(s, script_name):
            return i
    return None


def _provider_step_indices(steps: list[dict], workflow_name: str) -> list[int]:
    """Return indices of steps that invoke paid provider APIs."""
    provider_keywords = [
        "anthropic_api_key",
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "gemini-cli",
        "codex@latest",
        "claude-code-action",
    ]
    indices = []
    for i, step in enumerate(steps):
        run = step.get("run", "") or ""
        with_block = str(step.get("with", "") or "")
        uses = step.get("uses", "") or ""
        text = f"{run} {with_block} {uses}"
        # Skip the precheck and guard steps themselves
        if step_runs_script(step, NO_API_GUARD_SCRIPT):
            continue
        if step_runs_script(step, GOVERNOR_PRECHECK_SCRIPT):
            continue
        if any(kw in text for kw in provider_keywords):
            indices.append(i)
    return indices


@pytest.mark.parametrize("workflow_name", WORKFLOWS_WITH_GOVERNOR_PRECHECK)
def test_governor_precheck_before_provider_steps(workflow_name: str) -> None:
    wf = load_workflow(workflow_name)
    steps = all_steps(wf)

    precheck_idx = _step_index(steps, GOVERNOR_PRECHECK_SCRIPT)
    assert precheck_idx is not None, f"{workflow_name}: no governor precheck step"

    provider_indices = _provider_step_indices(steps, workflow_name)
    for pi in provider_indices:
        assert pi > precheck_idx, (
            f"{workflow_name}: provider step at index {pi} comes BEFORE governor "
            f"precheck at index {precheck_idx}; the precheck must run first"
        )


@pytest.mark.parametrize("workflow_name", WORKFLOWS_REQUIRING_NO_API_GUARD)
def test_no_api_guard_before_provider_steps(workflow_name: str) -> None:
    wf = load_workflow(workflow_name)
    steps = all_steps(wf)

    guard_idx = _step_index(steps, NO_API_GUARD_SCRIPT)
    assert guard_idx is not None, f"{workflow_name}: no NO-API guard step"

    provider_indices = _provider_step_indices(steps, workflow_name)
    for pi in provider_indices:
        assert pi > guard_idx, (
            f"{workflow_name}: provider step at index {pi} comes BEFORE NO-API guard "
            f"at index {guard_idx}; the guard must run first"
        )


# ─── governor precheck script sanity ─────────────────────────────────────────


def test_governor_precheck_script_exists() -> None:
    path = REPO_ROOT / "scripts" / "swarm_governor_precheck.py"
    assert path.exists(), "scripts/swarm_governor_precheck.py does not exist"


def test_governor_postrun_script_exists() -> None:
    path = REPO_ROOT / "scripts" / "swarm_governor_postrun.py"
    assert path.exists(), "scripts/swarm_governor_postrun.py does not exist"


def test_governor_precheck_imports_no_api_guard() -> None:
    path = REPO_ROOT / "scripts" / "swarm_governor_precheck.py"
    content = path.read_text()
    assert "oc_no_api_guard" in content, (
        "swarm_governor_precheck.py must import oc_no_api_guard to delegate the "
        "NO_API_MODE check to the canonical fail-closed guard"
    )


def test_governor_precheck_has_fail_closed_no_api_check() -> None:
    path = REPO_ROOT / "scripts" / "swarm_governor_precheck.py"
    content = path.read_text()
    # Must call oc_no_api_guard.evaluate() and block on True result
    assert "oc_no_api_guard.evaluate" in content
    assert "BLOCKED_NO_API_MODE" in content


def test_governor_precheck_has_kill_switch_check() -> None:
    path = REPO_ROOT / "scripts" / "swarm_governor_precheck.py"
    content = path.read_text()
    assert "BLOCKED_KILL_SWITCH" in content
    assert "OC_GOVERNOR_EMERGENCY_KILL_SWITCH" in content


def test_governor_precheck_always_exits_zero() -> None:
    path = REPO_ROOT / "scripts" / "swarm_governor_precheck.py"
    content = path.read_text()
    # Must NOT call sys.exit(1) — exits 0 always; blocking is via output variables
    assert "sys.exit(1)" not in content, (
        "swarm_governor_precheck.py must not call sys.exit(1); "
        "it signals blocked state via GITHUB_OUTPUT and always exits 0"
    )


# ─── precheck functional tests ───────────────────────────────────────────────


def _run_precheck(env: dict[str, str]) -> tuple[str, dict[str, str]]:
    """Run swarm_governor_precheck.main() with given env, return (stdout, output_vars)."""
    import tempfile

    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        output_file = f.name

    try:
        with patch.dict(os.environ, {**env, "GITHUB_OUTPUT": output_file}, clear=True):
            # Reload to pick up fresh env
            scripts_dir = str(REPO_ROOT / "scripts")
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)

            captured = StringIO()
            with patch("sys.stdout", captured):
                import swarm_governor_precheck

                importlib.reload(swarm_governor_precheck)
                swarm_governor_precheck.main()

        with open(output_file) as f:
            lines = f.read().strip().splitlines()

        out_vars: dict[str, str] = {}
        for line in lines:
            if "=" in line:
                k, _, v = line.partition("=")
                out_vars[k] = v

        return captured.getvalue(), out_vars
    finally:
        Path(output_file).unlink(missing_ok=True)


def test_precheck_no_api_mode_absent_blocks() -> None:
    _, out = _run_precheck({})
    assert out.get("authorized") == "false"
    assert out.get("reason") == "BLOCKED_NO_API_MODE"


def test_precheck_no_api_mode_set_to_false_still_requires_paid_policy() -> None:
    _, out = _run_precheck({"NO_API_MODE": "false"})
    assert out.get("authorized") == "false"
    assert out.get("reason") == "BLOCKED_PAID_EXECUTION_DISABLED"


def test_precheck_no_api_mode_disabled_still_requires_paid_policy() -> None:
    _, out = _run_precheck({"NO_API_MODE": "disabled"})
    assert out.get("authorized") == "false"
    assert out.get("reason") == "BLOCKED_PAID_EXECUTION_DISABLED"


def test_precheck_emergency_kill_switch_blocks() -> None:
    _, out = _run_precheck(
        {"NO_API_MODE": "false", "OC_GOVERNOR_EMERGENCY_KILL_SWITCH": "true"}
    )
    assert out.get("authorized") == "false"
    assert out.get("reason") == "BLOCKED_KILL_SWITCH"


def test_precheck_kill_switch_case_insensitive() -> None:
    _, out = _run_precheck(
        {"NO_API_MODE": "false", "OC_GOVERNOR_EMERGENCY_KILL_SWITCH": "TRUE"}
    )
    assert out.get("authorized") == "false"
    assert out.get("reason") == "BLOCKED_KILL_SWITCH"


def test_precheck_probe_mode_never_authorizes_provider_execution() -> None:
    _, out = _run_precheck({"NO_API_MODE": "false"})
    assert out.get("authorized") == "false"
    assert out.get("reason") == "BLOCKED_PAID_EXECUTION_DISABLED"


def test_precheck_paid_mode_no_allowlist_blocks() -> None:
    _, out = _run_precheck(
        {
            "NO_API_MODE": "false",
            "OC_GOVERNOR_PAID_EXECUTION_ENABLED": "true",
            "OC_GOVERNOR_PROVIDER": "anthropic",
        }
    )
    assert out.get("authorized") == "false"
    assert out.get("reason") == "BLOCKED_NO_PROVIDER_ALLOWLIST"


def test_precheck_paid_mode_provider_not_in_allowlist_blocks() -> None:
    _, out = _run_precheck(
        {
            "NO_API_MODE": "false",
            "OC_GOVERNOR_PAID_EXECUTION_ENABLED": "true",
            "OC_GOVERNOR_PROVIDER": "openai",
            "OC_GOVERNOR_PROVIDER_ALLOWLIST": "anthropic",
        }
    )
    assert out.get("authorized") == "false"
    assert out.get("reason") == "BLOCKED_PROVIDER_NOT_ALLOWED"


def test_precheck_paid_mode_provider_in_allowlist_authorizes() -> None:
    _, out = _run_precheck(
        {
            "NO_API_MODE": "false",
            "OC_GOVERNOR_PAID_EXECUTION_ENABLED": "true",
            "OC_GOVERNOR_PROVIDER": "anthropic",
            "OC_GOVERNOR_PROVIDER_ALLOWLIST": "anthropic",
            "OC_GOVERNOR_PER_RUN_ESTIMATED_COST_USD": "0.50",
            "OC_GOVERNOR_PER_RUN_BUDGET_USD": "1.00",
            "OC_GOVERNOR_DAILY_BUDGET_USD": "5.00",
            "OC_GOVERNOR_MONTHLY_BUDGET_USD": "20.00",
        }
    )
    assert out.get("authorized") == "true"
    assert out.get("reason") == "AUTHORIZED"


def test_precheck_retry_limit_blocks() -> None:
    _, out = _run_precheck(
        {
            "NO_API_MODE": "false",
            "OC_GOVERNOR_PAID_EXECUTION_ENABLED": "true",
            "OC_GOVERNOR_PROVIDER_ALLOWLIST": "anthropic",
            "OC_GOVERNOR_PROVIDER": "anthropic",
            "OC_GOVERNOR_RETRY_COUNT": "3",
            "OC_GOVERNOR_MAX_RETRIES": "1",
        }
    )
    assert out.get("authorized") == "false"
    assert out.get("reason") == "BLOCKED_RETRY_LIMIT_EXCEEDED"


def test_precheck_daily_budget_blocks() -> None:
    _, out = _run_precheck(
        {
            "NO_API_MODE": "false",
            "OC_GOVERNOR_PAID_EXECUTION_ENABLED": "true",
            "OC_GOVERNOR_PROVIDER_ALLOWLIST": "anthropic",
            "OC_GOVERNOR_PROVIDER": "anthropic",
            "OC_GOVERNOR_DAILY_BUDGET_USD": "5.00",
            "OC_GOVERNOR_DAILY_SPEND_USD": "4.80",
            "OC_GOVERNOR_MONTHLY_BUDGET_USD": "20.00",
            "OC_GOVERNOR_PER_RUN_BUDGET_USD": "1.00",
            "OC_GOVERNOR_PER_RUN_ESTIMATED_COST_USD": "0.30",
        }
    )
    assert out.get("authorized") == "false"
    assert out.get("reason") == "BLOCKED_DAILY_BUDGET_EXCEEDED"


def test_precheck_monthly_budget_blocks() -> None:
    _, out = _run_precheck(
        {
            "NO_API_MODE": "false",
            "OC_GOVERNOR_PAID_EXECUTION_ENABLED": "true",
            "OC_GOVERNOR_PROVIDER_ALLOWLIST": "anthropic",
            "OC_GOVERNOR_PROVIDER": "anthropic",
            "OC_GOVERNOR_DAILY_BUDGET_USD": "5.00",
            "OC_GOVERNOR_MONTHLY_BUDGET_USD": "20.00",
            "OC_GOVERNOR_MONTHLY_SPEND_USD": "19.90",
            "OC_GOVERNOR_PER_RUN_BUDGET_USD": "1.00",
            "OC_GOVERNOR_PER_RUN_ESTIMATED_COST_USD": "0.20",
        }
    )
    assert out.get("authorized") == "false"
    assert out.get("reason") == "BLOCKED_MONTHLY_BUDGET_EXCEEDED"


def test_precheck_per_run_budget_blocks() -> None:
    _, out = _run_precheck(
        {
            "NO_API_MODE": "false",
            "OC_GOVERNOR_PAID_EXECUTION_ENABLED": "true",
            "OC_GOVERNOR_PROVIDER_ALLOWLIST": "anthropic",
            "OC_GOVERNOR_PROVIDER": "anthropic",
            "OC_GOVERNOR_PER_RUN_BUDGET_USD": "1.00",
            "OC_GOVERNOR_PER_RUN_ESTIMATED_COST_USD": "2.00",
            "OC_GOVERNOR_DAILY_BUDGET_USD": "5.00",
            "OC_GOVERNOR_MONTHLY_BUDGET_USD": "20.00",
        }
    )
    assert out.get("authorized") == "false"
    assert out.get("reason") == "BLOCKED_PER_RUN_BUDGET_EXCEEDED"


def test_precheck_within_budget_authorizes() -> None:
    _, out = _run_precheck(
        {
            "NO_API_MODE": "false",
            "OC_GOVERNOR_PAID_EXECUTION_ENABLED": "true",
            "OC_GOVERNOR_PROVIDER_ALLOWLIST": "anthropic",
            "OC_GOVERNOR_PROVIDER": "anthropic",
            "OC_GOVERNOR_PER_RUN_BUDGET_USD": "1.00",
            "OC_GOVERNOR_PER_RUN_ESTIMATED_COST_USD": "0.50",
            "OC_GOVERNOR_DAILY_BUDGET_USD": "5.00",
            "OC_GOVERNOR_DAILY_SPEND_USD": "1.00",
            "OC_GOVERNOR_MONTHLY_BUDGET_USD": "20.00",
            "OC_GOVERNOR_MONTHLY_SPEND_USD": "5.00",
        }
    )
    assert out.get("authorized") == "true"
    assert out.get("reason") == "AUTHORIZED"


def test_precheck_paid_mode_missing_budget_blocks_fail_closed() -> None:
    _, out = _run_precheck(
        {
            "NO_API_MODE": "false",
            "OC_GOVERNOR_PAID_EXECUTION_ENABLED": "true",
            "OC_GOVERNOR_PROVIDER_ALLOWLIST": "anthropic",
            "OC_GOVERNOR_PROVIDER": "anthropic",
            "OC_GOVERNOR_PER_RUN_ESTIMATED_COST_USD": "0.50",
        }
    )
    assert out.get("authorized") == "false"
    assert out.get("reason", "").startswith("BLOCKED_MISSING_")


def test_precheck_paid_mode_malformed_budget_blocks_fail_closed() -> None:
    _, out = _run_precheck(
        {
            "NO_API_MODE": "false",
            "OC_GOVERNOR_PAID_EXECUTION_ENABLED": "true",
            "OC_GOVERNOR_PROVIDER_ALLOWLIST": "anthropic",
            "OC_GOVERNOR_PROVIDER": "anthropic",
            "OC_GOVERNOR_PER_RUN_ESTIMATED_COST_USD": "0.50",
            "OC_GOVERNOR_PER_RUN_BUDGET_USD": "not-money",
            "OC_GOVERNOR_DAILY_BUDGET_USD": "5.00",
            "OC_GOVERNOR_MONTHLY_BUDGET_USD": "20.00",
        }
    )
    assert out.get("authorized") == "false"
    assert out.get("reason") == "BLOCKED_INVALID_PER_RUN_BUDGET_USD"


def test_completion_lane_uses_compact_packet_and_primary_governor() -> None:
    path = WORKFLOWS_DIR / "orchid-completion-lane.yml"
    text = path.read_text()
    assert "swarm_prepare_work_packet.py" in text
    assert "steps.packet.outputs.packet" in text
    assert "Swarm governor precheck — primary provider" in text
    assert "steps.governor.outputs.authorized == 'true'" in text


def test_completion_lane_cross_provider_fallback_is_disabled() -> None:
    wf = load_workflow("orchid-completion-lane.yml")
    steps = all_steps(wf)
    by_name = {s.get("name"): s for s in steps}
    assert by_name["Execute bounded Gemini fallback"]["if"] == "${{ false }}"
    assert by_name["Execute bounded OpenAI fallback"]["if"] == "${{ false }}"


def test_completion_lane_runs_deterministic_preflight_before_provider() -> None:
    wf = load_workflow("orchid-completion-lane.yml")
    steps = all_steps(wf)
    names = [s.get("name", "") for s in steps]
    assert names.index("Prepare compact work packet") < names.index(
        "Run deterministic preflight"
    )
    assert names.index("Run deterministic preflight") < names.index(
        "Execute issue with governed direct Anthropic API"
    )


def test_all_provider_workflows_require_explicit_paid_execution_policy() -> None:
    for workflow_name in PROVIDER_WORKFLOWS:
        wf = load_workflow(workflow_name)
        steps = all_steps(wf)
        prechecks = [s for s in steps if step_runs_script(s, GOVERNOR_PRECHECK_SCRIPT)]
        assert prechecks, workflow_name
        for step in prechecks:
            env = step.get("env", {}) or {}
            assert "OC_GOVERNOR_PAID_EXECUTION_ENABLED" in env, workflow_name
            assert "OC_GOVERNOR_PROVIDER_ALLOWLIST" in env, workflow_name
            assert "OC_GOVERNOR_PER_RUN_BUDGET_USD" in env, workflow_name
            assert "OC_GOVERNOR_DAILY_BUDGET_USD" in env, workflow_name
            assert "OC_GOVERNOR_MONTHLY_BUDGET_USD" in env, workflow_name


def test_swarm_controller_refill_requires_explicit_authorization() -> None:
    text = (WORKFLOWS_DIR / "orchid-swarm-controller.yml").read_text()
    assert "vars.OC_GOVERNOR_AUTO_REFILL == 'true'" in text


def test_completion_lane_uses_durable_github_ledger() -> None:
    text = (WORKFLOWS_DIR / "orchid-completion-lane.yml").read_text()
    assert "swarm_governor_github_ledger.py" in text
    assert "steps.ledger.outputs.daily_spend_usd" in text
    assert "steps.ledger.outputs.monthly_spend_usd" in text
    assert "--ledger-issue 1330" in text


def test_completion_lane_exhausted_retry_parks_in_backoff() -> None:
    text = (WORKFLOWS_DIR / "orchid-completion-lane.yml").read_text()
    assert "Retry budget exhausted; issue parked in oc-runtime-backoff." in text
    assert "automatic refill remains disabled unless explicitly authorized." in text


def test_completion_lane_uses_direct_anthropic_executor_after_governor() -> None:
    wf = load_workflow("orchid-completion-lane.yml")
    steps = all_steps(wf)
    claude = next(
        s
        for s in steps
        if s.get("name") == "Execute issue with governed direct Anthropic API"
    )
    run = claude.get("run", "") or ""
    env = claude.get("env", {}) or {}
    assert "scripts/swarm_anthropic_direct.py" in run
    assert env.get("ANTHROPIC_API_KEY") == "${{ secrets.ANTHROPIC_API_KEY }}"
    assert env.get("GH_TOKEN") == "${{ github.token }}"


def test_completion_lane_classifier_uses_action_execution_file_output() -> None:
    text = (WORKFLOWS_DIR / "orchid-completion-lane.yml").read_text()
    assert "CLAUDE_EXECUTION_FILE: ${{ steps.claude.outputs.execution_file }}" in text
    assert "kind=no_execution" in text
    assert "kind=no_model_usage" in text
    assert "kind=workflow_validation_skip" in text


def test_no_execution_is_parked_without_paid_retry() -> None:
    text = (WORKFLOWS_DIR / "orchid-completion-lane.yml").read_text()
    assert '"$CLAUDE_KIND" == "no_execution"' in text
    assert "Parked in oc-runtime-backoff; no automatic paid retry." in text


def test_claude_workflows_do_not_use_deprecated_colon_wildcard_syntax() -> None:
    completion = (WORKFLOWS_DIR / "orchid-completion-lane.yml").read_text()
    governed = (WORKFLOWS_DIR / "claude-code-governed.yml").read_text()
    assert ":*)" not in completion
    assert ":*)" not in governed
    assert "Bash(git add *)" in governed
    assert "Bash(git push *)" in governed
    assert "anthropics/claude-code-action@v1" not in completion
    assert "scripts/swarm_anthropic_direct.py" in completion


def test_completion_lane_extracts_result_level_provider_error_fields() -> None:
    text = (WORKFLOWS_DIR / "orchid-completion-lane.yml").read_text()
    assert "result_error=$(jq -r" in text
    assert "api_error_status=$(jq -r" in text
    assert "kind=billing_exhausted" in text
    assert "api_error_status" in text


def test_billing_and_auth_errors_precede_generic_no_model_usage() -> None:
    text = (WORKFLOWS_DIR / "orchid-completion-lane.yml").read_text()
    billing = text.index("kind=billing_exhausted")
    security = text.index("kind=security")
    no_model = text.index("kind=no_model_usage")
    assert billing < no_model
    assert security < no_model


def test_completion_lane_classifies_anthropic_usage_limit_as_billing_exhausted() -> (
    None
):
    text = (WORKFLOWS_DIR / "orchid-completion-lane.yml").read_text()
    assert "reached your specified api usage limits" in text
    assert "api usage limit" in text
    assert "kind=billing_exhausted" in text


def test_max_turns_precedes_generic_provider_failure_classification() -> None:
    text = (WORKFLOWS_DIR / "orchid-completion-lane.yml").read_text()
    max_turns = text.index("kind=max_turns")
    provider_failure = text.index("kind=provider_failure")
    assert max_turns < provider_failure


def test_anthropic_http_5xx_precedes_generic_provider_failure() -> None:
    text = (WORKFLOWS_DIR / "orchid-completion-lane.yml").read_text()
    http_5xx = text.index('api_error_status" =~ ^5')
    provider_failure = text.index("kind=provider_failure")
    assert http_5xx < provider_failure
    assert "kind=safe_provider" in text
