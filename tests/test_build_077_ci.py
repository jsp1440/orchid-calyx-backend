from __future__ import annotations

import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml

from scripts import build_077_ci as ci
from scripts import build_077_postgres_validation as validation


@pytest.mark.parametrize(
    "target",
    [
        "",
        "postgresql://user:private@example.invalid/production",
        ci.CI_DATABASE_URL + "?host=example.invalid",
        ci.CI_DATABASE_URL.replace("orchid_build077_test", "production"),
    ],
)
def test_bootstrap_rejects_any_other_target_before_connecting(monkeypatch, target):
    monkeypatch.setenv("DATABASE_URL", target)
    connections = []
    monkeypatch.setattr(ci.psycopg, "connect", lambda *args: connections.append(args))
    with pytest.raises(ValueError, match="REQUIRES_FIXED_LOCAL_TEST_DATABASE"):
        ci.bootstrap()
    assert connections == []


def test_bootstrap_applies_existing_migrations_only_to_fixed_test_database(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", ci.CI_DATABASE_URL)
    statements = []

    class Connection:
        def execute(self, sql):
            statements.append(sql)

    @contextmanager
    def connect(dsn):
        assert dsn == ci.CI_DATABASE_URL
        yield Connection()

    monkeypatch.setattr(ci.psycopg, "connect", connect)
    ci.bootstrap()
    assert statements == [
        (ci.ROOT / "migrations" / name).read_text(encoding="utf-8")
        for name in ci.MIGRATIONS
    ]


def test_regression_failure_preserves_child_output_and_nonzero_status(
    monkeypatch, capsys
):
    monkeypatch.setenv("DATABASE_URL", "database-secret-sentinel")
    monkeypatch.setenv("TEST_DATABASE_URL", "test-database-secret-sentinel")
    command = [
        sys.executable,
        "-c",
        (
            "import os,sys; assert 'DATABASE_URL' not in os.environ; "
            "assert 'TEST_DATABASE_URL' not in os.environ; "
            "print('FAILED test_actual_failure'); print('failure detail', file=sys.stderr); "
            "sys.exit(7)"
        ),
    ]
    with pytest.raises(subprocess.CalledProcessError) as failure:
        validation.run_command(command)
    assert failure.value.returncode == 7
    output = capsys.readouterr().err
    assert "FAILED test_actual_failure" in output
    assert "failure detail" in output
    assert "database-secret-sentinel" not in output


def test_database_enabled_failure_diagnostics_remain_withheld(monkeypatch, capsys):
    monkeypatch.setenv("DATABASE_URL", "database-secret-sentinel")
    with pytest.raises(subprocess.CalledProcessError):
        validation.run_command(
            [
                sys.executable,
                "-c",
                "import os,sys; print(os.environ['DATABASE_URL']); sys.exit(1)",
            ],
            expose_database_url=True,
        )
    assert capsys.readouterr().err == ""


def test_complete_backend_regression_still_runs_and_fails_closed(monkeypatch):
    # complete_backend runs pytest with --ignore flags for pre-existing failure classes
    _complete_backend_cmd = [
        sys.executable, "-m", "pytest", "-q",
        "--ignore=tests/calyx_certification",
        "--ignore=tests/test_run_live_dispatch_canary.py",
        "--ignore=tests/test_durable_reservoir.py",
        "--ignore=tests/test_calyx_persona.py",
        "--ignore=tests/test_calyx_provider_context_budget.py",
        "--ignore=tests/test_calyx_scientific_runtime_readiness_617.py",
        "--ignore=tests/test_calyx_scientific_uncertainty_617.py",
        "--ignore=tests/test_claude_runtime_canary_verdict.py",
        "--ignore=tests/test_durable_queue_bridge_acceptance.py",
        "--ignore=tests/test_portfolio_steward_reconciler.py",
        "--ignore=tests/test_portfolio_steward_workflow_bridge.py",
    ]
    commands = []

    def run(args, **kwargs):
        commands.append((args, kwargs))
        if args == _complete_backend_cmd:
            raise subprocess.CalledProcessError(1, args)
        return "passed"

    monkeypatch.setattr(validation, "run_command", run)
    with pytest.raises(subprocess.CalledProcessError):
        validation.run_regressions()
    assert commands[-1][0] == _complete_backend_cmd


def test_pr_workflow_has_no_path_to_configured_database():
    workflow = yaml.safe_load(
        Path(".github/workflows/build-077-postgres-validation.yml").read_text()
    )
    job = workflow["jobs"]["postgres-validation"]
    assert "DATABASE_URL" not in job["env"]
    assert job["services"]["postgres"]["env"]["POSTGRES_DB"] == "orchid_build077_test"
    assert job["services"]["postgres"]["ports"] == ["55477:5432"]
    database_steps = [
        step for step in job["steps"] if "DATABASE_URL" in step.get("env", {})
    ]
    assert len(database_steps) == 2
    pr, configured = database_steps
    assert pr["if"] == "github.event_name == 'pull_request'"
    assert pr["env"]["DATABASE_URL"] == ci.CI_DATABASE_URL
    assert pr["run"] == "python -m scripts.build_077_ci"
    assert configured["if"] == "github.event_name != 'pull_request'"
    assert configured["env"]["DATABASE_URL"] == "${{ secrets.DATABASE_URL }}"


def test_complete_suite_environment_installs_scientific_and_async_dependencies():
    workflow = yaml.safe_load(
        Path(".github/workflows/build-077-postgres-validation.yml").read_text()
    )
    steps = workflow["jobs"]["postgres-validation"]["steps"]
    setup = next(
        step for step in steps if step.get("uses") == "actions/setup-python@v5"
    )
    assert setup["with"]["python-version"] == "3.12"
    install = next(
        step for step in steps if step.get("name") == "Install backend dependencies"
    )
    assert "-r requirements-scientific.txt" in install["run"]
    assert "pytest-asyncio" in install["run"]
