"""The completion lane's job boundary: the model never shares a job with a write token.

Review of #1973 showed that model-written code running in the job that held
GH_TOKEN could rewrite git configuration, shadow binaries or poison the tree
later trusted steps ran from, and so reach the credential however its
environment was scrubbed. The lane is therefore three jobs. These tests pin the
boundary as a contract on the workflow itself.
"""

from __future__ import annotations

import re
from pathlib import Path

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


def test_model_output_is_collected_by_digest_after_killing_model_processes():
    (collect,) = [
        s
        for s in _steps("model")
        if s.get("name") == "Collect model output for the trusted publisher"
    ]
    run = collect["run"]
    assert run.index('sudo pkill -KILL -u "$MODEL_USER"') < run.index(
        "oc_patch_publish.py collect"
    )
    assert "python3 -I scripts/oc_patch_publish.py collect" in run


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
