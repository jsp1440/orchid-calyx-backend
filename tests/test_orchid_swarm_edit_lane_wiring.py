"""Workflow wiring for the provider-free edit lane (scripts/oc_work_edit_lane.py).

The edit lane writes one mechanically derived line on an isolated
``oc/discovered-<fingerprint>`` branch and opens a draft pull request against
the integration branch. The workflow must grant exactly the authority that
needs, hand the lane its inputs, park the issue on the pull request, retain the
evidence, and make every other push target unreachable at the git level.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "orchid-swarm-controller.yml"


def _job():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    return workflow["jobs"]["provider_free_workers"]


def _step(name: str) -> dict:
    return next(step for step in _job()["steps"] if step.get("name") == name)


def test_edit_lane_job_receives_exactly_the_mutation_authority_it_needs():
    job = _job()
    assert job["permissions"] == {
        "contents": "write",
        "issues": "write",
        "pull-requests": "write",
    }
    # The workflow-level ceiling stays read-biased; only this job is raised.
    header = WORKFLOW.read_text(encoding="utf-8").split("\njobs:", maxsplit=1)[0]
    assert "contents: read" in header
    assert "pull-requests: read" in header


def test_checkout_has_history_and_a_pushable_remote():
    checkout = _step("Checkout controller revision")
    assert checkout["with"]["fetch-depth"] == 0
    assert checkout["with"]["persist-credentials"] is True
    # Pinned, not github.ref_name: that is `main` on schedule/issues runs and
    # `<N>/merge` on pull_request runs, neither of which is a PR base.
    assert _job()["env"]["INTEGRATION_BRANCH"] == "oc-autonomous-integration"


def test_the_edit_lane_runs_only_on_a_run_of_the_integration_ref():
    run = _step("Execute deterministic provider-free work")["run"]
    edit_block = run.split('if [[ "$mode" == "edit" ]]; then', maxsplit=1)[1]
    guard = 'if [[ "$GITHUB_REF" != "refs/heads/$INTEGRATION_BRANCH" ]]; then'
    assert guard in edit_block
    # The guard fails the step (the fail-closed release parks the issue with
    # evidence) before the lane can create a worktree, push or open a PR.
    assert edit_block.index(guard) < edit_block.index(
        "python3 -m scripts.oc_work_edit_lane"
    )
    assert "exit 2" in edit_block[edit_block.index(guard) : edit_block.index("set +e")]


def test_execute_step_runs_the_edit_lane_and_hands_its_receipt_to_the_worker():
    run = _step("Execute deterministic provider-free work")["run"]
    edit_block = run.split('if [[ "$mode" == "edit" ]]; then', maxsplit=1)[1]
    for fragment in (
        "python3 -m scripts.oc_work_edit_lane",
        '--issue-json "$issue"',
        '--repository "$GITHUB_REPOSITORY"',
        "--root .",
        '--base-sha "$INTEGRATION_SHA"',
        '--lease-comment "$lease"',
        '--integration-branch "$INTEGRATION_BRANCH"',
        '--github-output "$GITHUB_OUTPUT"',
        '> "$RUNNER_TEMP/provider-free-edit.json"',
        "edit_args=(--edit-json",
        "files_json=\"$(jq -c '.changed_files // []'",
    ):
        assert fragment in edit_block, fragment
    # The lane's exit status is a finding, not a job failure.
    assert edit_block.index("set +e") < edit_block.index(
        "python3 -m scripts.oc_work_edit_lane"
    )
    assert edit_block.index("set -e") > edit_block.index(
        "python3 -m scripts.oc_work_edit_lane"
    )
    # The worker verifies the actual write set against the lease.
    assert '--files-json "$files_json"' in run
    assert '"${validation_args[@]}" "${edit_args[@]}"' in run
    # The literal empty write set is gone: the worker now receives the lane's
    # actual changed files (still `[]` outside edit mode).
    assert "--files-json '[]'" not in run
    assert "files_json='[]'" in run
    # The validate lane is untouched.
    assert 'if [[ "$mode" == "validate" ]]; then' in run
    assert "python3 scripts/oc_provider_free_validate.py" in run


def test_blocked_case_records_the_pull_request_the_issue_waits_on():
    run = _step("Publish durable result and release lease")["run"]
    blocked = run.split("blocked)", maxsplit=1)[1].split("*)", maxsplit=1)[0]
    assert "--add-label oc-blocked" in blocked
    assert "blocked_on=$(jq -r '.blocked_on // empty'" in blocked
    assert "OC-BLOCKED-ON: ${blocked_on}" in blocked
    # done / owner-gate branches are unchanged.
    assert "--add-label oc-done" in run
    assert "--add-label oc-owner-gate" in run


def test_edit_receipt_is_retained_as_evidence():
    artifact = _step("Retain deterministic execution evidence")
    assert "${{ runner.temp }}/provider-free-edit.json" in artifact["with"]["path"]
    assert "${{ runner.temp }}/provider-free-result.json" in artifact["with"]["path"]


def test_budget_and_no_api_guards_are_intact():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Enforce fail-closed NO-API mode" in text
    assert "Observe current governed budget conditions" in text
    assert "gh pr merge" not in text
    assert "git push" not in text  # only the lane pushes, from its own worktree


def test_the_lane_pushes_only_through_its_structural_fence():
    # The pre-push hook is advisory to anyone who passes --no-verify; the
    # lane's one push call site builds its argv from fenced_push_args, which
    # refuses any refspec but <full sha>:refs/heads/oc/discovered-<16 hex>.
    source = (REPO_ROOT / "scripts" / "oc_work_edit_lane.py").read_text(
        encoding="utf-8"
    )
    assert source.count('"push"') == 2  # fenced_push_args + assert_fenced_push
    assert source.count("git_call(fenced_push_args(") == 1
    assert (
        'PUSH_DESTINATION = re.compile(r"^refs/heads/oc/discovered-[0-9a-f]{16}$")'
        in source
    )


def _hook_script() -> str:
    run = _step("Fence pushes to oc/discovered-* branches")["run"]
    return run.split("<<'HOOK'\n", maxsplit=1)[1].split("\nHOOK\n", maxsplit=1)[0]


def test_pre_push_fence_is_installed_before_any_lane_step_runs():
    names = [step.get("name") for step in _job()["steps"]]
    assert names.index("Fence pushes to oc/discovered-* branches") < names.index(
        "Verify provider-free worker claim"
    )
    run = _step("Fence pushes to oc/discovered-* branches")["run"]
    assert "core.hooksPath" in run
    assert re.search(r"refs/heads/oc/discovered-\*", _hook_script())


@pytest.fixture()
def scratch_repo(tmp_path: Path) -> tuple[Path, str, str]:
    """A repository with two commits, returning (path, older sha, newer sha)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args],
            cwd=repo,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    git("init", "-q", "-b", "main")
    (repo / "a").write_text("1\n")
    git("add", "a")
    git("commit", "-q", "-m", "one")
    older = git("rev-parse", "HEAD")
    (repo / "a").write_text("2\n")
    git("commit", "-q", "-am", "two")
    newer = git("rev-parse", "HEAD")
    hook = repo / "pre-push"
    hook.write_text(_hook_script())
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    return repo, older, newer


def _push_lines(repo: Path, lines: str) -> int:
    proc = subprocess.run(
        ["bash", str(repo / "pre-push"), "origin", "https://example.invalid/r.git"],
        cwd=repo,
        input=lines,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode


ZERO = "0" * 40


def test_fence_allows_a_new_or_fast_forward_discovered_branch(scratch_repo):
    repo, older, newer = scratch_repo
    assert (
        _push_lines(
            repo,
            f"refs/heads/oc/discovered-abc {newer} refs/heads/oc/discovered-abc {ZERO}\n",
        )
        == 0
    )
    assert (
        _push_lines(
            repo,
            f"refs/heads/oc/discovered-abc {newer} refs/heads/oc/discovered-abc {older}\n",
        )
        == 0
    )


@pytest.mark.parametrize(
    "remote_ref",
    [
        "refs/heads/main",
        "refs/heads/oc-autonomous-integration",
        "refs/heads/oc/other",
        "refs/tags/v1",
    ],
)
def test_fence_refuses_every_other_ref(scratch_repo, remote_ref):
    repo, _older, newer = scratch_repo
    assert (
        _push_lines(repo, f"refs/heads/oc/discovered-abc {newer} {remote_ref} {ZERO}\n")
        != 0
    )


def test_fence_refuses_forced_updates_and_deletions(scratch_repo):
    repo, older, newer = scratch_repo
    # non-fast-forward: remote is ahead of what we push
    assert (
        _push_lines(
            repo,
            f"refs/heads/oc/discovered-abc {older} refs/heads/oc/discovered-abc {newer}\n",
        )
        != 0
    )
    # deletion
    assert (
        _push_lines(repo, f"(delete) {ZERO} refs/heads/oc/discovered-abc {newer}\n")
        != 0
    )


def test_fence_refuses_a_mixed_push_entirely(scratch_repo):
    repo, _older, newer = scratch_repo
    lines = (
        f"refs/heads/oc/discovered-abc {newer} refs/heads/oc/discovered-abc {ZERO}\n"
        f"refs/heads/oc/discovered-abc {newer} refs/heads/main {ZERO}\n"
    )
    assert _push_lines(repo, lines) != 0
