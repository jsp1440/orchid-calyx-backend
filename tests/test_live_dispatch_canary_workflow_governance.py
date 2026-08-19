"""Static governance checks on .github/workflows/live-dispatch-canary.yml
itself - the structural properties a code-review of the running dispatch
logic cannot see, since they live entirely in the workflow's own
configuration (trigger surface, permission scope, secret placement,
concurrency behavior)."""
from __future__ import annotations

from pathlib import Path

import yaml

WORKFLOW_PATH = (
    Path(__file__).resolve().parent.parent / ".github" / "workflows" / "live-dispatch-canary.yml"
)


def _load_workflow() -> dict:
    # YAML parses the bare `on:` key as the boolean True, not the string
    # "on" - PyYAML's known quirk with the 1.1 boolean set. Load raw and
    # normalize rather than relying on a key name that isn't reliably there.
    raw = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    return raw


def test_workflow_file_exists_and_parses() -> None:
    workflow = _load_workflow()
    assert workflow["name"] == "Live Dispatch Canary (manual, one-shot)"


def test_trigger_is_workflow_dispatch_only() -> None:
    workflow = _load_workflow()
    triggers = workflow.get("on") or workflow.get(True)
    assert isinstance(triggers, dict)
    assert set(triggers.keys()) == {"workflow_dispatch"}


def test_top_level_permissions_are_locked_to_read_only_contents() -> None:
    workflow = _load_workflow()
    assert workflow["permissions"] == {"contents": "read"}


def test_concurrency_group_prevents_simultaneous_runs_without_cancelling_in_progress() -> None:
    workflow = _load_workflow()
    concurrency = workflow["concurrency"]
    assert concurrency["group"] == "live-dispatch-canary"
    assert concurrency["cancel-in-progress"] is False


def test_checkout_step_does_not_persist_credentials() -> None:
    workflow = _load_workflow()
    steps = workflow["jobs"]["live-dispatch-canary"]["steps"]
    checkout_steps = [step for step in steps if step.get("uses", "").startswith("actions/checkout")]
    assert len(checkout_steps) == 1
    assert checkout_steps[0]["with"]["persist-credentials"] is False


def test_coding_agent_secret_appears_in_exactly_one_step_and_it_is_the_execute_step() -> None:
    workflow = _load_workflow()
    job = workflow["jobs"]["live-dispatch-canary"]

    # It must not be present at job level at all.
    job_env = job.get("env", {})
    assert "CALYX_GITHUB_CODING_AGENT_TOKEN" not in job_env
    for value in job_env.values():
        assert "CALYX_GITHUB_CODING_AGENT_TOKEN" not in str(value)

    steps = job["steps"]
    steps_with_secret = [
        step for step in steps
        if "CALYX_GITHUB_CODING_AGENT_TOKEN" in str(step.get("env", {}))
    ]
    assert len(steps_with_secret) == 1
    only_step = steps_with_secret[0]
    assert only_step["env"]["CALYX_LIVE_DISPATCH_EXECUTE"] == "true"
    assert only_step.get("if") == "${{ inputs.execute == true }}"
    assert only_step["env"]["CALYX_GITHUB_CODING_AGENT_TOKEN"] == "${{ secrets.CALYX_GITHUB_CODING_AGENT_TOKEN }}"


def test_preflight_and_execute_steps_have_mutually_exclusive_conditions() -> None:
    workflow = _load_workflow()
    steps = workflow["jobs"]["live-dispatch-canary"]["steps"]
    run_steps = [step for step in steps if "run" in step and "run_live_dispatch_canary.py" in step["run"]]
    assert len(run_steps) == 2
    conditions = {step["if"] for step in run_steps}
    assert conditions == {"${{ inputs.execute != true }}", "${{ inputs.execute == true }}"}


def test_no_schedule_or_push_or_pull_request_trigger_exists() -> None:
    raw_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    for forbidden in ("schedule:", "push:", "pull_request:"):
        assert forbidden not in raw_text
