"""Opt-in workspace refresh: newly committed work becomes discoverable, safely."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from app.calyx_orchestrator.workspace_refresh import (
    WorkspaceRefresher,
    refresher_from_env,
)
from runtime.program_autonomy_brain_worker import configuration_problems

BRANCH = "acceptance/source"
IN_FLIGHT = {"work": {"w1": {"state": "in_flight"}, "w0": {"state": "completed"}}}
SETTLED = {"work": {"w0": {"state": "completed"}}}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _commit(repo: Path, name: str, text: str) -> str:
    (repo / name).write_text(text)
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.email=t@example.invalid",
        "-c",
        "user.name=t",
        "commit",
        "-qm",
        f"add {name}",
    )
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repos(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", BRANCH)
    _commit(origin, "batch_1.json", "{}")
    workspace = tmp_path / "workspace"
    subprocess.run(
        [
            "git",
            "clone",
            "-q",
            "--depth",
            "1",
            "--branch",
            BRANCH,
            f"file://{origin}",
            str(workspace),
        ],
        check=True,
    )
    _git(workspace, "checkout", "-q", "-b", "autonomy/hosted-acceptance")
    (workspace / ".calyx-isolated-workspace.json").write_text("{}")  # untracked
    return origin, workspace


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_new_commit_is_pulled_in_only_when_nothing_is_in_flight(repos):
    origin, workspace = repos
    clock = Clock()
    refresher = WorkspaceRefresher(workspace, BRANCH, 300, clock=clock)
    first = _git(workspace, "rev-parse", "HEAD")
    assert refresher.refresh(SETTLED) == {"status": "current", "commit": first}

    new = _commit(origin, "batch_2.json", "{}")
    clock.now = 10
    assert refresher.refresh(SETTLED) == {"status": "not_due"}
    clock.now = 400
    # Submitted work pins its files: never refresh under it.
    assert refresher.refresh(IN_FLIGHT) == {
        "status": "deferred_in_flight",
        "in_flight": 1,
    }
    assert not (workspace / "batch_2.json").exists()
    # Deferral does not restart the interval: retried as soon as work settles.
    clock.now = 401
    assert refresher.refresh(SETTLED) == {"status": "updated", "from": first, "to": new}
    assert (workspace / "batch_2.json").is_file()
    # Branch name and the untracked isolation marker survive.
    assert (
        _git(workspace, "rev-parse", "--abbrev-ref", "HEAD")
        == "autonomy/hosted-acceptance"
    )
    assert (workspace / ".calyx-isolated-workspace.json").is_file()


def test_modified_tracked_files_are_never_overwritten(repos):
    origin, workspace = repos
    _commit(origin, "batch_2.json", "{}")
    (workspace / "batch_1.json").write_text('{"local": "change"}')
    report = WorkspaceRefresher(workspace, BRANCH, 300, clock=Clock()).refresh(SETTLED)
    assert report == {"status": "skipped_dirty"}
    assert (workspace / "batch_1.json").read_text() == '{"local": "change"}'


def test_git_failure_is_reported_not_raised(repos):
    _origin, workspace = repos
    report = WorkspaceRefresher(
        workspace, "no-such-branch", 300, clock=Clock()
    ).refresh(SETTLED)
    assert report["status"] == "failed" and report["detail"].startswith("GIT_FAILED:")


@pytest.mark.parametrize("ref", ["--upload-pack=x", "a..b", "", "a b"])
def test_unsafe_refs_are_rejected(ref, tmp_path):
    with pytest.raises(ValueError, match="REFRESH_REF_INVALID"):
        WorkspaceRefresher(tmp_path, ref, 300)


def test_configuration_is_off_by_default_and_validated(tmp_path):
    assert refresher_from_env({}, workspace=str(tmp_path)) is None
    assert (
        refresher_from_env(
            {"OC_BRAIN_WORKSPACE_REFRESH_SECONDS": "0"}, workspace=str(tmp_path)
        )
        is None
    )
    env = {
        "OC_BRAIN_WORKSPACE_REFRESH_SECONDS": "300",
        "OC_BRAIN_WORKSPACE_REFRESH_REF": BRANCH,
    }
    assert refresher_from_env(env, workspace=str(tmp_path)).interval_seconds == 300
    with pytest.raises(ValueError, match="OUT_OF_RANGE"):
        refresher_from_env(
            {**env, "OC_BRAIN_WORKSPACE_REFRESH_SECONDS": "5"}, workspace=str(tmp_path)
        )
    with pytest.raises(ValueError, match="REF_REQUIRED"):
        refresher_from_env(
            {"OC_BRAIN_WORKSPACE_REFRESH_SECONDS": "300"}, workspace=str(tmp_path)
        )
    with pytest.raises(ValueError, match="REQUIRES_WORKSPACE"):
        refresher_from_env(env, workspace="")


def test_worker_reports_refresh_misconfiguration_before_starting(tmp_path):
    problems = configuration_problems(
        {
            "OC_BRAIN_WORK_MANIFEST": str(tmp_path / "missing.json"),
            "OC_BRAIN_WORKSPACE_REFRESH_SECONDS": "300",
        }
    )
    assert "OC_BRAIN_WORKSPACE_REFRESH_REQUIRES_WORK_SOURCES" in problems
    assert "OC_BRAIN_WORKSPACE_REFRESH_REQUIRES_WORKSPACE" in problems
