"""Runs the timer-driven program-autonomy proof against a disposable PostgreSQL.

The PostgreSQL tests run ``scripts/oc_program_autonomy_timer_proof.py`` as a
subprocess. That script spawns real ``run_forever`` supervisor processes, and
each one is paced only by its own sleep timer. The tests then check the JSON
evidence the script writes. Off-runner they skip when no usable
``TEST_DATABASE_URL`` is configured. In CI (``CI=true``) the shared
``requires_postgres`` gate turns an unusable database into a failure instead.

The negative controls run the same harness against a scratch copy of the
source with one production guard removed. The proof must then FAIL on the
assertion that guard exists for. If a mutation's target text is not found,
the test fails: it never skips. A control that silently stops mutating is
itself a false pass.

The small tests at the bottom need no database. They pin the harness's own
safety rails.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "oc_program_autonomy_timer_proof.py"
WORKER = Path("app/calyx_orchestrator/program_worker.py")

REQUIRED_FULL_ASSERTIONS = {
    "barrier_released_all_supervisors_together",
    "concurrent_claim_lost_by_all_but_one",
    "race_job_delivered_exactly_once",
    "victim_killed_mid_lease",
    "duplicate_lease_attempts_refused",
    "dead_worker_token_fenced_during_recovery_lease",
    "zero_duplicate_executions",
    "durable_outcomes_match_ledger",
    "dead_worker_job_recovered",
    "provider_failure_does_not_stall_other_jobs",
    "dead_letter_after_max_attempts",
    "mid_run_enqueue_completed_autonomously",
    "durable_state_changed_as_expected",
    "settled_before_deadline",
    "no_network_calls",
    "harness_never_invoked_the_cycle",
}

# The claim UPDATE's compare-and-set guard (PersistentProgramWorker.claim).
CLAIM_GUARD = """            filters = [
                CalyxProgramJob.program_job_id == candidate.program_job_id,
                CalyxProgramJob.status == "queued",
                CalyxProgramJob.outcome.is_(None),
            ]
"""
CLAIM_GUARD_REMOVED = """            filters = [
                CalyxProgramJob.program_job_id == candidate.program_job_id,
            ]
"""
# The lease-token check in PersistentProgramWorker.complete().
COMPLETE_TOKEN_CHECK = """                CalyxProgramJob.lease_token == lease_token,
                CalyxProgramJob.lease_expires_at.is_not(None),
                CalyxProgramJob.lease_expires_at > now,
            )
            .update(
                {CalyxProgramJob.status: "completing"},
"""
COMPLETE_TOKEN_CHECK_REMOVED = COMPLETE_TOKEN_CHECK.split("\n", 1)[1]


def _run_proof(
    script: Path, output: Path, *extra: str
) -> tuple[subprocess.CompletedProcess, dict]:
    env = {key: value for key, value in os.environ.items() if key != "PGHOST"}
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            str(script),
            "--dsn",
            os.environ["TEST_DATABASE_URL"],
            "--output",
            str(output),
            *extra,
        ],
        cwd=script.parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    assert output.exists(), completed.stderr[-4000:]
    return completed, json.loads(output.read_text(encoding="utf-8"))


def _failed(report: dict) -> list[str]:
    return [item["name"] for item in report.get("assertions", []) if not item["passed"]]


def _source_copy(tmp_path: Path, mutation: tuple[str, str] | None) -> Path:
    root = tmp_path / "src"
    ignore = shutil.ignore_patterns("__pycache__", "*.pyc")
    for name in ("app", "runtime"):
        shutil.copytree(REPO_ROOT / name, root / name, ignore=ignore)
    (root / "scripts").mkdir()
    shutil.copy2(SCRIPT, root / "scripts" / SCRIPT.name)
    if mutation is not None:
        target = root / WORKER
        text = target.read_text(encoding="utf-8")
        original, replacement = mutation
        assert text.count(original) == 1, (
            "negative-control target not found exactly once in program_worker.py; "
            "update the mutation rather than letting the control stop mutating"
        )
        target.write_text(text.replace(original, replacement), encoding="utf-8")
    return root / "scripts" / SCRIPT.name


@pytest.mark.requires_postgres("TEST_DATABASE_URL")
def test_supervisors_complete_ten_consecutive_timer_cycles(tmp_path: Path) -> None:
    output = Path(
        os.environ.get("OC_AUTPROOF_EVIDENCE")
        or tmp_path / "program-autonomy-timer-proof.json"
    )
    completed, report = _run_proof(
        SCRIPT,
        output,
        "--supervisors",
        "2",
        "--target-cycles",
        "10",
        "--deadline-seconds",
        "420",
    )
    assert completed.returncode == 0 and report["status"] == "PASS", json.dumps(
        {
            "failed": _failed(report),
            "error": report.get("error"),
            "stdout": completed.stdout[-2000:],
        },
        indent=2,
        default=str,
    )
    names = {item["name"] for item in report["assertions"]}
    assert REQUIRED_FULL_ASSERTIONS <= names, sorted(REQUIRED_FULL_ASSERTIONS - names)
    for supervisor in report["supervisors"]:
        assert supervisor["consecutive_cycles"] >= 10
        assert supervisor["records_not_executed"] == 0
        assert (
            supervisor["gap_seconds_min"] >= report["parameters"]["poll_seconds"] - 1.0
        )
    assert report["claims"]["race_lost"] == report["claims"]["race_contenders"] - 1 >= 1
    assert report["victim"]["returncode"] == -9
    assert report["network"]["blocked_attempts"] == 0
    assert report["jobs"]["dead-always-fails"]["outcome"] == "DEAD_LETTER"
    assert report["jobs"]["slow-recovered"]["attempt_count"] == 2
    # Every known-defect area is decided one way or the other, never left out.
    assert set(report["fixed_behaviour_detected"]) == {"D6", "D7", "D7-crash"}
    open_defects = {item["id"] for item in report["known_defects"]}
    assert open_defects == {
        k for k, fixed in report["fixed_behaviour_detected"].items() if not fixed
    }


@pytest.mark.requires_postgres("TEST_DATABASE_URL")
def test_concurrent_claim_control_passes_on_unmodified_copy(tmp_path: Path) -> None:
    script = _source_copy(tmp_path, None)
    _completed, report = _run_proof(
        script, tmp_path / "race.json", "--scenario", "race"
    )
    assert report["status"] == "PASS", _failed(report)
    assert report["claims"]["race_lost"] == 1


@pytest.mark.requires_postgres("TEST_DATABASE_URL")
def test_negative_control_claim_guard_removed_fails_the_proof(tmp_path: Path) -> None:
    script = _source_copy(tmp_path, (CLAIM_GUARD, CLAIM_GUARD_REMOVED))
    completed, report = _run_proof(script, tmp_path / "race.json", "--scenario", "race")
    assert completed.returncode == 1 and report["status"] == "FAIL"
    failed = _failed(report)
    assert "concurrent_claim_lost_by_all_but_one" in failed, failed
    assert "zero_duplicate_executions" in failed, failed
    assert report["claims"]["race_lost"] == 0


@pytest.mark.requires_postgres("TEST_DATABASE_URL")
def test_negative_control_token_check_removed_fails_the_fence(tmp_path: Path) -> None:
    script = _source_copy(
        tmp_path, (COMPLETE_TOKEN_CHECK, COMPLETE_TOKEN_CHECK_REMOVED)
    )
    completed, report = _run_proof(
        script, tmp_path / "fence.json", "--scenario", "fence"
    )
    assert completed.returncode == 1 and report["status"] == "FAIL"
    failed = _failed(report)
    assert "dead_worker_token_fenced_during_recovery_lease" in failed, failed
    fence = next(
        item["detail"]
        for item in report["assertions"]
        if item["name"] == "dead_worker_token_fenced_during_recovery_lease"
    )
    assert fence["complete_current_owner_dead_token"] == "accepted"


# ---------------------------------------------------------------------------
# Harness safety rails (no database needed)
# ---------------------------------------------------------------------------


def _load_script():
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


def _child(env_update: dict[str, str]) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if not k.startswith("OC_AUTPROOF_")}
    env.update(env_update)
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--supervisor-child", "--verify-handshake"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_child_handshake_accepts_only_the_harness_secret(tmp_path: Path) -> None:
    proof = _load_script()
    secret_file = tmp_path / "child-secret"
    secret = proof._write_child_secret(secret_file)
    assert (secret_file.stat().st_mode & 0o777) == 0o600

    ok = _child(
        {proof.CHILD_TOKEN_ENV: secret, proof.CHILD_SECRET_FILE_ENV: str(secret_file)}
    )
    assert ok.returncode == 0, ok.stderr

    wrong = _child(
        {proof.CHILD_TOKEN_ENV: "0" * 64, proof.CHILD_SECRET_FILE_ENV: str(secret_file)}
    )
    assert wrong.returncode == 2
    assert "does not match" in wrong.stderr

    absent = _child({proof.CHILD_TOKEN_ENV: secret})
    assert absent.returncode == 2 and "not provided" in absent.stderr

    missing = _child(
        {
            proof.CHILD_TOKEN_ENV: secret,
            proof.CHILD_SECRET_FILE_ENV: str(tmp_path / "nope"),
        }
    )
    assert missing.returncode == 2 and "unreadable" in missing.stderr

    secret_file.chmod(0o640)
    loose = _child(
        {proof.CHILD_TOKEN_ENV: secret, proof.CHILD_SECRET_FILE_ENV: str(secret_file)}
    )
    assert loose.returncode == 2 and "wider than 0600" in loose.stderr


def test_proof_executor_hook_does_not_arm_without_the_handshake() -> None:
    result = _child({})
    assert result.returncode == 2
    assert "handshake refused" in result.stderr


def test_duplicate_detector_flags_overlap_and_allows_lawful_retries() -> None:
    proof = _load_script()

    def ev(event: str, t: float, pid: int, attempt: int) -> dict:
        return {
            "event": event,
            "t": t,
            "pid": pid,
            "attempt": attempt,
            "program_job_id": "job",
            "job_key": "k",
            "worker_id": f"w{pid}",
        }

    lawful = [
        ev("start", 0, 1, 1),  # killed: no end/fail recorded
        ev("start", 61, 2, 2),  # after the lease could expire
        ev("fail", 62, 2, 2),
        ev("start", 70, 3, 3),  # after a recorded failure
        ev("end", 71, 3, 3),
    ]
    assert proof._overlapping_executions(lawful, 60) == []
    overlap = [ev("start", 0, 1, 1), ev("start", 1, 2, 2), ev("end", 2, 1, 1)]
    assert len(proof._overlapping_executions(overlap, 60)) == 1
    after_success = [ev("start", 0, 1, 1), ev("end", 1, 1, 1), ev("start", 100, 2, 2)]
    assert (
        proof._overlapping_executions(after_success, 60)[0]["previous_succeeded"]
        is True
    )


def test_harness_refuses_a_non_loopback_database() -> None:
    proof = _load_script()
    with pytest.raises(SystemExit, match="non-loopback"):
        proof._endpoint("postgresql://user:secret@db.example.org:5432/prod")
    assert proof._endpoint("postgresql://u:p@localhost:55432/db") == "localhost:55432"
    assert proof._endpoint("postgresql+psycopg2://u@127.0.0.1/db") == "127.0.0.1:5432"


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


def test_claim_observer_recognises_only_the_claim_update() -> None:
    proof = _load_script()
    claim_sql = (
        "UPDATE calyx_engineering_program_jobs SET status=%(status)s, lease_owner=..."
    )
    assert proof._is_claim_update(claim_sql, {"status": "running", "lease_token": "t"})
    # release_preflight / recovery write status=queued and clear the token.
    assert not proof._is_claim_update(
        claim_sql, {"status": "queued", "lease_token": None}
    )
    assert not proof._is_claim_update(
        "SELECT 1", {"status": "running", "lease_token": "t"}
    )
    assert (
        proof._claim_job_id({"program_job_id_1": "abc", "status": "running"}) == "abc"
    )


def test_socket_module_is_untouched_in_the_test_process() -> None:
    # Loading the script must not arm the guard in an importing process.
    _load_script()
    assert socket.socket.connect.__qualname__ == "socket.connect"
