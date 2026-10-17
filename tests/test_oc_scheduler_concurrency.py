"""Dispatch-only entrypoints must not contend with execution for a queue slot."""

from pathlib import Path

import pytest
import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"


@pytest.mark.parametrize(
    "entrypoint",
    [
        "orchid-continuous-completion.yml",
        "orchid-continuous-pulse.yml",
        "oc-integration-handoff.yml",
    ],
)
def test_dispatch_entrypoints_do_not_evict_pending_controller(entrypoint):
    controller = yaml.safe_load((WORKFLOWS / "orchid-swarm-controller.yml").read_text())
    dispatcher = yaml.safe_load((WORKFLOWS / entrypoint).read_text())
    controller_group = controller["concurrency"]["group"]
    dispatcher_group = dispatcher.get("concurrency", {}).get("group")
    # GitHub permits only one pending run in a concurrency group, even with
    # cancel-in-progress=false. A redirect arriving behind an active controller
    # must not replace that controller's pending autonomous refill.
    assert dispatcher_group != controller_group


def test_controller_still_serializes_execution_without_cancelling_active_work():
    controller = yaml.safe_load((WORKFLOWS / "orchid-swarm-controller.yml").read_text())
    assert controller["concurrency"]["cancel-in-progress"] is False
    group = controller["concurrency"]["group"]
    assert "'orchid-swarm-controller'" in group
    assert "'orchid-swarm-pulse'" in group
    assert "github.event_name == 'schedule'" in group
    assert "github.ref != 'refs/heads/oc-autonomous-integration'" in group


def test_default_branch_schedule_redirects_before_any_queue_or_lease_operation():
    controller = yaml.safe_load((WORKFLOWS / "orchid-swarm-controller.yml").read_text())
    redirect = controller["jobs"]["scheduled-pulse"]
    predicate = (
        "github.event_name == 'schedule' && "
        "github.ref != 'refs/heads/oc-autonomous-integration'"
    )
    assert redirect["if"] == "${{ " + predicate + " }}"
    assert controller["jobs"]["plan"]["if"] == "${{ !(" + predicate + ") }}"
    assert redirect["permissions"] == {"contents": "read", "actions": "write"}
    assert len(redirect["steps"]) == 1
    run = redirect["steps"][0]["run"]
    assert "gh workflow run orchid-swarm-controller.yml" in run
    assert "--ref oc-autonomous-integration" in run
    assert "Dispatch accepted; execution and completion remain unproven" in run


def test_default_branch_pulse_uses_the_existing_controller_dispatch_contract(tmp_path):
    import os
    import subprocess

    controller = yaml.safe_load((WORKFLOWS / "orchid-swarm-controller.yml").read_text())
    step = controller["jobs"]["scheduled-pulse"]["steps"][0]
    fake_gh = tmp_path / "gh"
    fake_gh.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$OC_TEST_ARGS"\n')
    fake_gh.chmod(0o700)
    args = tmp_path / "args"
    summary = tmp_path / "summary"
    env = {
        "PATH": f"{tmp_path}:/usr/bin:/bin",
        "GITHUB_REPOSITORY": "test/repository",
        "GITHUB_STEP_SUMMARY": str(summary),
        "OC_TEST_ARGS": str(args),
    }
    # The shell command is real; GitHub is intentionally simulated. No token
    # or inherited production credential enters the subprocess.
    result = subprocess.run(
        ["bash", "-c", step["run"]],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert args.read_text().splitlines() == [
        "workflow",
        "run",
        "orchid-swarm-controller.yml",
        "--repo",
        "test/repository",
        "--ref",
        "oc-autonomous-integration",
    ]
    assert "completion remain unproven" in summary.read_text()
    # A failed dispatch must be red, not a false-success receipt.
    fake_gh.write_text("#!/bin/sh\nexit 9\n")
    os.unlink(summary)
    failed = subprocess.run(
        ["bash", "-c", step["run"]],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert failed.returncode == 9
    assert not summary.exists()
