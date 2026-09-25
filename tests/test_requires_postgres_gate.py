"""PostgreSQL-backed suites skip with a precise reason instead of erroring.

``tests/conftest.py`` registers ``requires_postgres`` and gates marked items with
one real connection probe. A TCP probe is not an honest gate: a developer box or
CI sandbox can have a PostgreSQL listening on localhost:5432 that does not know
the placeholder ``test`` role, in which case a socket check says "reachable"
and every gated test then errors inside fixture setup with a raw driver error.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from conftest import _redact_dsn, postgres_unavailable_reason

UNREACHABLE = "postgresql://nobody:hunter2@127.0.0.1:1/none"
GATED_FILES = (
    "tests/test_build_067_pg_writer.py",
    "tests/test_build_086c_final_validation.py",
    "tests/test_build_086d_review_readiness.py",
    "tests/test_occurrence_reconciliation_runs.py",
    "tests/test_occurrence_taxonomy_guard.py",
    "tests/test_run_live_dispatch_canary.py",
)


def test_probe_reports_the_driver_reason_and_redacts_the_password():
    reason = postgres_unavailable_reason(UNREACHABLE)
    assert reason is not None
    assert reason.startswith(
        "PostgreSQL not usable at postgresql://nobody:***@127.0.0.1:1/none"
    )
    assert "hunter2" not in reason
    assert "OperationalError" in reason


def test_probe_fails_closed_without_a_dsn():
    assert postgres_unavailable_reason(None) is not None
    assert postgres_unavailable_reason("") is not None


def test_redaction_keeps_the_user_and_host():
    assert (
        _redact_dsn("postgresql://u:p%40ss@db.example:5432/x")
        == "postgresql://u:***@db.example:5432/x"
    )
    assert _redact_dsn("postgresql://db.example/x") == "postgresql://db.example/x"


@pytest.mark.parametrize("path", GATED_FILES)
def test_gated_suite_skips_cleanly_when_postgres_is_unusable(path: str):
    # The off-runner skip path. The inner run must not inherit the runner's
    # CI=true, which (by design, see the next test) turns the skip into a failure.
    env = _unreachable_env(require_postgres=False)
    proc = _run_gated(path, env)
    output = proc.stdout + proc.stderr
    assert proc.returncode == 0, output
    assert " error" not in output.split("\n")[-2]
    assert "FAILED" not in output and "ERROR" not in output
    assert "PostgreSQL not usable at postgresql://nobody:***@127.0.0.1:1/none" in output
    assert "hunter2" not in output


def test_gated_suite_fails_rather_than_skips_when_postgres_is_required():
    proc = _run_gated(GATED_FILES[0], _unreachable_env(require_postgres=True))
    output = proc.stdout + proc.stderr
    assert proc.returncode != 0, output
    assert "PostgreSQL is required in this environment but unusable" in output
    assert "hunter2" not in output


def _unreachable_env(*, require_postgres: bool) -> dict[str, str]:
    env = dict(os.environ, TEST_DATABASE_URL=UNREACHABLE, DATABASE_URL=UNREACHABLE)
    env.pop("CI", None)
    env.pop("OC_REQUIRE_POSTGRES", None)
    if require_postgres:
        env["OC_REQUIRE_POSTGRES"] = "1"
    return env


def _run_gated(path: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:randomly", "-rs", path],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_ci_turns_an_unusable_database_into_a_failure_not_a_skip(monkeypatch):
    """A skip in CI would let a broken runner report the Postgres suites green."""
    from tests import conftest

    monkeypatch.delenv("OC_REQUIRE_POSTGRES", raising=False)
    monkeypatch.setenv("CI", "true")
    assert conftest._postgres_required_here() is True
    monkeypatch.setenv("CI", "false")
    assert conftest._postgres_required_here() is False
    monkeypatch.setenv("OC_REQUIRE_POSTGRES", "1")
    assert conftest._postgres_required_here() is True
