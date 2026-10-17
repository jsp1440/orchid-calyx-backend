"""Model-driven worker subprocesses never inherit a credential.

The paid worker runs pytest on tests the model wrote. With GH_TOKEN (issues:
write) in their environment, model-written code could open an issue shaped like
engine discovery -- which the owner's discovery grant would then pay for -- or
delete the admission receipts the daily cap counts. These tests run real child
processes and assert what they can see.
"""

from __future__ import annotations

import inspect
import json
import os
import subprocess
import sys

import pytest
import yaml

from scripts import swarm_anthropic_direct as direct

SECRETS = {
    "GH_TOKEN": "ghs_worker",
    "GITHUB_TOKEN": "ghs_actions",
    "ANTHROPIC_API_KEY": "sk-ant",
    "OPENAI_API_KEY": "sk-openai",
    "GEMINI_API_KEY": "gem",
    "GOOGLE_API_KEY": "goog",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN": "oidc",
    "ACTIONS_ID_TOKEN_REQUEST_URL": "https://oidc.example",
    "ACTIONS_RUNTIME_TOKEN": "runtime",
    "ACTIONS_CACHE_URL": "https://cache.example",
    "DATABASE_URL": "postgresql://u:p@h/db",
    "NEON_PROJECT_SECRET": "s",
    "SOME_SERVICE_PASSWORD": "p",
    "custom_private_key": "k",
}
KEPT = {"PATH", "HOME", "PYTHONPATH", "LANG", "GITHUB_REPOSITORY", "RUNNER_TEMP"}
WORKFLOW = ".github/workflows/orchid-completion-lane.yml"


@pytest.fixture
def environment(monkeypatch):
    for name, value in SECRETS.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("PYTHONPATH", "/opt/example")
    monkeypatch.setenv("LANG", "C.UTF-8")
    monkeypatch.setenv("GITHUB_REPOSITORY", "jsp1440/orchid-calyx-backend")
    monkeypatch.setenv("RUNNER_TEMP", "/tmp/runner")
    monkeypatch.setenv("HOME", os.environ.get("HOME", "/root"))


def _child_env(cmd_prefix):
    probe = "import json, os; print(json.dumps(dict(os.environ)))"
    result = direct._run([*cmd_prefix, "-c", probe], timeout=60)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_a_model_driven_child_sees_no_credential(environment):
    seen = _child_env([sys.executable])
    assert not set(SECRETS) & set(seen)
    assert KEPT <= set(seen)
    assert seen["PYTHONPATH"] == "/opt/example"
    leaked = [
        name
        for name in seen
        if direct._secret_env_name(name) and name not in direct.GIT_SAFETY
    ]
    assert not leaked


def test_a_child_cannot_read_a_secret_by_any_name(environment):
    seen = _child_env([sys.executable])
    values = set(SECRETS.values())
    assert not values & set(seen.values())


def test_the_pytest_check_runs_with_the_scrubbed_environment(environment, monkeypatch):
    captured = {}

    def fake(cmd, **kwargs):
        captured.update(cmd=cmd, env=kwargs.get("env"))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(direct.subprocess, "run", fake)
    direct._tool_run_check({"name": "pytest", "target": "tests/test_x.py"})
    assert captured["cmd"][1:4] == ["-m", "pytest", "-q"]
    assert captured["env"] is not None
    assert not set(SECRETS) & set(captured["env"])


@pytest.mark.parametrize(
    "cmd",
    [
        ["git", "status", "--short"],
        ["git", "diff", "--"],
        ["git", "add", "--", "x"],
        ["git", "commit", "-m", "x"],
        [sys.executable, "-m", "ruff", "check", "."],
        [sys.executable, "-m", "pytest", "-q"],
        ["python3", "-c", "print(1)"],
    ],
)
def test_only_remote_steps_get_credentials(cmd):
    assert direct._needs_credentials(cmd) is False


@pytest.mark.parametrize(
    "cmd",
    [
        ["gh", "pr", "create"],
        ["/usr/bin/gh", "api", "x"],
        ["git", "push", "-u", "origin", "b"],
        ["git", "fetch", "origin", "main"],
    ],
)
def test_the_executors_own_remote_steps_keep_credentials(cmd, environment, monkeypatch):
    captured = {}

    def fake(cmd, **kwargs):
        captured["env"] = kwargs.get("env")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(direct.subprocess, "run", fake)
    direct._run(cmd)
    assert captured["env"]["GH_TOKEN"] == "ghs_worker"
    assert captured["env"]["GIT_CONFIG_KEY_0"] == "core.hooksPath"


def test_git_hooks_and_fsmonitor_are_disabled_for_every_call(environment):
    seen = _child_env([sys.executable])
    pairs = {
        seen[f"GIT_CONFIG_KEY_{i}"]: seen[f"GIT_CONFIG_VALUE_{i}"]
        for i in range(int(seen["GIT_CONFIG_COUNT"]))
    }
    assert pairs == {"core.hooksPath": "/dev/null", "core.fsmonitor": "false"}


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="Linux prctl")
def test_a_hardened_executor_hides_its_environment_from_children():
    """A child at the same uid cannot read /proc/<parent>/environ once hardened.

    Root bypasses the check, so under root the probe runs as nobody.
    """
    child = (
        "import os\n"
        "try:\n"
        "    open(f'/proc/{os.getppid()}/environ', 'rb').read()\n"
        "    print('READ')\n"
        "except PermissionError:\n"
        "    print('DENIED')\n"
    )
    results = {}
    for harden in (False, True):
        code = (
            "import subprocess, sys\n"
            + inspect.getsource(direct.harden_process)
            + ("\nassert harden_process()\n" if harden else "\n")
            + f"print(subprocess.run([sys.executable, '-c', {child!r}],"
            " capture_output=True, text=True).stdout.strip())\n"
        )

        def demote():
            os.setgid(65534)
            os.setuid(65534)

        run = subprocess.run(
            ["/usr/bin/env", "python3", "-I", "-c", code],
            capture_output=True,
            text=True,
            cwd="/",
            env={"PATH": os.environ.get("PATH", ""), "GH_TOKEN": "ghs_worker"},
            preexec_fn=demote if os.geteuid() == 0 else None,
            timeout=60,
            check=False,
        )
        assert run.returncode == 0, run.stderr
        results[harden] = run.stdout.strip()
    # The unhardened control proves the probe can read when nothing stops it.
    assert results == {False: "READ", True: "DENIED"}


def _job():
    with open(WORKFLOW, encoding="utf-8") as handle:
        workflow = yaml.safe_load(handle)
    (job,) = workflow["jobs"].values()
    return job


def test_the_lane_checkout_persists_no_token():
    steps = _job()["steps"]
    checkout = steps[0]
    assert checkout["uses"].startswith("actions/checkout@")
    assert checkout["with"]["persist-credentials"] is False
    assert steps[1]["run"].strip() == "gh auth setup-git"


def test_the_worker_replaces_its_shell_and_fallback_clis_drop_tokens():
    steps = _job()["steps"]
    (worker,) = [s for s in steps if s.get("id") == "claude"]
    assert "exec python3 scripts/swarm_anthropic_direct.py" in worker["run"]
    for step in steps:
        run = str(step.get("run") or "")
        if "npx -y @" in run and ("gemini-cli" in run or "codex" in run):
            for line in run.splitlines():
                if "env -u GH_TOKEN" in line:
                    for name in (
                        "GITHUB_TOKEN",
                        "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
                        "ACTIONS_ID_TOKEN_REQUEST_URL",
                    ):
                        assert f"-u {name}" in line
