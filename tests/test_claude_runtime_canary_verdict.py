"""Behavioural contract for the Claude runtime canary's verdict logic.

The canary drives a repository-wide circuit breaker: a PASS closes the circuit and
lets the scheduler dispatch paid Claude workers again. It previously derived that
verdict from the action's step outcome alone, which is unsafe, because
anthropics/claude-code-action@v1 exits ``outcome=success`` when it *skips*
execution:

    Workflow validation failed. The workflow file must exist and have identical
    content to the version on the repository's default branch.
    ...
    Exiting due to workflow validation skip
    ##[end-action id=claude.run;outcome=success;conclusion=success

A canary that never called Claude therefore reported PASS and closed the circuit.
These tests run the real shell from the workflow against fixtures and pin that a
verdict now requires positive proof of execution.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

CANARY = Path(".github/workflows/orchid-claude-runtime-canary.yml")
PUBLISH_STEP = "Publish canary result and control runtime circuit"


@pytest.fixture(scope="module")
def canary() -> dict:
    return yaml.safe_load(CANARY.read_text())


@pytest.fixture(scope="module")
def publish_script(canary) -> str:
    for step in canary["jobs"]["canary"]["steps"]:
        if step.get("name") == PUBLISH_STEP:
            return step["run"]
    raise AssertionError(f"{PUBLISH_STEP!r} step not found")


def run_verdict(script: str, tmp_path: Path, outcome: str, record: object | None):
    """Execute the real publish-step shell with `gh` stubbed out."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "gh-calls.txt"
    gh = bin_dir / "gh"
    gh.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$GH_CALLS"\nexit 0\n')
    gh.chmod(0o755)

    log = tmp_path / "claude-execution-output.json"
    if record is not None:
        log.write_text(json.dumps(record))

    proc = subprocess.run(
        ["bash", "-c", script.replace("${{ github.repository }}", "owner/repo")],
        capture_output=True,
        text=True,
        check=False,
        env={
            "PATH": f"{bin_dir}:/usr/bin:/bin",
            "GH_CALLS": str(calls),
            "GH_TOKEN": "x",
            "GITHUB_REPOSITORY": "owner/repo",
            "OUTCOME": outcome,
            "RUN_URL": "https://example.invalid/run/1",
            "CLAUDE_EXECUTION_LOG": str(log),
        },
    )
    recorded = calls.read_text() if calls.exists() else ""
    return proc, recorded


RESULT_OK = [{"type": "system", "subtype": "init"}, {"type": "result", "subtype": "success", "is_error": False}]
RESULT_ERR = [{"type": "system", "subtype": "init"}, {"type": "result", "subtype": "success", "is_error": True}]


def test_a_real_clean_execution_closes_the_circuit(publish_script, tmp_path):
    proc, calls = run_verdict(publish_script, tmp_path, "success", RESULT_OK)
    assert proc.returncode == 0, proc.stderr
    assert "verdict: pass" in proc.stdout
    assert "--remove-label oc-runtime-degraded" in calls
    assert "--add-label oc-runtime-degraded" not in calls


def test_a_real_failed_execution_opens_the_circuit(publish_script, tmp_path):
    proc, calls = run_verdict(publish_script, tmp_path, "failure", RESULT_ERR)
    assert proc.returncode == 1
    assert "verdict: fail" in proc.stdout
    assert "--add-label oc-runtime-degraded" in calls
    assert "--remove-label oc-runtime-degraded" not in calls


def test_workflow_validation_skip_never_closes_the_circuit(publish_script, tmp_path):
    """The regression this exists for: outcome=success with no execution record."""
    proc, calls = run_verdict(publish_script, tmp_path, "success", None)
    assert proc.returncode == 1
    assert "verdict: indeterminate" in proc.stdout
    assert "--remove-label oc-runtime-degraded" not in calls
    # An inconclusive probe must not move the circuit in EITHER direction.
    assert "--add-label oc-runtime-degraded" not in calls
    assert "INDETERMINATE" in calls


def test_a_failed_step_is_never_upgraded_by_a_clean_record(publish_script, tmp_path):
    proc, calls = run_verdict(publish_script, tmp_path, "failure", RESULT_OK)
    assert proc.returncode == 1
    assert "verdict: fail" in proc.stdout
    assert "--add-label oc-runtime-degraded" in calls


def test_is_error_true_fails_even_when_the_step_reports_success(publish_script, tmp_path):
    proc, calls = run_verdict(publish_script, tmp_path, "success", RESULT_ERR)
    assert proc.returncode == 1
    assert "verdict: fail" in proc.stdout
    assert "--add-label oc-runtime-degraded" in calls


def test_malformed_record_is_indeterminate_not_a_pass(publish_script, tmp_path):
    proc, calls = run_verdict(publish_script, tmp_path, "success", {"unexpected": "shape"})
    assert proc.returncode == 1
    assert "verdict: indeterminate" in proc.stdout
    assert "--remove-label oc-runtime-degraded" not in calls


# --- structural guarantees ---------------------------------------------------

def test_canary_is_dispatch_only(canary):
    # The action rejects the push event outright, so a push-triggered canary could
    # only ever open the circuit against a runtime it never tested.
    assert list(canary[True].keys()) == ["workflow_dispatch"]


def test_canary_surfaces_the_sdk_error(canary):
    step = next(s for s in canary["jobs"]["canary"]["steps"] if s.get("id") == "claude")
    assert step["with"]["show_full_output"] is True


def test_verdict_is_not_taken_from_step_outcome_alone(publish_script):
    assert 'if [[ "$OUTCOME" != "success" ]]' in publish_script
    assert "select(.type == \"result\")" in publish_script
    assert "verdict=indeterminate" in publish_script
