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
    assert env["CALYX_ACCEPTANCE_DATABASE_CONFIRMED"]["value"] == "non-production"
    assert env["NO_API_MODE"]["value"] == "true"
    assert env["OC_GOVERNOR_PAID_EXECUTION_ENABLED"]["value"] == "false"
    assert env["PROVIDER_LAUNCH_AUTHORIZED"]["value"] == "false"
    assert len(env["OC_BRAIN_REF"]["value"]) == 40  # a pinned commit, not a branch


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
