"""The prepared Render acceptance cannot reach production or start half-configured."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
START = REPO_ROOT / "scripts" / "oc_render_autonomy_acceptance_start.sh"
BLUEPRINT = REPO_ROOT / "deploy" / "render" / "autonomy-acceptance.blueprint.yaml"

COMPLETE = {
    "DATABASE_URL": "postgresql://acceptance@127.0.0.1:1/never_used",
    "CALYX_API_KEY": "acceptance-only",
    "OC_BRAIN_READ_TOKEN": "not-a-real-token",
    "OC_BRAIN_REF": "0" * 40,
    "CALYX_ACCEPTANCE_SOURCE_BRANCH": "claude/sharp-pasteur-e6c4r1-traitbank",
}


def _run(env: dict[str, str], tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(START)],
        cwd=REPO_ROOT,
        env={"PATH": os.environ["PATH"], "TMPDIR": str(tmp_path), **env},
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize("missing", sorted(COMPLETE))
def test_start_refuses_when_a_required_setting_is_missing(missing, tmp_path):
    env = {k: v for k, v in COMPLETE.items() if k != missing}
    env["CALYX_ACCEPTANCE_DATABASE_CONFIRMED"] = "non-production"
    result = _run(env, tmp_path)
    assert result.returncode != 0
    assert missing in result.stderr
    assert list(tmp_path.iterdir()) == []  # nothing cloned, fetched or started


@pytest.mark.parametrize(
    "confirmation",
    [None, "", "production", "yes", "non-production:", "production:neondb"],
)
def test_start_refuses_an_unconfirmed_database(confirmation, tmp_path):
    env = dict(COMPLETE)
    if confirmation is not None:
        env["CALYX_ACCEPTANCE_DATABASE_CONFIRMED"] = confirmation
    result = _run(env, tmp_path)
    assert result.returncode == 0
    assert '"zero_reason": "configuration_unavailable"' in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_pinned_database_that_cannot_be_read_never_starts(tmp_path):
    env = dict(COMPLETE)
    env["CALYX_ACCEPTANCE_DATABASE_CONFIRMED"] = "non-production:autonomy_midrun"
    result = _run(env, tmp_path)
    assert result.returncode == 1
    assert "ACCEPTANCE_DATABASE_UNREACHABLE" in result.stdout
    assert list(tmp_path.iterdir()) == []


@pytest.mark.requires_postgres("TEST_DATABASE_URL")
def test_pinned_database_name_must_match_the_real_connection(tmp_path):
    """A worker pointed at the wrong database (e.g. the preserved evidence
    database) refuses before the API, the clone or the worker can run."""
    env = dict(COMPLETE, DATABASE_URL=os.environ["TEST_DATABASE_URL"])
    env["CALYX_ACCEPTANCE_DATABASE_CONFIRMED"] = "non-production:autonomy_midrun"
    result = _run(env, tmp_path)
    assert result.returncode == 0
    assert "ACCEPTANCE_DATABASE_MISMATCH" in result.stdout
    assert "expected autonomy_midrun" in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_blueprint_is_isolated_cheap_and_never_auto_deployed():
    assert not (REPO_ROOT / "render.yaml").exists()  # Render syncs only a root file
    (service,) = yaml.safe_load(BLUEPRINT.read_text(encoding="utf-8"))["services"]
    assert service["type"] == "worker"
    assert service["name"] != "orchid-calyx-backend"  # not the production service
    assert service["plan"] == "starter"
    assert service["autoDeploy"] is False
    assert (
        service["startCommand"] == "bash scripts/oc_render_autonomy_acceptance_start.sh"
    )
    env = {item["key"]: item for item in service["envVars"]}
    # Secrets are entered by the owner in Render, never committed.
    assert env["DATABASE_URL"] == {"key": "DATABASE_URL", "sync": False}
    assert env["OC_BRAIN_READ_TOKEN"] == {"key": "OC_BRAIN_READ_TOKEN", "sync": False}
    assert env["CALYX_API_KEY"].get("generateValue") is True
    # Bound to the dedicated loop database, so a stale DATABASE_URL refuses to start.
    assert (
        env["CALYX_ACCEPTANCE_DATABASE_CONFIRMED"]["value"]
        == "non-production:autonomy_loop"
    )
    assert env["CALYX_ACCEPTANCE_WORK_MODE"]["value"] == "loop"
    assert env["NO_API_MODE"]["value"] == "true"
    assert env["OC_GOVERNOR_PAID_EXECUTION_ENABLED"]["value"] == "false"
    assert env["PROVIDER_LAUNCH_AUTHORIZED"]["value"] == "false"
    assert len(env["OC_BRAIN_REF"]["value"]) == 40  # a pinned commit, not a branch
    # A Blueprint sync must deploy the same Brain revision CI accepted.
    workflow = (
        REPO_ROOT / ".github" / "workflows" / "brain-calyx-autonomy-acceptance.yml"
    )
    pinned = yaml.safe_load(workflow.read_text(encoding="utf-8"))["env"]["OC_BRAIN_REF"]
    assert env["OC_BRAIN_REF"]["value"] == pinned


@pytest.mark.requires_postgres("TEST_DATABASE_URL")
def test_pinned_database_name_that_matches_is_confirmed(tmp_path):
    from sqlalchemy import create_engine, text

    dsn = os.environ["TEST_DATABASE_URL"]
    engine = create_engine(dsn)
    with engine.connect() as connection:
        name = connection.execute(text("SELECT current_database()")).scalar_one()
    engine.dispose()
    # A branch that does not exist stops the script right after the guard.
    env = dict(COMPLETE, DATABASE_URL=dsn)
    env["CALYX_ACCEPTANCE_SOURCE_BRANCH"] = "no-such-branch-for-guard-test"
    env["CALYX_ACCEPTANCE_DATABASE_CONFIRMED"] = f"non-production:{name}"
    result = _run(env, tmp_path)
    assert f'{{"acceptance_database": "{name}", "confirmed": true}}' in result.stdout
    assert "ACCEPTANCE_DATABASE_MISMATCH" not in result.stdout


def test_unknown_work_mode_is_refused_before_anything_runs(tmp_path):
    env = dict(COMPLETE, CALYX_ACCEPTANCE_DATABASE_CONFIRMED="non-production")
    env["CALYX_ACCEPTANCE_WORK_MODE"] = "everything"
    result = _run(env, tmp_path)
    assert result.returncode == 0
    assert "CALYX_ACCEPTANCE_WORK_MODE must be manifest or loop" in result.stdout
    assert list(tmp_path.iterdir()) == []


# --- G3: the long-running worker's isolated-database confirmation -----------


@pytest.mark.parametrize(
    "confirmation",
    [
        "autonomy-isolated",  # the database name is mandatory
        "autonomy-isolated:",
        "autonomy-isolated:neondb",  # the production application database
        "autonomy-isolated:postgres",
        "autonomy-isolated:autonomy",
        "autonomy-isolated:Autonomy_prod",
        "autonomy-isolated:autonomy-prod",
        "autonomy-isolated:autonomy_prod;true",
        "autonomy-isolated:autonomy_prod ",
        "autonomy-isolated:prod_autonomy_x",
    ],
)
def test_isolated_confirmation_refuses_anything_but_a_dedicated_name(
    confirmation, tmp_path
):
    env = dict(COMPLETE, CALYX_ACCEPTANCE_DATABASE_CONFIRMED=confirmation)
    result = _run(env, tmp_path)
    assert result.returncode == 0
    assert '"zero_reason": "configuration_unavailable"' in result.stdout
    # Refused on the name alone: the database is never contacted.
    assert "ACCEPTANCE_DATABASE_UNREACHABLE" not in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_isolated_confirmation_still_checks_the_real_connection(tmp_path):
    # A well-formed name is not trusted: the live connection must be read first.
    env = dict(
        COMPLETE, CALYX_ACCEPTANCE_DATABASE_CONFIRMED="autonomy-isolated:autonomy_prod"
    )
    result = _run(env, tmp_path)
    assert result.returncode == 1
    assert "ACCEPTANCE_DATABASE_UNREACHABLE" in result.stdout
    assert list(tmp_path.iterdir()) == []


@pytest.mark.requires_postgres("TEST_DATABASE_URL")
def test_isolated_confirmation_refuses_a_different_database(tmp_path):
    env = dict(COMPLETE, DATABASE_URL=os.environ["TEST_DATABASE_URL"])
    env["CALYX_ACCEPTANCE_DATABASE_CONFIRMED"] = "autonomy-isolated:autonomy_prod"
    result = _run(env, tmp_path)
    assert result.returncode == 0
    assert "ACCEPTANCE_DATABASE_MISMATCH" in result.stdout
    assert "expected autonomy_prod" in result.stdout
    assert list(tmp_path.iterdir()) == []


@pytest.mark.requires_postgres("TEST_DATABASE_URL")
def test_isolated_confirmation_accepts_its_own_autonomy_database(tmp_path):
    import uuid

    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import make_url

    name = f"autonomy_g3_{uuid.uuid4().hex[:12]}"
    admin = create_engine(os.environ["TEST_DATABASE_URL"], isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        dsn = make_url(os.environ["TEST_DATABASE_URL"]).set(database=name)
        env = dict(COMPLETE, DATABASE_URL=dsn.render_as_string(hide_password=False))
        # A branch that does not exist stops the script right after the guard.
        env["CALYX_ACCEPTANCE_SOURCE_BRANCH"] = "no-such-branch-for-guard-test"
        env["CALYX_ACCEPTANCE_DATABASE_CONFIRMED"] = f"autonomy-isolated:{name}"
        result = _run(env, tmp_path)
        assert (
            f'{{"acceptance_database": "{name}", "confirmed": true}}' in result.stdout
        )
        assert "ACCEPTANCE_DATABASE_MISMATCH" not in result.stdout
    finally:
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


# --- G5: the long-running worker's prepared Blueprint ------------------------

PRODUCTION_BLUEPRINT = (
    REPO_ROOT / "deploy" / "render" / "autonomy-production.blueprint.yaml"
)
VERIFY_WORKFLOW = (
    REPO_ROOT / ".github" / "workflows" / "render-autonomy-acceptance-verify.yml"
)


def _service(path: Path) -> dict:
    (service,) = yaml.safe_load(path.read_text(encoding="utf-8"))["services"]
    return service


def test_production_blueprint_is_isolated_gated_and_never_auto_deployed():
    service = _service(PRODUCTION_BLUEPRINT)
    acceptance = _service(BLUEPRINT)
    assert service["type"] == "worker"
    assert service["name"] not in {"orchid-calyx-backend", acceptance["name"]}
    assert service["plan"] == "starter"
    assert service["branch"] == "main"
    assert service["autoDeploy"] is False
    assert service["startCommand"] == acceptance["startCommand"]
    env = {item["key"]: item for item in service["envVars"]}
    # Secrets are entered by the owner in Render, never committed.
    assert env["DATABASE_URL"] == {"key": "DATABASE_URL", "sync": False}
    assert env["OC_BRAIN_READ_TOKEN"] == {"key": "OC_BRAIN_READ_TOKEN", "sync": False}
    assert env["CALYX_API_KEY"].get("generateValue") is True
    assert (
        env["CALYX_ACCEPTANCE_DATABASE_CONFIRMED"]["value"]
        == "autonomy-isolated:autonomy_prod"
    )
    assert env["CALYX_ACCEPTANCE_SOURCE_BRANCH"]["value"] == "main"
    assert env["CALYX_ACCEPTANCE_WORK_MODE"]["value"] == "loop"
    assert (
        env["CALYX_PROGRAM_AUTONOMY_WORKER_ID"]["value"]
        != {i["key"]: i for i in acceptance["envVars"]}[
            "CALYX_PROGRAM_AUTONOMY_WORKER_ID"
        ]["value"]
    )
    # Paid execution stays gated three ways.
    assert env["NO_API_MODE"]["value"] == "true"
    assert env["OC_GOVERNOR_PAID_EXECUTION_ENABLED"]["value"] == "false"
    assert env["PROVIDER_LAUNCH_AUTHORIZED"]["value"] == "false"
    # Same Brain revision CI accepted.
    workflow = (
        REPO_ROOT / ".github" / "workflows" / "brain-calyx-autonomy-acceptance.yml"
    )
    pinned = yaml.safe_load(workflow.read_text(encoding="utf-8"))["env"]["OC_BRAIN_REF"]
    assert env["OC_BRAIN_REF"]["value"] == pinned


def test_production_blueprint_confirmation_passes_the_name_rule(tmp_path):
    # The committed value clears the autonomy-isolated name rule and so reaches
    # the live current_database() check (unreachable here), not a refusal.
    env = {i["key"]: i for i in _service(PRODUCTION_BLUEPRINT)["envVars"]}
    run_env = dict(COMPLETE)
    run_env["CALYX_ACCEPTANCE_DATABASE_CONFIRMED"] = env[
        "CALYX_ACCEPTANCE_DATABASE_CONFIRMED"
    ]["value"]
    result = _run(run_env, tmp_path)
    assert result.returncode == 1
    assert "ACCEPTANCE_DATABASE_UNREACHABLE" in result.stdout
    assert "ISOLATED_DATABASE_NAME_REFUSED" not in result.stdout
    assert list(tmp_path.iterdir()) == []


def test_production_verification_uses_only_its_own_read_only_secret():
    workflow = yaml.safe_load(VERIFY_WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["verify"]
    assert "render-autonomy-verify-production" in job["if"]
    assert job["env"]["PRODUCTION_DSN"] == (
        "${{ secrets.OC_AUTONOMY_PROD_VERIFY_DATABASE_URL }}"
    )
    (step,) = [
        s for s in job["steps"] if s.get("name", "").startswith("Verify the hosted")
    ]
    branch = step["run"].split('if [ "$PRODUCTION" = "true" ]; then', 1)[1]
    branch = branch.split("elif", 1)[0]
    assert 'dsn="$PRODUCTION_DSN"' in branch
    assert "FIRST_RUN_DSN" not in branch  # never the acceptance credential
    assert "--require-loop --database autonomy_prod" in branch
