"""The completion lane's job boundary: the model never shares a job with a write token.

Review of #1973 showed that model-written code running in the job that held
GH_TOKEN could rewrite git configuration, shadow binaries or poison the tree
later trusted steps ran from, and so reach the credential however its
environment was scrubbed. The lane is therefore three jobs. These tests pin the
boundary as a contract on the workflow itself.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

WORKFLOW = Path(".github/workflows/orchid-completion-lane.yml")
TEXT = WORKFLOW.read_text(encoding="utf-8")
JOBS = yaml.safe_load(TEXT)["jobs"]
WRITE = {"write"}


def _steps(job):
    return JOBS[job]["steps"]


def _names(job):
    return [s.get("name") for s in _steps(job)]


def _blob(value):
    return yaml.safe_dump(value, sort_keys=True)


def test_the_lane_is_exactly_admit_model_publish():
    assert list(JOBS) == ["execute", "model", "publish"]
    assert JOBS["model"]["needs"] == "execute"
    assert JOBS["publish"]["needs"] == ["execute", "model"]
    assert yaml.safe_load(TEXT)["permissions"] == {"contents": "read"}


def test_the_model_job_has_no_write_permission_and_no_token_in_env():
    model = JOBS["model"]
    assert model["permissions"] == {"contents": "read", "issues": "read"}
    assert not set(model["permissions"].values()) & WRITE
    assert "GH_TOKEN" not in model.get("env", {})
    assert "GITHUB_TOKEN" not in model.get("env", {})
    # One trusted step, before any model-driven code exists on the runner,
    # gets the read-only token; nothing after it does.
    with_token = [
        s.get("name") for s in _steps("model") if "github.token" in _blob(s.get("env"))
    ]
    assert with_token == ["Verify lease time before paid execution"]
    names = _names("model")
    assert (
        names.index(with_token[0])
        < names.index("Isolate model-driven execution in an unprivileged account")
        < names.index("Execute issue with governed direct Anthropic API")
    )
    secrets = re.findall(r"secrets\.([A-Z_]+)", _blob(model))
    assert secrets == ["ANTHROPIC_API_KEY"]


def test_the_model_job_cannot_push_comment_or_open_a_pull_request():
    for step in _steps("model"):
        run = str(step.get("run") or "")
        assert "git push" not in run
        assert not re.search(r"(^|\s)gh (pr|issue|api|workflow)\b", run), step.get(
            "name"
        )


def test_model_driven_code_runs_as_an_unprivileged_account():
    (claude,) = [s for s in _steps("model") if s.get("id") == "claude"]
    run = claude["run"]
    assert (
        'sudo -n -H -u "$MODEL_USER" --preserve-env=ANTHROPIC_API_KEY,GITHUB_RUN_ID'
        in run
    )
    assert (
        '"$python_bin" -I "$MODEL_HOME/repo/scripts/swarm_anthropic_direct.py"' in run
    )
    assert '--emit-patch-dir "$MODEL_HOME/out"' in run
    assert "GH_TOKEN" not in _blob(claude.get("env"))
    (isolate,) = [
        s
        for s in _steps("model")
        if s.get("name") == "Isolate model-driven execution in an unprivileged account"
    ]
    body = isolate["run"]
    assert "sudo useradd" in body
    assert 'sudo -u "$MODEL_USER" sudo -n true' in body
    assert 'sudo chmod 0700 "$MODEL_HOME" "$HOME"' in body
    for group in ("docker", "sudo", "adm"):
        assert group in body
    assert 'test -r "$GITHUB_WORKSPACE/.git/config"' in body


def _collect_step():
    (collect,) = [
        s
        for s in _steps("model")
        if s.get("name") == "Collect model output for the trusted publisher"
    ]
    return collect


def test_model_output_is_collected_by_digest_after_killing_model_processes():
    run = _collect_step()["run"]
    kill = run.index('sudo -n -u "$MODEL_USER" kill -9 -1')
    verify = run.index('pgrep -u "$MODEL_USER"')
    assert kill < verify < run.index("oc_patch_publish.py collect")
    assert "python3 -I scripts/oc_patch_publish.py collect" in run
    # The collector reads as the model account, never as root.
    assert '--model-user "$MODEL_USER"' in run


def _run_collect_step(tmp_path, pgrep_survivors):
    """Run the real step script against stubbed sudo, pgrep, sleep and python3.

    ``pgrep_survivors`` is the list of exit statuses pgrep returns, call by
    call; the last one repeats. 0 is "a process matched", 1 is "none".
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    statuses = tmp_path / "pgrep-statuses"
    statuses.write_text("\n".join(str(s) for s in pgrep_survivors) + "\n")
    stubs = {
        "sudo": f'echo "sudo $*" >> "{log}"\n',
        "sleep": f'echo "sleep $*" >> "{log}"\n',
        "python3": f'echo "python3 $*" >> "{log}"\n',
        "pgrep": (
            f'echo "pgrep $*" >> "{log}"\n'
            f'status=$(head -n 1 "{statuses}")\n'
            f'if [ "$(wc -l < "{statuses}")" -gt 1 ]; then\n'
            f'  tail -n +2 "{statuses}" > "{statuses}.next"\n'
            f'  mv "{statuses}.next" "{statuses}"\n'
            "fi\n"
            'exit "$status"\n'
        ),
    }
    for name, body in stubs.items():
        stub = bin_dir / name
        stub.write_text("#!/bin/sh\n" + body)
        stub.chmod(0o755)
    script = tmp_path / "step.sh"
    script.write_text(_collect_step()["run"])
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "MODEL_USER": "oc-model",
        "MODEL_HOME": str(tmp_path / "home"),
        "RUNNER_TEMP": str(tmp_path),
    }
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return result, calls


def test_a_fork_loop_is_killed_repeatedly_until_none_remain(tmp_path):
    # Survivors on the first two checks, gone on the third.
    result, calls = _run_collect_step(tmp_path, [0, 0, 1])
    assert result.returncode == 0, result.stderr
    kills = [c for c in calls if c.startswith("sudo ")]
    assert kills == ["sudo -n -u oc-model kill -9 -1"] * 3
    assert sum(c.startswith("pgrep ") for c in calls) == 3
    assert calls[-1].startswith("python3 -I scripts/oc_patch_publish.py collect")


def test_a_process_that_survives_every_round_fails_closed(tmp_path):
    result, calls = _run_collect_step(tmp_path, [0])
    assert result.returncode != 0
    assert "survived" in result.stderr
    # Bounded, and nothing is collected.
    assert sum(c.startswith("sudo ") for c in calls) == 30
    assert not any(c.startswith("python3 ") for c in calls)


def test_a_pgrep_error_is_not_read_as_none_remaining(tmp_path):
    result, calls = _run_collect_step(tmp_path, [2])
    assert result.returncode != 0
    assert not any(c.startswith("python3 ") for c in calls)


def _classify(tmp_path, record, conclusion="failure", outcome="failure"):
    (step,) = [s for s in _steps("publish") if s.get("id") == "claude_provider"]
    execution = tmp_path / "execution.json"
    execution.write_text(json.dumps(record))
    output = tmp_path / "github_output"
    output.write_text("")
    script = tmp_path / "classify.sh"
    script.write_text(step["run"])
    env = {
        "PATH": "/usr/bin:/bin",
        "CLAUDE_EXECUTION_FILE": str(execution),
        "CLAUDE_OUTCOME": outcome,
        "CLAUDE_CONCLUSION": conclusion,
        "GITHUB_OUTPUT": str(output),
    }
    result = subprocess.run(
        ["bash", "--noprofile", "--norc", "-eo", "pipefail", str(script)],
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return output.read_text().splitlines()


@pytest.mark.skipif(shutil.which("jq") is None, reason="the step runs jq")
def test_model_controlled_values_cannot_inject_github_output_lines(tmp_path):
    injected = "end\nkind=healthy\nfallback_allowed=true"
    lines = _classify(
        tmp_path,
        {
            "type": "result",
            "api_error_status": 401,
            "terminal_reason": injected,
            "error": "x\rkind=healthy",
            "subtype": "error kind=healthy",
            "num_turns": 3,
            "modelUsage": {"m": {}},
        },
    )
    keys = [line.split("=", 1)[0] for line in lines]
    assert keys == [
        "kind",
        "fallback_allowed",
        "terminal_reason",
        "error_type",
        "result_error",
        "api_error_status",
        "is_error",
        "num_turns",
        "model_usage_count",
    ]
    values = dict(line.split("=", 1) for line in lines)
    assert values["kind"] == "security"
    assert values["fallback_allowed"] == "false"
    assert values["terminal_reason"] == "invalid"
    assert values["result_error"] == "invalid"
    for line in lines:
        assert re.fullmatch(r"[a-z_]+=[A-Za-z0-9_.:/-]+", line), line


@pytest.mark.skipif(shutil.which("jq") is None, reason="the step runs jq")
def test_ordinary_classifier_values_pass_through_unchanged(tmp_path):
    lines = _classify(
        tmp_path,
        {
            "type": "result",
            "subtype": "error_max_turns",
            "terminal_reason": "max_turns",
            "num_turns": 12,
            "modelUsage": {"m": {}},
        },
    )
    values = dict(line.split("=", 1) for line in lines)
    assert values["kind"] == "max_turns"
    assert values["terminal_reason"] == "max_turns"
    assert values["num_turns"] == "12"
    assert values["model_usage_count"] == "1"


def test_the_model_job_saves_no_dependency_cache():
    for step in _steps("model"):
        if str(step.get("uses", "")).startswith("actions/setup-python@"):
            assert "cache" not in (step.get("with") or {})
        assert not str(step.get("uses", "")).startswith("actions/cache")


def test_the_publish_job_runs_only_trusted_code_from_a_fresh_checkout():
    publish = JOBS["publish"]
    (checkout,) = [
        s
        for s in publish["steps"]
        if str(s.get("uses", "")).startswith("actions/checkout@")
    ]
    assert checkout["with"]["ref"] == "${{ needs.execute.outputs.trusted_sha }}"
    assert checkout["with"]["persist-credentials"] is False
    (download,) = [
        s
        for s in publish["steps"]
        if str(s.get("uses", "")).startswith("actions/download-artifact@")
    ]
    # Model output lands outside the workspace, as data.
    assert download["with"]["path"] == "${{ runner.temp }}/model-output"
    for step in publish["steps"]:
        run = str(step.get("run") or "")
        # Nothing model-authored is installed, tested or executed here.
        assert "pip install" not in run
        assert "pytest" not in run
        assert not re.search(
            r"(python3?|bash|sh|source|\.)\s+\"?\$RUNNER_TEMP/model-output", run
        )
        assert "publish-worktree/" not in run
    (publish_step,) = [s for s in publish["steps"] if s.get("id") == "publish"]
    assert "scripts/oc_patch_publish.py" in publish_step["run"]
    assert '--worktree "$RUNNER_TEMP/publish-worktree"' in publish_step["run"]
    assert (
        publish_step["env"]["ALLOWED_PATHS"]
        == "${{ needs.execute.outputs.allowed_paths }}"
    )


def test_the_write_scope_comes_from_the_admitting_job_not_the_model():
    outputs = JOBS["execute"]["outputs"]
    assert outputs["allowed_paths"] == "${{ steps.issue_auth.outputs.allowed_paths }}"
    assert "steps.governor.outputs.authorized == 'true'" in outputs["paid"]
    for name in ("trusted_sha", "allowed_paths", "paid"):
        assert "needs.model" not in outputs[name]


def test_only_the_publish_job_can_write_code_or_pull_requests():
    for name, job in JOBS.items():
        perms = job["permissions"]
        if name == "publish":
            assert perms["contents"] == perms["pull-requests"] == "write"
        else:
            assert perms.get("contents") == "read", name
            assert "pull-requests" not in perms, name
            assert "id-token" not in perms, name


def test_publish_always_settles_once_the_model_job_was_admitted():
    publish = JOBS["publish"]
    assert publish["if"].startswith("always()")
    assert "needs.execute.outputs.paid == 'true'" in publish["if"]
    (cost,) = [
        s
        for s in publish["steps"]
        if s.get("name") == "Record provider cost reservation and actual cost"
    ]
    # A lost model runner still records the reservation.
    assert "needs.model.result != 'skipped'" in cost["if"]
    assert any(s.get("id") == "settlement" for s in publish["steps"])
