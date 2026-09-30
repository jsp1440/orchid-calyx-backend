"""Runs the timer-driven program-autonomy proof against a disposable PostgreSQL.

The PostgreSQL test runs ``scripts/oc_program_autonomy_timer_proof.py`` as a
subprocess. That script spawns real ``run_forever`` supervisor processes, and
each one is paced only by its own sleep timer. The test then checks the JSON
evidence the script writes. Off-runner it skips when no usable
``TEST_DATABASE_URL`` is configured. In CI (``CI=true``) the shared
``requires_postgres`` gate turns an unusable database into a failure instead.

The small tests at the bottom need no database. They pin the harness's own
safety rails: the network guard, the loopback-only DSN rule and the child
token.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "oc_program_autonomy_timer_proof.py"

REQUIRED_ASSERTIONS = {
    "victim_killed_mid_lease",
    "duplicate_lease_attempts_refused",
    "dead_worker_token_fenced_after_recovery",
    "zero_duplicate_executions",
    "durable_outcomes_match_ledger",
    "dead_worker_job_recovered",
    "provider_failure_does_not_stall_other_jobs",
    "dead_letter_after_max_attempts",
    "dead_letter_dependant_never_executed",
    "mid_run_enqueue_completed_autonomously",
    "durable_state_changed_as_expected",
    "no_network_calls",
    "harness_never_invoked_the_cycle",
}


@pytest.mark.requires_postgres("TEST_DATABASE_URL")
def test_supervisors_complete_ten_consecutive_timer_cycles(tmp_path: Path) -> None:
    output = Path(
        os.environ.get("OC_AUTPROOF_EVIDENCE")
        or tmp_path / "program-autonomy-timer-proof.json"
    )
    env = {key: value for key, value in os.environ.items() if key != "PGHOST"}
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--dsn",
            os.environ["TEST_DATABASE_URL"],
            "--output",
            str(output),
            "--supervisors",
            "2",
            "--target-cycles",
            "10",
            "--poll-seconds",
            "15",
            "--lease-seconds",
            "60",
            "--max-jobs-per-cycle",
            "2",
            "--deadline-seconds",
            "600",
        ],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    assert output.exists(), completed.stderr[-4000:]
    report = json.loads(output.read_text(encoding="utf-8"))
    failed = [item for item in report.get("assertions", []) if not item["passed"]]
    assert completed.returncode == 0 and report["status"] == "PASS", json.dumps(
        {
            "failed": failed,
            "error": report.get("error"),
            "stdout": completed.stdout[-2000:],
        },
        indent=2,
        default=str,
    )

    names = {item["name"] for item in report["assertions"]}
    assert REQUIRED_ASSERTIONS <= names
    supervisors = report["supervisors"]
    assert len(supervisors) >= 2
    for supervisor in supervisors:
        assert supervisor["consecutive_cycles"] >= 10
        assert supervisor["records_not_executed"] == 0
        assert (
            supervisor["gap_seconds_min"] >= report["parameters"]["poll_seconds"] - 1.0
        )
    assert report["victim"]["returncode"] == -9
    assert report["network"]["blocked_attempts"] == 0
    assert report["jobs"]["dead-always-fails"]["outcome"] == "DEAD_LETTER"
    assert report["jobs"]["slow-recovered"]["attempt_count"] == 2


# ---------------------------------------------------------------------------
# Harness safety rails (no database needed)
# ---------------------------------------------------------------------------


def _load_script():
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "oc_program_autonomy_timer_proof", SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    # dataclasses resolves string annotations through sys.modules.
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


def test_socket_guard_blocks_everything_but_the_database_endpoint(
    tmp_path: Path,
) -> None:
    code = f"""
import json, socket, sys
sys.path.insert(0, {str(SCRIPT.parent)!r})
import oc_program_autonomy_timer_proof as proof
netlog = {str(tmp_path / "net.jsonl")!r}
proof._install_socket_guard("127.0.0.1:1", netlog)
assert proof._guard_selftest(netlog) is True
outcomes = {{}}
for label, target in (("external", ("192.0.2.10", 443)), ("wrong_port", ("127.0.0.1", 2))):
    try:
        socket.create_connection(target, timeout=0.2)
        outcomes[label] = "connected"
    except PermissionError as exc:
        outcomes[label] = "blocked" if "OC_AUTPROOF_NETWORK_BLOCKED" in str(exc) else str(exc)
    except OSError as exc:
        outcomes[label] = "oserror"
try:
    socket.getaddrinfo("api.anthropic.com", 443)
    outcomes["dns"] = "resolved"
except PermissionError:
    outcomes["dns"] = "blocked"
try:
    socket.create_connection(("127.0.0.1", 1), timeout=0.2)
    outcomes["database_endpoint"] = "connected"
except PermissionError:
    outcomes["database_endpoint"] = "blocked"
except OSError:
    outcomes["database_endpoint"] = "allowed_refused_by_os"
print(json.dumps(outcomes))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )
    outcomes = json.loads(result.stdout.strip().splitlines()[-1])
    assert outcomes == {
        "external": "blocked",
        "wrong_port": "blocked",
        "dns": "blocked",
        "database_endpoint": "allowed_refused_by_os",
    }
    entries = [
        json.loads(line)
        for line in (tmp_path / "net.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    kinds = [entry["kind"] for entry in entries]
    # The self-test is recorded as such and is never counted as a real call.
    assert kinds.count("selftest") == 1
    assert "selftest_connect_blocked" in kinds
    assert sum(1 for kind in kinds if not kind.startswith("selftest")) == 3


def test_harness_refuses_a_non_loopback_database() -> None:
    proof = _load_script()
    with pytest.raises(SystemExit, match="non-loopback"):
        proof._endpoint("postgresql://user:secret@db.example.org:5432/prod")
    assert proof._endpoint("postgresql://u:p@localhost:55432/db") == "localhost:55432"
    assert proof._endpoint("postgresql+psycopg2://u@127.0.0.1/db") == "127.0.0.1:5432"


def test_proof_executor_hook_does_not_arm_without_the_harness_token() -> None:
    env = {
        key: value
        for key, value in os.environ.items()
        if key != "OC_AUTPROOF_CHILD_TOKEN"
    }
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--supervisor-child"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 2
    assert "requires the harness token" in result.stderr


def test_search_path_is_scoped_and_password_redacted() -> None:
    proof = _load_script()
    scoped = proof._with_search_path(
        "postgresql://u:p@localhost:5432/db", "oc_autproof_abc"
    )
    assert scoped.endswith("?options=-csearch_path%3Doc_autproof_abc")
    assert (
        proof._redact("postgresql://u:hunter2@localhost/db")
        == "postgresql://u:***@localhost/db"
    )


def test_socket_module_is_untouched_in_the_test_process() -> None:
    # Loading the script must not arm the guard in an importing process.
    _load_script()
    assert socket.socket.connect.__qualname__ == "socket.connect"
