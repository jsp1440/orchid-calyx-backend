"""Timer-driven proof of the program-autonomy supervisor on real PostgreSQL.

What runs
---------
The harness starts ``runtime.program_autonomy_worker.main()`` in N >= 2
separate supervisor processes. ``main()`` enters the real ``run_forever``
loop, and that loop's own ``time.sleep(poll_seconds)`` timer drives every
cycle. The harness never calls ``run_once``, ``run_forever`` or the cycle
function. It seeds programs, injects faults, reads the database and reads each
supervisor's own stdout, which ``main()`` writes one JSON record per cycle.
Cycles are counted from those records. Poll and lease intervals are the
smallest values ``ProgramAutonomyPolicy`` accepts (15 s / 60 s), set through
the production environment variables.

All N supervisors (and the crash canaries) start from one shared barrier: each
blocks on a PostgreSQL advisory lock the harness holds, and the harness
releases it only once every process is waiting. A separate "victim"
supervisor is started earlier and alone, because it must be the one holding
the slow job's lease when it is SIGKILLed.

Why a proof-only executor hook
------------------------------
``AuthoritativeExecutorRegistry`` is a closed allowlist of the roles an
autonomous worker may complete. It has no registration extension point, and
that is deliberate: a plugin or environment hook would let configuration
widen what production workers execute. So the proof adds none. The supervisor
child mode in this file rebinds ``program_cycle.AuthoritativeExecutorRegistry``
to a subclass carrying the fake executors, then calls the unmodified
``main()``. Nothing under ``app/`` or ``runtime/`` imports this script. Child
mode arms only after a handshake: the harness writes a per-run secret to a
0600 file it owns and passes the same secret in the environment, and the child
compares them in constant time.

Faults injected (scenario ``full``)
-----------------------------------
* Controlled concurrent claim: while only one job is queued, every supervisor
  claims it at the same instant. A driver-level gate holds each process's
  claim UPDATE for that job until all N have issued it. Each process records
  the UPDATE's rowcount, so lost claim races are counted, not assumed.
* SIGKILL of the victim while it holds a live lease on a slow job.
* Duplicate-lease attempts by an intruder against that live lease.
* While the recovered attempt 2 holds its live lease, the production
  ``complete``/``heartbeat`` API is called with the dead worker's token.
* A fake provider 503 (a ``RuntimeError`` subclass).
* Realistic provider failures, a ``ConnectionError`` and an
  ``httpx.HTTPStatusError``. Each runs in its own crash-canary supervisor, so
  a supervisor death is observed and reported, not hidden.
* A job whose executor always fails, so it is dead-lettered after
  ``max_attempts``.
* A mid-run enqueue of a new program.

Known defects (D6, D7, D7-crash) are detected from behaviour. When the fixed
behaviour is present it is asserted strictly. When it is absent it is reported
under ``known_defects``, and ``--require-defect-fixes`` turns every open known
defect into a failure.

No network
----------
Every process installs a socket guard. It denies Python-level
``connect``/``getaddrinfo`` to anything but the loopback PostgreSQL in the
DSN, and it logs each attempt. A self-test against a TEST-NET address proves
the guard is armed. libpq opens its PostgreSQL connection in C, below this
guard, and that is the only permitted destination. Non-loopback DSNs are
refused. The harness creates a unique schema, bootstraps it with
``ensure_orchestrator_schema``, and drops it afterwards.
"""

from __future__ import annotations

import argparse
import hmac
import itertools
import json
import os
import re
import secrets
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EVIDENCE_SCHEMA = "oc.program-autonomy-timer-proof.v2"
OWNER = "autonomy-timer-proof-owner"
CHILD_TOKEN_ENV = "OC_AUTPROOF_CHILD_TOKEN"
CHILD_SECRET_FILE_ENV = "OC_AUTPROOF_CHILD_SECRET_FILE"
LEDGER_ENV = "OC_AUTPROOF_LEDGER"
NETLOG_ENV = "OC_AUTPROOF_NETLOG"
ALLOWED_ENDPOINT_ENV = "OC_AUTPROOF_ALLOWED_ENDPOINT"
BARRIER_KEY_ENV = "OC_AUTPROOF_BARRIER_KEY"
RACE_JOB_ENV = "OC_AUTPROOF_RACE_JOB"
RACE_CONTENDERS_ENV = "OC_AUTPROOF_RACE_CONTENDERS"
RACE_DIR_ENV = "OC_AUTPROOF_RACE_DIR"
REQUIRE_FIXES_ENV = "OC_AUTPROOF_REQUIRE_DEFECT_FIXES"
SELFTEST_ADDRESS = ("192.0.2.1", 443)  # RFC 5737 TEST-NET-1: never routable.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
RACE_GATE_TIMEOUT_SECONDS = 20.0

PROBE_ROLE = "autonomy_probe"  # real production executor, wrapped for the ledger
PROVIDER_ROLE = "proof_fake_provider_probe"
DEAD_ROLE = "proof_permanent_failure"
SLOW_ROLE = "proof_slow_probe"
FAKE_503_CODE = "FAKE_PROVIDER_HTTP_503"
FAKE_CONNECTION_CODE = "FAKE_PROVIDER_CONNECTION_RESET"
FAKE_HTTPX_CODE = "FAKE_PROVIDER_HTTPX_STATUS_503"
PERMANENT_CODE = "FAKE_PERMANENT_EXECUTOR_FAILURE"
INJECTED_ERROR_CODES = frozenset(
    {FAKE_503_CODE, FAKE_CONNECTION_CODE, FAKE_HTTPX_CODE, PERMANENT_CODE}
)
REPAIR_JOB_PREFIX = "dead-letter-repair:"
# failure kind -> (supervisor name, owner). One owner per canary, so only that
# canary can ever claim the job that raises this failure.
CANARIES = {
    "connection_error": ("canary-connection-error", "autproof-canary-connerror-owner"),
    "httpx_status": ("canary-httpx-status", "autproof-canary-httpx-owner"),
}
CANARY_CODES = {
    "connection_error": FAKE_CONNECTION_CODE,
    "httpx_status": FAKE_HTTPX_CODE,
}

SCENARIO_REQUIRED = {
    "race": {
        "barrier_released_all_supervisors_together",
        "concurrent_claim_lost_by_all_but_one",
        "race_job_delivered_exactly_once",
        "zero_duplicate_executions",
        "no_network_calls",
        "harness_never_invoked_the_cycle",
    },
    "fence": {
        "barrier_released_all_supervisors_together",
        "victim_killed_mid_lease",
        "dead_worker_token_fenced_during_recovery_lease",
        "dead_worker_job_recovered",
        "zero_duplicate_executions",
        "no_network_calls",
        "harness_never_invoked_the_cycle",
    },
}

_SELFTEST_ACTIVE = threading.local()

_ENV_DENY = re.compile(
    r"(API_KEY|TOKEN|SECRET|PASSWORD|ANTHROPIC|OPENAI|GEMINI|FIRECRAWL|^PG|DATABASE_URL"
    r"|CALYX_PROGRAM_AUTONOMY_|^OC_AUTPROOF_)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Socket guard (harness and supervisor children)
# ---------------------------------------------------------------------------


def _append_jsonl(path: str | None, record: dict[str, Any]) -> None:
    if not path:
        return
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (json.dumps(record, sort_keys=True) + "\n").encode())
    finally:
        os.close(fd)


def _install_socket_guard(allowed_endpoint: str, netlog: str | None) -> None:
    """Deny every Python-level outbound connection except loopback PostgreSQL."""
    host, _, port_text = allowed_endpoint.rpartition(":")
    allowed_port = int(port_text) if port_text.isdigit() else None
    allowed_hosts = {host} | (LOOPBACK_HOSTS if host in LOOPBACK_HOSTS else set())

    def record(kind: str, target: object) -> None:
        if getattr(_SELFTEST_ACTIVE, "on", False):
            kind = f"selftest_{kind}"
        _append_jsonl(
            netlog,
            {
                "kind": kind,
                "target": repr(target),
                "pid": os.getpid(),
                "t": time.time(),
            },
        )

    def allowed(address: object) -> bool:
        if isinstance(address, (str, bytes)):
            return True  # AF_UNIX path
        if isinstance(address, tuple) and len(address) >= 2:
            return str(address[0]) in allowed_hosts and address[1] == allowed_port
        return False

    original_connect = socket.socket.connect
    original_connect_ex = socket.socket.connect_ex
    original_getaddrinfo = socket.getaddrinfo

    def guarded_connect(self: socket.socket, address: Any) -> Any:
        if not allowed(address):
            record("connect_blocked", address)
            raise PermissionError(f"OC_AUTPROOF_NETWORK_BLOCKED:{address!r}")
        return original_connect(self, address)

    def guarded_connect_ex(self: socket.socket, address: Any) -> Any:
        if not allowed(address):
            record("connect_blocked", address)
            raise PermissionError(f"OC_AUTPROOF_NETWORK_BLOCKED:{address!r}")
        return original_connect_ex(self, address)

    def guarded_getaddrinfo(host: Any, port: Any, *args: Any, **kwargs: Any) -> Any:
        name = host.decode() if isinstance(host, bytes) else str(host)
        if name not in allowed_hosts:
            record("getaddrinfo_blocked", (name, port))
            raise PermissionError(f"OC_AUTPROOF_NETWORK_BLOCKED:{name}")
        return original_getaddrinfo(host, port, *args, **kwargs)

    socket.socket.connect = guarded_connect  # type: ignore[method-assign]
    socket.socket.connect_ex = guarded_connect_ex  # type: ignore[method-assign]
    socket.getaddrinfo = guarded_getaddrinfo  # type: ignore[assignment]


def _guard_selftest(netlog: str | None) -> bool:
    """Prove the guard is armed: a TEST-NET connect must be refused by it."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    _SELFTEST_ACTIVE.on = True
    try:
        probe.settimeout(0.5)
        probe.connect(SELFTEST_ADDRESS)
    except PermissionError as exc:
        blocked = "OC_AUTPROOF_NETWORK_BLOCKED" in str(exc)
    except OSError:
        blocked = False
    else:
        blocked = False
    finally:
        _SELFTEST_ACTIVE.on = False
        probe.close()
    _append_jsonl(
        netlog,
        {"kind": "selftest", "blocked": blocked, "pid": os.getpid(), "t": time.time()},
    )
    return blocked


# ---------------------------------------------------------------------------
# Child handshake
# ---------------------------------------------------------------------------


def _write_child_secret(path: Path) -> str:
    secret = secrets.token_hex(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, secret.encode())
    finally:
        os.close(fd)
    return secret


def _verify_child_handshake(environ: Any) -> str | None:
    """Return why the child must refuse to arm, or ``None`` when it may."""
    token = str(environ.get(CHILD_TOKEN_ENV, ""))
    path = str(environ.get(CHILD_SECRET_FILE_ENV, ""))
    if not token or not path:
        return "harness token or secret file not provided"
    try:
        info = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        return f"secret file unreadable: {type(exc).__name__}"
    if not stat.S_ISREG(info.st_mode):
        return "secret file is not a regular file"
    if info.st_uid != os.getuid():
        return "secret file is not owned by this user"
    if info.st_mode & 0o077:
        return "secret file permissions are wider than 0600"
    with open(path, encoding="utf-8") as handle:
        expected = handle.read().strip()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        return "secret file does not hold a harness secret"
    if not hmac.compare_digest(expected.encode(), token.encode()):
        return "harness token does not match the secret file"
    return None


# ---------------------------------------------------------------------------
# Supervisor child: proof-only executors + the unmodified production main()
# ---------------------------------------------------------------------------


class FakeProviderHTTPError(RuntimeError):
    """Synthetic stand-in for a provider 503. Never produced by a real call."""


def _httpx_status_error() -> Exception:
    """A real ``httpx.HTTPStatusError`` built locally. No request is sent."""
    try:
        import httpx
    except ImportError:  # pragma: no cover - httpx is a runtime requirement

        class HTTPStatusError(Exception):
            """Fallback with httpx's shape when httpx is unavailable."""

        return HTTPStatusError(FAKE_HTTPX_CODE)
    request = httpx.Request("POST", "https://provider.invalid/v1/messages")
    response = httpx.Response(503, request=request)
    return httpx.HTTPStatusError(FAKE_HTTPX_CODE, request=request, response=response)


class FakeModelProvider:
    """Scripted, socket-free provider. Fails on the attempts it is told to."""

    def complete(self, *, attempt: int, fail_on_attempts: list[int], kind: str) -> dict:
        if attempt in fail_on_attempts:
            if kind == "connection_error":
                raise ConnectionError(FAKE_CONNECTION_CODE)
            if kind == "httpx_status":
                raise _httpx_status_error()
            raise FakeProviderHTTPError(FAKE_503_CODE)
        return {"status": 200, "synthetic": True, "content": "fake-provider-ok"}


def _plain_dsn(dsn: str) -> str:
    return re.sub(r"^postgres(ql)?\+\w+://", "postgresql://", dsn)


def _wait_at_barrier(dsn: str, key: int, worker_id: str) -> None:
    import psycopg2

    arrived = time.time()
    conn = psycopg2.connect(_plain_dsn(dsn))
    try:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock_shared(%s)", (key,))
            released = time.time()
            cur.execute("SELECT pg_advisory_unlock_shared(%s)", (key,))
    finally:
        conn.close()
    _append_jsonl(
        os.environ[LEDGER_ENV],
        {
            "event": "barrier_released",
            "worker_id": worker_id,
            "pid": os.getpid(),
            "t": released,
            "waited_s": round(released - arrived, 3),
        },
    )


def _is_claim_update(statement: str, parameters: Any) -> bool:
    return (
        statement.lstrip().startswith(
            "UPDATE calyx_engineering_program_jobs SET status="
        )
        and isinstance(parameters, dict)
        and parameters.get("status") == "running"
        and bool(parameters.get("lease_token"))
    )


def _claim_job_id(parameters: dict) -> str | None:
    return next(
        (
            str(value)
            for key, value in parameters.items()
            if key.startswith("program_job_id") and isinstance(value, str)
        ),
        None,
    )


def _install_claim_observer(worker_id: str) -> None:
    """Record every claim UPDATE's rowcount; gate the race job's claim.

    The gate only delays the statement. It changes nothing about what the
    production claim executes, so a lost race here is the production UPDATE's
    own ``WHERE status = 'queued' AND outcome IS NULL`` guard at work.
    """
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    ledger = os.environ[LEDGER_ENV]
    race_job = os.environ.get(RACE_JOB_ENV, "")
    contenders = int(os.environ.get(RACE_CONTENDERS_ENV, "0") or 0)
    race_dir = Path(os.environ.get(RACE_DIR_ENV, "."))
    gated = {"done": False}

    def arrivals() -> int:
        return len(list(race_dir.glob("*.arrived")))

    def before(conn, cursor, statement, parameters, context, executemany):
        if gated["done"] or not race_job or not _is_claim_update(statement, parameters):
            return
        if _claim_job_id(parameters) != race_job:
            return
        gated["done"] = True
        (race_dir / f"{os.getpid()}.arrived").touch()
        deadline = time.time() + RACE_GATE_TIMEOUT_SECONDS
        while time.time() < deadline and arrivals() < contenders:
            time.sleep(0.005)
        _append_jsonl(
            ledger,
            {
                "event": "race_gate",
                "worker_id": worker_id,
                "pid": os.getpid(),
                "t": time.time(),
                "arrived": arrivals(),
                "contenders": contenders,
            },
        )

    def after(conn, cursor, statement, parameters, context, executemany):
        if not _is_claim_update(statement, parameters):
            return
        _append_jsonl(
            ledger,
            {
                "event": "claim_update",
                "program_job_id": _claim_job_id(parameters),
                "rowcount": cursor.rowcount,
                "worker_id": worker_id,
                "pid": os.getpid(),
                "t": time.time(),
            },
        )

    event.listen(Engine, "before_cursor_execute", before)
    event.listen(Engine, "after_cursor_execute", after)


def _supervisor_child(verify_only: bool = False) -> int:
    refusal = _verify_child_handshake(os.environ)
    if refusal is not None:
        print(f"supervisor child handshake refused: {refusal}", file=sys.stderr)
        return 2
    if verify_only:
        return 0
    netlog = os.environ.get(NETLOG_ENV)
    _install_socket_guard(os.environ[ALLOWED_ENDPOINT_ENV], netlog)
    if not _guard_selftest(netlog):
        print("socket guard self-test did not block", file=sys.stderr)
        return 3

    from app.calyx_orchestrator import program_cycle
    from app.calyx_orchestrator.engineering_core import TerminalOutcome
    from app.calyx_orchestrator.executor import (
        ExecutionReceipt,
        ExecutionState,
        GovernedAssignment,
        canonical_checksum,
    )
    from app.calyx_orchestrator.executor_registry import (
        AuthoritativeExecutorRegistry,
        RegisteredExecutor,
    )
    from runtime import program_autonomy_worker

    worker_id = os.environ.get("CALYX_PROGRAM_AUTONOMY_WORKER_ID", "")
    ledger = os.environ[LEDGER_ENV]
    provider = FakeModelProvider()
    _install_claim_observer(worker_id)

    def job_meta(assignment: GovernedAssignment) -> dict[str, Any]:
        job = assignment.inputs.get("job")
        if not isinstance(job, dict):
            raise TypeError("PROOF_JOB_INPUT_REQUIRED")
        return job

    def event(kind: str, assignment: GovernedAssignment, **extra: Any) -> None:
        if kind == "start":
            from hashlib import sha256

            from app.calyx_orchestrator.program_models import CalyxProgramJob
            from app.database import get_session_local

            with get_session_local()() as db:
                job = db.get(CalyxProgramJob, assignment.assignment_id)
                token = job.lease_token if job else None
                expires = (
                    job.lease_expires_at.timestamp()
                    if job and job.lease_expires_at
                    else 0
                )
                extra.update(
                    {
                        "lease_fingerprint": sha256(token.encode()).hexdigest()
                        if token
                        else None,
                        "live_owned_lease": bool(
                            job
                            and job.status == "running"
                            and job.lease_owner == worker_id
                            and token
                            and expires > time.time()
                        ),
                    }
                )
        _append_jsonl(
            ledger,
            {
                "event": kind,
                "program_job_id": assignment.assignment_id,
                "job_key": assignment.job_key,
                "role_key": assignment.role_key,
                "attempt": int(job_meta(assignment).get("attempt_count") or 0),
                "worker_id": worker_id,
                "pid": os.getpid(),
                "t": time.time(),
                **extra,
            },
        )

    def receipt(
        key: str, assignment: GovernedAssignment, output: dict
    ) -> ExecutionReceipt:
        built = ExecutionReceipt(
            assignment_id=assignment.assignment_id,
            program_id=assignment.program_id,
            job_key=assignment.job_key,
            executor_key=key,
            state=ExecutionState.DELIVERED,
            outcome=TerminalOutcome.DELIVERED,
            input_checksum=assignment.verified_input_checksum(),
            output_checksum=canonical_checksum(output),
            output=output,
            evidence_uris=assignment.evidence_uris,
        )
        built.verify()
        return built

    class LedgerProbe:
        """Delegates to the real AutonomyProbeExecutor; only adds ledger lines."""

        def __init__(self, inner: Any) -> None:
            self.inner = inner
            self.executor_key = inner.executor_key

        def execute(self, assignment: GovernedAssignment) -> ExecutionReceipt:
            event("start", assignment)
            result = self.inner.execute(assignment)
            event("end", assignment)
            return result

    class FakeProviderProbe:
        executor_key = "proof_fake_provider_probe_v1"

        def execute(self, assignment: GovernedAssignment) -> ExecutionReceipt:
            job = job_meta(assignment)
            event("start", assignment)
            try:
                answer = provider.complete(
                    attempt=int(job.get("attempt_count") or 0),
                    fail_on_attempts=list(job.get("fail_on_attempts") or []),
                    kind=str(job.get("failure_kind") or "http_503"),
                )
            except Exception as exc:
                event(
                    "fail", assignment, code=str(exc), exception_type=type(exc).__name__
                )
                raise
            event("end", assignment)
            output = {"provider": answer, "side_effects": []}
            return receipt(self.executor_key, assignment, output)

    class PermanentFailure:
        executor_key = "proof_permanent_failure_v1"

        def execute(self, assignment: GovernedAssignment) -> ExecutionReceipt:
            event("start", assignment)
            event("fail", assignment, code=PERMANENT_CODE, exception_type="ValueError")
            raise ValueError(PERMANENT_CODE)

    class SlowProbe:
        executor_key = "proof_slow_probe_v1"

        def execute(self, assignment: GovernedAssignment) -> ExecutionReceipt:
            job = job_meta(assignment)
            event("start", assignment)
            delays = job.get("slow_seconds_by_attempt") or {}
            delay = float(delays.get(str(int(job.get("attempt_count") or 0)), 0))
            if delay:
                time.sleep(delay)
            event("end", assignment)
            return receipt(
                self.executor_key, assignment, {"slow": True, "side_effects": []}
            )

    class ProofExecutorRegistry(AuthoritativeExecutorRegistry):
        def __init__(self, **kwargs: Any) -> None:
            super().__init__(**kwargs)
            probe = self._by_role[PROBE_ROLE]
            self._by_role[PROBE_ROLE] = RegisteredExecutor(
                role_key=PROBE_ROLE,
                executor=LedgerProbe(probe.executor),
                authoritative=True,
                external_side_effects=False,
            )
            for role_key, executor in (
                (PROVIDER_ROLE, FakeProviderProbe()),
                (DEAD_ROLE, PermanentFailure()),
                (SLOW_ROLE, SlowProbe()),
            ):
                self._by_role[role_key] = RegisteredExecutor(
                    role_key=role_key,
                    executor=executor,
                    authoritative=True,
                    external_side_effects=False,
                )

    program_cycle.AuthoritativeExecutorRegistry = ProofExecutorRegistry  # type: ignore[misc]
    barrier = os.environ.get(BARRIER_KEY_ENV)
    if barrier:
        _wait_at_barrier(os.environ["DATABASE_URL"], int(barrier), worker_id)
    return program_autonomy_worker.main()


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _redact(dsn: str) -> str:
    return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", dsn)


def _endpoint(dsn: str) -> str:
    parts = urlsplit(_plain_dsn(dsn))
    host = parts.hostname or "localhost"
    if host not in LOOPBACK_HOSTS and not host.startswith("/"):
        raise SystemExit(
            f"refusing non-loopback PostgreSQL host {host!r}: this proof is disposable-only"
        )
    return f"{host}:{parts.port or 5432}"


def _with_search_path(dsn: str, schema: str) -> str:
    option = "options=" + quote(f"-csearch_path={schema}", safe="")
    return dsn + ("&" if "?" in dsn else "?") + option


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _safe_json(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except ValueError:
        return None


def _overlapping_executions(
    ledger: list[dict[str, Any]], lease_seconds: int
) -> list[dict[str, Any]]:
    """Executions of one job that a live lease should have excluded.

    A job may start again only after its previous execution recorded a
    failure, or, when that execution was killed without recording anything,
    after its lease could have expired. It may never start again after a
    successful execution. Anything else is a duplicate execution, whatever
    attempt number it carries.
    """
    by_job: dict[str, list[dict[str, Any]]] = {}
    for item in sorted(ledger, key=lambda entry: entry["t"]):
        if item.get("event") in {"start", "end", "fail"}:
            by_job.setdefault(item["program_job_id"], []).append(item)
    findings: list[dict[str, Any]] = []
    for job_id, events in by_job.items():
        starts = [item for item in events if item["event"] == "start"]
        for previous, current in itertools.pairwise(starts):
            closing = [
                item
                for item in events
                if item["event"] in {"end", "fail"}
                and item["pid"] == previous["pid"]
                and item["attempt"] == previous["attempt"]
                and previous["t"] <= item["t"] <= current["t"]
            ]
            succeeded = any(item["event"] == "end" for item in closing)
            failed_first = any(item["event"] == "fail" for item in closing)
            lease_could_expire = current["t"] >= previous["t"] + lease_seconds - 1.0
            if succeeded or not (failed_first or lease_could_expire):
                findings.append(
                    {
                        "program_job_id": job_id,
                        "job_key": current["job_key"],
                        "previous": [previous["worker_id"], previous["attempt"]],
                        "current": [current["worker_id"], current["attempt"]],
                        "seconds_after_previous_start": round(
                            current["t"] - previous["t"], 2
                        ),
                        "previous_succeeded": succeeded,
                    }
                )
    return findings


@dataclass
class Supervisor:
    name: str
    worker_id: str
    owner: str
    process: subprocess.Popen
    started_at: float
    records: list[dict[str, Any]] = field(default_factory=list)
    stderr_path: Path | None = None
    stopped_by_harness: bool = False

    def cycles(self) -> list[dict[str, Any]]:
        return [item for item in self.records if item["record"].get("executed") is True]

    @staticmethod
    def cycle(item: dict[str, Any]) -> dict[str, Any]:
        return item["record"].get("cycle") or {}

    def crash_line(self) -> str | None:
        if self.stderr_path is None or not self.stderr_path.exists():
            return None
        text = self.stderr_path.read_text(encoding="utf-8", errors="replace")
        lines = [line for line in text.splitlines() if line.strip()]
        return lines[-1][:300] if lines else None


def _reader(sup: Supervisor, log_path: Path) -> None:
    assert sup.process.stdout is not None
    with log_path.open("a", encoding="utf-8") as log:
        for raw in sup.process.stdout:
            now = time.time()
            log.write(f"{now:.3f} {raw}")
            log.flush()
            try:
                record = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict) and "executed" in record:
                sup.records.append({"t": now, "record": record})


class Proof:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.scenario: str = args.scenario
        self.dsn: str = args.dsn
        self.endpoint = _endpoint(self.dsn)
        self.schema = f"oc_autproof_{uuid.uuid4().hex[:12]}"
        self.scoped_dsn = _with_search_path(self.dsn, self.schema)
        self.workdir = Path(args.workdir or tempfile.mkdtemp(prefix="oc-autproof-"))
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.secret_path = self.workdir / "child-secret"
        self.token = _write_child_secret(self.secret_path)
        self.ledger = self.workdir / "execution-ledger.jsonl"
        self.netlog = self.workdir / "network-guard.jsonl"
        self.race_dir = self.workdir / "race"
        self.race_dir.mkdir(exist_ok=True)
        self.barrier_key = secrets.randbelow(2**30) + 1
        self.supervisors: list[Supervisor] = []
        self.canaries: dict[str, Supervisor] = {}
        self.victim: Supervisor | None = None
        self.assertions: list[dict[str, Any]] = []
        self.timeline: list[dict[str, Any]] = []
        self.known_defects: list[dict[str, Any]] = []
        self.fixed_behaviour: dict[str, bool] = {}
        self.programs: dict[str, str] = {}
        self.race_job_id: str | None = None
        self.victim_lease: dict[str, Any] | None = None
        self.fence_result: dict[str, Any] | None = None
        self.mid_run_enqueue_at: float | None = None
        self.settled_before_deadline = False
        self.barrier_waiters = 0
        self.t0 = time.time()

    # -- database -----------------------------------------------------------
    def _engine(self, dsn: str):
        from sqlalchemy import create_engine

        return create_engine(dsn, pool_pre_ping=True)

    def setup_schema(self) -> str:
        from sqlalchemy import text
        from sqlalchemy.orm import Session

        from app.calyx_orchestrator.schema import ensure_orchestrator_schema

        admin = self._engine(self.dsn)
        with admin.begin() as conn:
            version = conn.execute(text("SHOW server_version")).scalar_one()
            conn.execute(text(f'CREATE SCHEMA "{self.schema}"'))
        admin.dispose()
        self.engine = self._engine(self.scoped_dsn)
        with Session(self.engine) as db:
            ensure_orchestrator_schema(db)
        return str(version)

    def drop_schema(self) -> None:
        from sqlalchemy import text

        engine = getattr(self, "engine", None)
        if engine is not None:
            engine.dispose()
        admin = self._engine(self.dsn)
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE'))
        admin.dispose()

    def session(self):
        from sqlalchemy.orm import Session

        return Session(self.engine)

    def create_program(
        self,
        name: str,
        specs: list[Any],
        deps: list[tuple[str, str]],
        owner: str = OWNER,
    ) -> str:
        from app.calyx_orchestrator.program_repository import (
            PersistentProgramRepository,
        )

        with self.session() as db:
            repo = PersistentProgramRepository(db)
            program = repo.create_program(
                owner=owner,
                title=f"Timer proof: {name}",
                objective="Synthetic proof workload for the program-autonomy supervisor timer.",
                jobs=specs,
                dependencies=deps,
            )
            repo.start(owner=owner, program_id=program.program_id)
            self.programs[name] = program.program_id
        self.mark("enqueue", program=name)
        return self.programs[name]

    def jobs(self) -> dict[str, Any]:
        from sqlalchemy import select

        from app.calyx_orchestrator.program_models import CalyxProgramJob

        with self.session() as db:
            rows = db.scalars(select(CalyxProgramJob)).all()
            return {
                row.job_key: {
                    "program_job_id": row.program_job_id,
                    "program_id": row.program_id,
                    "role_key": row.role_key,
                    "status": row.status,
                    "outcome": row.outcome,
                    "attempt_count": row.attempt_count,
                    "max_attempts": row.max_attempts,
                    "lease_owner": row.lease_owner,
                    "lease_token": row.lease_token,
                    "lease_expires_at": (
                        row.lease_expires_at.timestamp()
                        if row.lease_expires_at
                        else None
                    ),
                    "blocker": row.blocker,
                    "evidence": _safe_json(row.evidence_json),
                }
                for row in rows
            }

    def program_status(self) -> dict[str, str]:
        from app.calyx_orchestrator.program_models import CalyxProgram

        with self.session() as db:
            return {
                name: db.get(CalyxProgram, pid).status
                for name, pid in self.programs.items()
            }

    @staticmethod
    def _spec(
        key: str, role: str, title: str, repository: str, inputs: dict | None = None
    ):
        from app.calyx_orchestrator.program_repository import ProgramJobSpec

        return ProgramJobSpec(key, role, title, repository, inputs=inputs)

    # -- processes ----------------------------------------------------------
    def mark(self, event: str, **extra: Any) -> None:
        self.timeline.append(
            {"t": round(time.time() - self.t0, 2), "event": event, **extra}
        )

    def child_env(self, worker_id: str, owner: str, barrier: bool) -> dict[str, str]:
        env = {
            key: value for key, value in os.environ.items() if not _ENV_DENY.search(key)
        }
        env.update(
            {
                "PYTHONPATH": str(REPO_ROOT),
                "PYTHONUNBUFFERED": "1",
                "DATABASE_URL": self.scoped_dsn,
                "NO_API_MODE": "true",
                "PROVIDER_LAUNCH_AUTHORIZED": "false",
                "CALYX_PROGRAM_AUTONOMY_ENABLED": "true",
                "CALYX_PROGRAM_AUTONOMY_OWNER": owner,
                "CALYX_PROGRAM_AUTONOMY_WORKER_ID": worker_id,
                "CALYX_PROGRAM_AUTONOMY_POLL_SECONDS": str(self.args.poll_seconds),
                "CALYX_PROGRAM_AUTONOMY_LEASE_SECONDS": str(self.args.lease_seconds),
                "CALYX_PROGRAM_AUTONOMY_MAX_JOBS_PER_CYCLE": str(
                    self.args.max_jobs_per_cycle
                ),
                "CALYX_PROGRAM_AUTONOMY_TIMEOUT_SECONDS": "60",
                CHILD_TOKEN_ENV: self.token,
                CHILD_SECRET_FILE_ENV: str(self.secret_path),
                LEDGER_ENV: str(self.ledger),
                NETLOG_ENV: str(self.netlog),
                ALLOWED_ENDPOINT_ENV: self.endpoint,
                RACE_DIR_ENV: str(self.race_dir),
                RACE_CONTENDERS_ENV: str(self.args.supervisors),
            }
        )
        if self.race_job_id:
            env[RACE_JOB_ENV] = self.race_job_id
        if barrier:
            env[BARRIER_KEY_ENV] = str(self.barrier_key)
        return env

    def spawn(
        self, name: str, worker_id: str, owner: str = OWNER, barrier: bool = True
    ) -> Supervisor:
        stderr_path = self.workdir / f"{name}.stderr.log"
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--supervisor-child"],
            cwd=str(REPO_ROOT),
            env=self.child_env(worker_id, owner, barrier),
            stdout=subprocess.PIPE,
            stderr=stderr_path.open("w", encoding="utf-8"),
            text=True,
            bufsize=1,
        )
        sup = Supervisor(
            name, worker_id, owner, process, time.time(), stderr_path=stderr_path
        )
        threading.Thread(
            target=_reader, args=(sup, self.workdir / f"{name}.stdout.log"), daemon=True
        ).start()
        self.mark("spawn", supervisor=name, pid=process.pid)
        return sup

    def all_processes(self) -> list[Supervisor]:
        return [
            *self.supervisors,
            *self.canaries.values(),
            *([self.victim] if self.victim else []),
        ]

    def stop_all(self) -> None:
        for sup in self.all_processes():
            if sup.process.poll() is None:
                sup.stopped_by_harness = True
                sup.process.send_signal(signal.SIGTERM)
        for sup in self.all_processes():
            try:
                sup.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                sup.process.kill()
                sup.process.wait(timeout=5)

    def hold_barrier(self):
        import psycopg2

        conn = psycopg2.connect(_plain_dsn(self.dsn))
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s)", (self.barrier_key,))
        return conn

    def release_barrier(self, conn, expected: int) -> None:
        def waiting() -> int:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' "
                    "AND NOT granted AND classid = 0 AND objid = %s AND objsubid = 1",
                    (self.barrier_key,),
                )
                return int(cur.fetchone()[0])

        self.wait_for(lambda: waiting() >= expected, 90)
        self.barrier_waiters = waiting()
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_unlock(%s)", (self.barrier_key,))
        conn.close()
        self.mark("barrier_released", waiting=self.barrier_waiters, expected=expected)

    # -- assertions ---------------------------------------------------------
    def check(self, name: str, passed: bool, detail: Any = None) -> bool:
        self.assertions.append({"name": name, "passed": bool(passed), "detail": detail})
        return bool(passed)

    def defect(self, defect_id: str, observed: str, **extra: Any) -> None:
        self.known_defects.append({"id": defect_id, "observed": observed, **extra})

    @staticmethod
    def wait_for(predicate, timeout: float, interval: float = 0.5) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(interval)
        return bool(predicate())

    def ledger_events(self, event: str, **match: Any) -> list[dict[str, Any]]:
        return [
            item
            for item in _read_jsonl(self.ledger)
            if item.get("event") == event
            and all(item.get(k) == v for k, v in match.items())
        ]

    # -- the run --------------------------------------------------------------
    def run(self) -> dict[str, Any]:
        _install_socket_guard(self.endpoint, str(self.netlog))
        server_version = self.setup_schema()
        if self.scenario in {"full", "fence"} and not self.start_victim():
            return self.finish(server_version)
        barrier = self.hold_barrier()
        if self.scenario in {"full", "race"}:
            spec = self._spec(
                "race-0", PROBE_ROLE, "Concurrent claim target", "proof/race"
            )
            self.create_program("race", [spec], [])
            self.race_job_id = self.jobs()["race-0"]["program_job_id"]
        if self.scenario == "full":
            self.seed_canaries()
        if self.scenario == "productive":
            self.create_program(
                "productive",
                [
                    self._spec(
                        f"productive-{index}",
                        PROBE_ROLE,
                        f"Productive timer job {index}",
                        "proof/productive",
                    )
                    for index in range(self.args.target_cycles)
                ],
                [
                    (f"productive-{index}", f"productive-{index + 1}")
                    for index in range(self.args.target_cycles - 1)
                ],
            )
        for index in range(1, self.args.supervisors + 1):
            self.supervisors.append(
                self.spawn(f"supervisor-{index}", f"autproof-supervisor-{index}")
            )
        if self.scenario == "full":
            for kind, (name, owner) in CANARIES.items():
                self.canaries[kind] = self.spawn(name, f"autproof-{name}", owner=owner)
        self.release_barrier(barrier, len(self.supervisors) + len(self.canaries))

        if self.race_job_id:
            self.wait_for(self.race_resolved, 45)
            self.mark("race_resolved")
        if self.scenario == "race":
            self.wait_for(lambda: self.jobs()["race-0"]["outcome"] is not None, 30)
            time.sleep(3)  # let any duplicate execution a broken guard allowed finish
            self.stop_all()
            return self.finish(server_version)

        if self.scenario == "full":
            self.seed_main_workload()
            self.duplicate_lease_attempts()
        if self.victim is not None:
            self.kill_victim()
        self.drive(time.time() + self.args.deadline_seconds)
        self.mark("stop_supervisors")
        self.stop_all()
        return self.finish(server_version)

    def drive(self, deadline: float) -> None:
        while time.time() < deadline:
            if self.scenario == "productive":
                if (
                    len(self.supervisors[0].cycles()) >= self.args.target_cycles
                    and self.settled()
                ):
                    self.settled_before_deadline = True
                    return
                if self.supervisors[0].process.poll() is not None:
                    return
                time.sleep(1.0)
                continue
            if self.fence_result is None:
                self.try_fence_during_recovery()
            if self.scenario == "fence":
                if (
                    self.fence_result is not None
                    and self.jobs()["slow-recovered"]["outcome"]
                ):
                    self.settled_before_deadline = True
                    return
            else:
                counts = [len(sup.cycles()) for sup in self.supervisors]
                if (
                    self.mid_run_enqueue_at is None
                    and min(counts) >= self.args.mid_run_after_cycles
                ):
                    self.mid_run_enqueue_at = time.time()
                    self.create_program(
                        "midrun",
                        [
                            self._spec(
                                f"midrun-{i}",
                                PROBE_ROLE,
                                f"Mid-run job {i}",
                                "proof/midrun",
                            )
                            for i in range(3)
                        ],
                        [("midrun-0", "midrun-1"), ("midrun-1", "midrun-2")],
                    )
                if (
                    self.mid_run_enqueue_at is not None
                    and min(counts) >= self.args.target_cycles
                    and self.fence_result is not None
                    and self.settled()
                ):
                    self.settled_before_deadline = True
                    return
            if any(sup.process.poll() is not None for sup in self.supervisors):
                return
            time.sleep(1.0)

    def start_victim(self) -> bool:
        self.create_program(
            "slow",
            [
                self._spec(
                    "slow-recovered",
                    SLOW_ROLE,
                    "Slow job whose first worker is SIGKILLed mid-lease",
                    "proof/slow",
                    inputs={
                        # Attempt 1 never finishes (it is killed). Attempt 2 holds its
                        # lease long enough to be probed with the dead worker's token.
                        "slow_seconds_by_attempt": {
                            "1": self.args.lease_seconds * 10,
                            "2": self.args.recovery_hold_seconds,
                        }
                    },
                )
            ],
            [],
        )
        self.victim = self.spawn("victim", "autproof-victim", barrier=False)

        def executing() -> bool:
            job = self.jobs()["slow-recovered"]
            return (
                job["status"] == "running"
                and job["lease_owner"] == "autproof-victim"
                and bool(self.ledger_events("start", job_key="slow-recovered"))
            )

        if not self.check("victim_claimed_slow_job", self.wait_for(executing, 60)):
            return False
        self.victim_lease = self.jobs()["slow-recovered"]
        self.mark("victim_claimed", attempt=self.victim_lease["attempt_count"])
        return True

    def race_resolved(self) -> bool:
        updates = self.ledger_events("claim_update", program_job_id=self.race_job_id)
        return len(updates) >= self.args.supervisors

    def seed_canaries(self) -> None:
        for kind, (name, owner) in CANARIES.items():
            spec = self._spec(
                f"{name}-job",
                PROVIDER_ROLE,
                f"Fake provider raises {kind} on attempt 1",
                f"proof/{name}",
                inputs={"fail_on_attempts": [1], "failure_kind": kind},
            )
            self.create_program(name, [spec], [], owner=owner)

    def seed_main_workload(self) -> None:
        spec = self._spec
        self.create_program(
            "chain",
            [
                spec(f"chain-{i}", PROBE_ROLE, f"Chain job {i}", "proof/chain")
                for i in range(4)
            ],
            [(f"chain-{i}", f"chain-{i + 1}") for i in range(3)],
        )
        self.create_program(
            "parallel",
            [
                spec(f"parallel-{i}", PROBE_ROLE, f"Parallel job {i}", "proof/parallel")
                for i in range(4)
            ],
            [],
        )
        self.create_program(
            "provider",
            [
                spec(
                    "provider-503-once",
                    PROVIDER_ROLE,
                    "Fake provider answers 503 on attempt 1",
                    "proof/provider",
                    inputs={"fail_on_attempts": [1]},
                ),
                spec(
                    "provider-ok-0",
                    PROVIDER_ROLE,
                    "Fake provider healthy",
                    "proof/provider",
                ),
                spec(
                    "provider-ok-1",
                    PROVIDER_ROLE,
                    "Fake provider healthy",
                    "proof/provider",
                ),
            ],
            [],
        )
        self.create_program(
            "deadletter",
            [
                spec(
                    "dead-always-fails",
                    DEAD_ROLE,
                    "Executor always fails",
                    "proof/deadletter",
                ),
                spec(
                    "dead-downstream",
                    PROBE_ROLE,
                    "Must never run",
                    "proof/deadletter-downstream",
                ),
            ],
            [("dead-always-fails", "dead-downstream")],
        )

    def kill_victim(self) -> None:
        assert self.victim is not None
        live = self.jobs()["slow-recovered"]
        lease_live = bool(
            live["lease_expires_at"] and live["lease_expires_at"] > time.time()
        )
        self.victim.process.send_signal(signal.SIGKILL)
        self.victim.process.wait(timeout=10)
        killed_at = time.time()
        self.mark("victim_sigkill", lease_live=lease_live)
        self.check(
            "victim_killed_mid_lease",
            lease_live
            and self.victim.process.returncode == -signal.SIGKILL
            and live["lease_owner"] == "autproof-victim",
            {
                "returncode": self.victim.process.returncode,
                "lease_expires_in_s": round(
                    (live["lease_expires_at"] or 0) - killed_at, 2
                ),
            },
        )

    def settled(self) -> bool:
        dead_canary_jobs = {
            f"{CANARIES[kind][0]}-job"
            for kind, sup in self.canaries.items()
            if sup.process.poll() is not None
        }
        for key, job in self.jobs().items():
            if key.startswith(REPAIR_JOB_PREFIX) or key == "dead-downstream":
                continue  # inert follow-up records, never executed by design
            if key in dead_canary_jobs:
                continue  # its only supervisor died; that is reported, not waited on
            if job["outcome"] is None:
                return False
        return True

    def duplicate_lease_attempts(self) -> None:
        from sqlalchemy import update

        from app.calyx_orchestrator.program_models import CalyxProgramJob
        from app.calyx_orchestrator.program_worker import PersistentProgramWorker

        assert self.victim_lease is not None
        job_id = self.victim_lease["program_job_id"]
        results: dict[str, str] = {}
        with self.session() as db:
            worker = PersistentProgramWorker(db)
            claimed = worker.claim(
                worker_id="autproof-intruder",
                lease_seconds=self.args.lease_seconds,
                owner=OWNER,
                allowed_role_keys=frozenset({SLOW_ROLE}),
            )
            results["claim_same_role"] = "claimed" if claimed is not None else "refused"
            forged = str(uuid.uuid4())
            for label, worker_id in (
                ("complete_forged_token", "autproof-intruder"),
                ("complete_victim_id_forged_token", "autproof-victim"),
            ):
                try:
                    worker.complete(
                        program_job_id=job_id,
                        worker_id=worker_id,
                        lease_token=forged,
                        outcome="DELIVERED",
                    )
                    results[label] = "accepted"
                except PermissionError as exc:
                    results[label] = f"refused:{exc}"
            try:
                worker.heartbeat(
                    program_job_id=job_id,
                    worker_id="autproof-victim",
                    lease_token=forged,
                    lease_seconds=self.args.lease_seconds,
                )
                results["heartbeat_forged_token"] = "accepted"
            except PermissionError as exc:
                results["heartbeat_forged_token"] = f"refused:{exc}"
            raw = db.execute(
                update(CalyxProgramJob)
                .where(
                    CalyxProgramJob.program_job_id == job_id,
                    CalyxProgramJob.status == "queued",
                    CalyxProgramJob.outcome.is_(None),
                )
                .values(
                    status="running",
                    lease_owner="autproof-intruder",
                    lease_token=str(uuid.uuid4()),
                )
            )
            results["raw_conditional_claim_rows"] = str(raw.rowcount)
            db.commit()
        after = self.jobs()["slow-recovered"]
        unchanged = all(
            after[key] == self.victim_lease[key]
            for key in ("lease_token", "lease_owner", "attempt_count", "outcome")
        )
        refused = (
            results["claim_same_role"] == "refused"
            and all(
                value.startswith("refused:")
                for key, value in results.items()
                if key.startswith(("complete", "heartbeat"))
            )
            and results["raw_conditional_claim_rows"] == "0"
        )
        self.mark("duplicate_lease_attempts")
        self.check(
            "duplicate_lease_attempts_refused",
            refused and unchanged,
            {**results, "lease_unchanged": unchanged},
        )

    def try_fence_during_recovery(self) -> None:
        """Probe the recovered attempt 2 with the dead worker's token, via the API."""
        from app.calyx_orchestrator.program_worker import PersistentProgramWorker

        assert self.victim_lease is not None
        live = self.jobs()["slow-recovered"]
        started = self.ledger_events("start", job_key="slow-recovered", attempt=2)
        if not (
            started
            and live["status"] == "running"
            and live["attempt_count"] == 2
            and live["lease_owner"]
            and live["lease_owner"] != "autproof-victim"
            and live["lease_expires_at"]
            and live["lease_expires_at"] > time.time() + 2
        ):
            return
        stale = self.victim_lease["lease_token"]
        job_id = live["program_job_id"]
        results: dict[str, str] = {}
        with self.session() as db:
            worker = PersistentProgramWorker(db)
            probes = (
                ("complete_current_owner_dead_token", "complete", live["lease_owner"]),
                (
                    "heartbeat_current_owner_dead_token",
                    "heartbeat",
                    live["lease_owner"],
                ),
                ("complete_dead_worker_own_token", "complete", "autproof-victim"),
            )
            for label, method, worker_id in probes:
                try:
                    if method == "complete":
                        worker.complete(
                            program_job_id=job_id,
                            worker_id=worker_id,
                            lease_token=stale,
                            outcome="DELIVERED",
                        )
                    else:
                        worker.heartbeat(
                            program_job_id=job_id,
                            worker_id=worker_id,
                            lease_token=stale,
                            lease_seconds=self.args.lease_seconds,
                        )
                    results[label] = "accepted"
                except (PermissionError, ValueError, LookupError) as exc:
                    results[label] = f"refused:{exc}"
        after = self.jobs()["slow-recovered"]
        unchanged = all(
            after[key] == live[key]
            for key in ("lease_token", "lease_owner", "attempt_count", "outcome")
        )
        still_live = bool(
            after["lease_expires_at"] and after["lease_expires_at"] > time.time()
        )
        self.fence_result = {
            **results,
            "recovery_lease_owner": live["lease_owner"],
            "recovery_lease_unchanged": unchanged,
            "recovery_lease_still_live": still_live,
            "probed_at_s": round(time.time() - self.t0, 2),
        }
        self.mark("fence_probe_during_recovery_lease")

    # -- evaluation -----------------------------------------------------------
    def finish(self, server_version: str) -> dict[str, Any]:
        if any(sup.process.poll() is None for sup in self.all_processes()):
            self.stop_all()
        args = self.args
        ledger = _read_jsonl(self.ledger)
        netlog = _read_jsonl(self.netlog)
        try:
            jobs = self.jobs()
            programs = self.program_status()
        except Exception as exc:  # noqa: BLE001 - reported, never masked
            jobs, programs = {}, {}
            self.check("durable_state_readable", False, f"{type(exc).__name__}: {exc}")

        supervisors = [
            self.supervisor_evidence(sup, main=True) for sup in self.supervisors
        ]
        canaries = {
            kind: self.supervisor_evidence(sup, main=False)
            for kind, sup in self.canaries.items()
        }
        self.evaluate_barrier(ledger)
        claims = self.evaluate_claims(jobs, ledger)
        self.evaluate_duplicates(ledger)
        if self.victim_lease is not None:
            self.evaluate_recovery(jobs, ledger)
        if self.scenario == "full":
            self.evaluate_full(jobs, programs, ledger)
            self.evaluate_known_defects(jobs, programs, ledger, canaries)
        if self.scenario == "productive":
            self.evaluate_productive(jobs, ledger)
        network = self.evaluate_network(netlog)
        cycle_modules = (
            "runtime.program_autonomy_worker",
            "app.calyx_orchestrator.program_cycle",
        )
        imported = sorted(name for name in cycle_modules if name in sys.modules)
        self.check("harness_never_invoked_the_cycle", not imported, imported)
        if args.require_defect_fixes:
            for item in self.known_defects:
                self.check(
                    f"known_defect_{item['id']}_must_be_fixed", False, item["observed"]
                )

        required = SCENARIO_REQUIRED.get(self.scenario)
        gating = [
            item
            for item in self.assertions
            if required is None
            or item["name"] in required
            or item["name"].startswith("known_defect_")
        ]
        missing = sorted(
            (required or set()) - {item["name"] for item in self.assertions}
        )
        passed = bool(gating) and not missing and all(item["passed"] for item in gating)
        return {
            "schema": EVIDENCE_SCHEMA,
            "status": "PASS" if passed else "FAIL",
            "scenario": self.scenario,
            "generated_at_unix": round(time.time(), 3),
            "duration_seconds": round(time.time() - self.t0, 2),
            "mode": "real run_forever supervisor subprocesses; synthetic proof workload; NO-API",
            "postgres": {
                "server_version": server_version,
                "dsn": _redact(self.dsn),
                "schema": self.schema,
            },
            "parameters": {
                "supervisors": args.supervisors,
                "target_cycles": args.target_cycles,
                "poll_seconds": args.poll_seconds,
                "lease_seconds": args.lease_seconds,
                "max_jobs_per_cycle": args.max_jobs_per_cycle,
                "deadline_seconds": args.deadline_seconds,
                "require_defect_fixes": bool(args.require_defect_fixes),
            },
            "cycle_source": (
                "each supervisor's own per-cycle JSON stdout records emitted by "
                "runtime.program_autonomy_worker.main()"
            ),
            "supervisors": supervisors,
            "crash_canaries": canaries,
            "victim": {
                "worker_id": self.victim.worker_id if self.victim else None,
                "returncode": self.victim.process.returncode if self.victim else None,
            },
            "claims": claims,
            "executions": {
                "starts": sum(1 for i in ledger if i.get("event") == "start"),
                "successes": sum(1 for i in ledger if i.get("event") == "end"),
                "injected_failures": sum(1 for i in ledger if i.get("event") == "fail"),
            },
            "jobs": {
                key: {
                    f: job[f]
                    for f in (
                        "role_key",
                        "status",
                        "outcome",
                        "attempt_count",
                        "blocker",
                    )
                }
                for key, job in sorted(jobs.items())
            },
            "programs": programs,
            "assertions": self.assertions,
            "gating_assertions": sorted({item["name"] for item in gating}),
            "missing_required_assertions": missing,
            "fixed_behaviour_detected": self.fixed_behaviour,
            "known_defects": self.known_defects,
            "timeline": self.timeline,
            "network": network,
        }

    def supervisor_evidence(self, sup: Supervisor, *, main: bool) -> dict[str, Any]:
        args = self.args
        cycles = sup.cycles()
        gaps = [round(b["t"] - a["t"], 2) for a, b in itertools.pairwise(cycles)]
        errors = [sup.cycle(c)["error"] for c in cycles if sup.cycle(c).get("error")]
        unexpected = [e for e in errors if e.get("code") not in INJECTED_ERROR_CODES]
        died = sup.process.returncode is not None and not sup.stopped_by_harness
        evidence = {
            "name": sup.name,
            "worker_id": sup.worker_id,
            "pid": sup.process.pid,
            "cycles": len(cycles),
            "consecutive_cycles": len(cycles),
            "records_not_executed": len(sup.records) - len(cycles),
            "exit_code": sup.process.returncode,
            "died_before_stop": died,
            "crash": sup.crash_line() if died else None,
            "ran_seconds": round(
                (cycles[-1]["t"] if cycles else sup.started_at) - sup.started_at, 2
            ),
            "gap_seconds_min": min(gaps) if gaps else None,
            "gap_seconds_max": max(gaps) if gaps else None,
            "stop_reasons": dict(
                Counter(sup.cycle(c).get("stop_reason") for c in cycles)
            ),
            "jobs_completed": sum(
                sup.cycle(c).get("completed_jobs", 0) for c in cycles
            ),
            "unexpected_errors": unexpected,
        }
        if not main:
            return evidence
        target = args.target_cycles if self.scenario in {"full", "productive"} else 1
        self.check(
            f"{sup.name}_consecutive_timer_cycles",
            len(cycles) >= target and len(sup.records) == len(cycles),
            {"cycles": len(cycles), "target": target},
        )
        self.check(
            f"{sup.name}_loop_survived_until_stopped",
            not died and sup.process.returncode == -signal.SIGTERM,
            {"returncode": sup.process.returncode, "crash": evidence["crash"]},
        )
        if self.scenario in {"full", "productive"}:
            paced = (
                bool(gaps)
                and min(gaps) >= args.poll_seconds - 1.0
                and max(gaps) <= args.poll_seconds + 30
            )
            self.check(
                f"{sup.name}_cycles_paced_by_own_timer",
                paced,
                {"min_gap": min(gaps or [0]), "max_gap": max(gaps or [0])},
            )
        self.check(
            f"{sup.name}_no_unexpected_cycle_errors", not unexpected, unexpected[:3]
        )
        return evidence

    def evaluate_productive(
        self, jobs: dict[str, Any], ledger: list[dict[str, Any]]
    ) -> None:
        """Refuse timer-only evidence: every required cycle must finish one job."""
        cycles = self.supervisors[0].cycles()
        expected = [f"productive-{index}" for index in range(self.args.target_cycles)]
        completed_keys: list[str] = []
        job_ids: list[str] = []
        lease_ids: list[str] = []
        cycle_evidence: list[dict[str, Any]] = []
        valid = len(cycles) == self.args.target_cycles
        for ordinal, record in enumerate(cycles, start=1):
            cycle = self.supervisors[0].cycle(record)
            results = cycle.get("jobs", [])
            valid = valid and (
                cycle.get("attempted_jobs") == 1
                and cycle.get("completed_jobs") == 1
                and not cycle.get("failed_jobs")
                and not cycle.get("error")
                and len(results) == 1
            )
            if len(results) != 1:
                continue
            result = results[0]
            key, job_id = result.get("job_key"), result.get("program_job_id")
            completed_keys.append(key)
            job_ids.append(job_id)
            durable = jobs.get(key, {})
            starts = [
                item
                for item in ledger
                if item.get("event") == "start" and item.get("program_job_id") == job_id
            ]
            ends = [
                item
                for item in ledger
                if item.get("event") == "end" and item.get("program_job_id") == job_id
            ]
            persisted = (
                result.get("outcome") == "DELIVERED"
                and durable.get("program_job_id") == job_id
                and durable.get("outcome") == "DELIVERED"
                and durable.get("attempt_count") == 1
                and durable.get("lease_owner") is None
                and durable.get("lease_token") is None
                and durable.get("lease_expires_at") is None
                and len(starts) == len(ends) == 1
                and starts[0].get("live_owned_lease") is True
                and bool(starts[0].get("lease_fingerprint"))
            )
            lease_id = starts[0].get("lease_fingerprint") if len(starts) == 1 else None
            lease_ids.append(lease_id)
            valid = valid and persisted
            cycle_evidence.append(
                {
                    "cycle": ordinal,
                    "program_job_id": job_id,
                    "job_key": key,
                    "lease_fingerprint": lease_id,
                    "completed_and_persisted": persisted,
                }
            )
        self.check(
            "ten_consecutive_productive_timer_cycles",
            valid
            and completed_keys == expected
            and len(set(job_ids)) == self.args.target_cycles
            and len(set(lease_ids)) == self.args.target_cycles
            and all(job_ids)
            and self.settled_before_deadline,
            cycle_evidence,
        )

    def evaluate_barrier(self, ledger: list[dict[str, Any]]) -> None:
        released = [item for item in ledger if item.get("event") == "barrier_released"]
        times = [item["t"] for item in released]
        spread = round(max(times) - min(times), 3) if times else None
        expected = len(self.supervisors) + len(self.canaries)
        self.check(
            "barrier_released_all_supervisors_together",
            len(released) == expected == self.barrier_waiters
            and spread is not None
            and spread < 2.0,
            {
                "released": len(released),
                "waiting_at_release": self.barrier_waiters,
                "expected": expected,
                "spread_s": spread,
            },
        )

    def evaluate_claims(
        self, jobs: dict[str, Any], ledger: list[dict[str, Any]]
    ) -> dict[str, Any]:
        contenders = self.args.supervisors
        updates = [item for item in ledger if item.get("event") == "claim_update"]
        summary: dict[str, Any] = {
            "claim_updates": len(updates),
            "lost_claim_races": sum(1 for item in updates if item["rowcount"] == 0),
            "race_job_id": self.race_job_id,
        }
        if not self.race_job_id:
            return summary
        race = [item for item in updates if item["program_job_id"] == self.race_job_id]
        gates = [item for item in ledger if item.get("event") == "race_gate"]
        won = sum(1 for item in race if item["rowcount"] == 1)
        lost = sum(1 for item in race if item["rowcount"] == 0)
        summary.update(
            {"race_won": won, "race_lost": lost, "race_contenders": contenders}
        )
        self.check(
            "concurrent_claim_lost_by_all_but_one",
            won == 1
            and lost == contenders - 1
            and lost > 0
            and len(gates) == contenders
            and all(gate["arrived"] >= contenders for gate in gates),
            {
                "contenders": contenders,
                "won": won,
                "lost": lost,
                "gate_arrivals": [gate["arrived"] for gate in gates],
            },
        )
        job = jobs.get("race-0", {})
        starts = [
            i
            for i in ledger
            if i.get("event") == "start" and i.get("job_key") == "race-0"
        ]
        ends = [
            i
            for i in ledger
            if i.get("event") == "end" and i.get("job_key") == "race-0"
        ]
        self.check(
            "race_job_delivered_exactly_once",
            job.get("outcome") == "DELIVERED"
            and job.get("attempt_count") == 1
            and len(starts) == 1
            and len(ends) == 1,
            {
                "starts": len(starts),
                "final": {
                    k: job.get(k) for k in ("status", "outcome", "attempt_count")
                },
            },
        )
        return summary

    def evaluate_duplicates(self, ledger: list[dict[str, Any]]) -> None:
        starts = Counter(
            (i["program_job_id"], i["attempt"])
            for i in ledger
            if i.get("event") == "start"
        )
        successes = Counter(i["job_key"] for i in ledger if i.get("event") == "end")
        overlapping = _overlapping_executions(ledger, self.args.lease_seconds)
        repeated = [f"{key[0]}#{key[1]}" for key, count in starts.items() if count > 1]
        twice = [key for key, count in successes.items() if count > 1]
        self.check(
            "zero_duplicate_executions",
            not repeated and not twice and not overlapping,
            {
                "duplicate_attempt_starts": repeated,
                "duplicate_successful_executions": twice,
                "overlapping_or_early_reexecutions": overlapping[:5],
                "executions": sum(starts.values()),
            },
        )

    def evaluate_network(self, netlog: list[dict[str, Any]]) -> dict[str, int]:
        blocked = [item for item in netlog if not item["kind"].startswith("selftest")]
        selftests = [item for item in netlog if item["kind"] == "selftest"]
        guarded = len(self.all_processes())
        self.check(
            "no_network_calls",
            not blocked
            and len(selftests) >= guarded
            and all(item["blocked"] for item in selftests),
            {
                "blocked_attempts": blocked[:5],
                "guard_selftests_blocked": sum(
                    1 for item in selftests if item["blocked"]
                ),
                "processes_guarded": guarded,
            },
        )
        return {"blocked_attempts": len(blocked), "guard_selftests": len(selftests)}

    def evaluate_recovery(
        self, jobs: dict[str, Any], ledger: list[dict[str, Any]]
    ) -> None:
        slow = jobs.get("slow-recovered", {})
        starts = sorted(
            (
                item
                for item in ledger
                if item.get("job_key") == "slow-recovered"
                and item.get("event") == "start"
            ),
            key=lambda item: item["t"],
        )
        recovered = next((item for item in starts if item["attempt"] == 2), None)
        expiry = starts[0]["t"] + self.args.lease_seconds if starts else None
        self.check(
            "dead_worker_job_recovered",
            slow.get("outcome") == "DELIVERED"
            and slow.get("attempt_count") == 2
            and len(starts) == 2
            and starts[0]["worker_id"] == "autproof-victim"
            and recovered is not None
            and recovered["worker_id"].startswith("autproof-supervisor-")
            and recovered["t"] >= (expiry or 0) - 1.0,
            {
                "attempts": [(item["attempt"], item["worker_id"]) for item in starts],
                "recovered_after_lease_expiry_s": (
                    round(recovered["t"] - expiry, 2) if recovered and expiry else None
                ),
                "final": {
                    k: slow.get(k) for k in ("status", "outcome", "attempt_count")
                },
            },
        )
        fence = self.fence_result or {}
        probes = [key for key in fence if key.startswith(("complete_", "heartbeat_"))]
        self.check(
            "dead_worker_token_fenced_during_recovery_lease",
            bool(probes)
            and all(str(fence[key]).startswith("refused:") for key in probes)
            and fence.get("recovery_lease_unchanged") is True
            and fence.get("recovery_lease_still_live") is True,
            fence
            or "the recovery lease was never observed live, so the probe did not run",
        )

    def evaluate_full(
        self,
        jobs: dict[str, Any],
        programs: dict[str, str],
        ledger: list[dict[str, Any]],
    ) -> None:
        delivered = {key for key, job in jobs.items() if job["outcome"] == "DELIVERED"}
        executed = {item["job_key"] for item in ledger if item.get("event") == "end"}
        self.check(
            "durable_outcomes_match_ledger",
            delivered == executed,
            {
                "delivered_without_execution": sorted(delivered - executed),
                "executed_without_delivery": sorted(executed - delivered),
            },
        )

        def first(event: str, key: str) -> dict[str, Any] | None:
            return next(
                (
                    i
                    for i in ledger
                    if i.get("job_key") == key and i.get("event") == event
                ),
                None,
            )

        failed = first("fail", "provider-503-once")
        retried = first("end", "provider-503-once")
        between = [
            item["job_key"]
            for item in ledger
            if item.get("event") == "end"
            and failed
            and retried
            and failed["t"] < item["t"] < retried["t"]
        ]
        failing = next(
            (
                s
                for s in self.supervisors
                if failed and s.worker_id == failed["worker_id"]
            ),
            None,
        )
        later = (
            [c for c in failing.cycles() if c["t"] > failed["t"]]
            if failing and failed
            else []
        )
        provider = jobs.get("provider-503-once", {})
        self.check(
            "provider_failure_does_not_stall_other_jobs",
            failed is not None
            and failed["code"] == FAKE_503_CODE
            and provider.get("outcome") == "DELIVERED"
            and provider.get("attempt_count") == 2
            and len(between) >= 1
            and len(later) >= 1
            and all(
                jobs.get(key, {}).get("outcome") == "DELIVERED"
                for key in ("provider-ok-0", "provider-ok-1")
            ),
            {
                "failing_worker": failed["worker_id"] if failed else None,
                "jobs_completed_while_503_job_waited": len(between),
                "failing_supervisor_cycles_after_failure": len(later),
                "final": {
                    k: provider.get(k) for k in ("status", "outcome", "attempt_count")
                },
            },
        )
        dead = jobs.get("dead-always-fails", {})
        dead_fails = sorted(
            item["attempt"]
            for item in ledger
            if item.get("job_key") == "dead-always-fails"
            and item.get("event") == "fail"
        )
        self.check(
            "dead_letter_after_max_attempts",
            dead.get("outcome") == "DEAD_LETTER"
            and dead.get("status") == "blocked"
            and dead.get("blocker") == "PROGRAM_JOB_ATTEMPTS_EXHAUSTED"
            and dead.get("attempt_count") == dead.get("max_attempts") == 3
            and dead_fails == [1, 2, 3],
            {
                "failed_attempts": dead_fails,
                "final": {
                    k: dead.get(k)
                    for k in ("status", "outcome", "attempt_count", "blocker")
                },
            },
        )
        mid = [key for key in jobs if key.startswith("midrun-")]
        mid_after = all(
            item["t"] > (self.mid_run_enqueue_at or float("inf"))
            for item in ledger
            if str(item.get("job_key", "")).startswith("midrun-")
            and item.get("event") == "start"
        )
        self.check(
            "mid_run_enqueue_completed_autonomously",
            len(mid) == 3
            and mid_after
            and all(
                jobs[k]["outcome"] == "DELIVERED" and jobs[k]["attempt_count"] == 1
                for k in mid
            ),
            {"jobs": {key: jobs[key]["outcome"] for key in mid}},
        )
        normal = [
            key
            for key in jobs
            if key.startswith(
                ("chain-", "parallel-", "midrun-", "provider-ok-", "race-")
            )
        ]
        expected_complete = ("chain", "parallel", "provider", "slow", "midrun", "race")
        self.check(
            "durable_state_changed_as_expected",
            bool(normal)
            and all(
                jobs[k]["status"] == "completed" and jobs[k]["attempt_count"] == 1
                for k in normal
            )
            and all(
                job["lease_token"] is None and job["lease_owner"] is None
                for job in jobs.values()
                if job["outcome"]
            )
            and all(programs.get(name) == "completed" for name in expected_complete)
            and all(
                (job["evidence"] or {}).get("receipt_type") == "execution"
                for job in jobs.values()
                if job["outcome"] == "DELIVERED"
            ),
            {"programs": programs, "normal_jobs": len(normal)},
        )
        self.check(
            "settled_before_deadline",
            self.settled_before_deadline,
            {
                "duration_s": round(time.time() - self.t0, 2),
                "deadline_s": self.args.deadline_seconds,
            },
        )

    def evaluate_known_defects(
        self,
        jobs: dict[str, Any],
        programs: dict[str, str],
        ledger: list[dict[str, Any]],
        canaries: dict[str, dict[str, Any]],
    ) -> None:
        self.evaluate_d6(jobs, programs, ledger)
        self.evaluate_d7(ledger)
        self.evaluate_d7_crash(jobs, ledger, canaries)

    def evaluate_d6(
        self,
        jobs: dict[str, Any],
        programs: dict[str, str],
        ledger: list[dict[str, Any]],
    ) -> None:
        """A dead-letter must block its program, settle dependants, record one follow-up."""
        dead = jobs.get("dead-always-fails", {})
        downstream = jobs.get("dead-downstream", {})
        repairs = {
            key: job for key, job in jobs.items() if key.startswith(REPAIR_JOB_PREFIX)
        }
        executed = {
            item.get("job_key") for item in ledger if item.get("event") == "start"
        }
        never_ran = "dead-downstream" not in executed and not (set(repairs) & executed)
        status = programs.get("deadletter")
        if status == "blocked":
            self.fixed_behaviour["D6"] = True
            repair = next(iter(repairs.values()), {})
            self.check(
                "D6_fixed_dead_letter_blocks_program_with_one_follow_up",
                never_ran
                and len(repairs) == 1
                and next(iter(repairs))
                == f"{REPAIR_JOB_PREFIX}{dead.get('program_job_id')}"
                # The follow-up is an explicit owner-action record (#1710 round 1):
                # blocked for automation, unresolved, never schedulable.
                and repair.get("status") == "blocked"
                and repair.get("outcome") is None
                and repair.get("blocker") == "OWNER_ACTION_REQUIRED:DEAD_LETTER"
                and repair.get("attempt_count") == 0
                and repair.get("max_attempts") == 0
                and downstream.get("outcome") == "BLOCKED"
                and downstream.get("blocker") == "UPSTREAM_JOB_FAILED",
                {
                    "repairs": sorted(repairs),
                    "repair": {
                        k: repair.get(k)
                        for k in (
                            "status",
                            "outcome",
                            "blocker",
                            "attempt_count",
                            "max_attempts",
                        )
                    },
                    "downstream": {
                        k: downstream.get(k) for k in ("status", "outcome", "blocker")
                    },
                },
            )
            return
        self.fixed_behaviour["D6"] = False
        self.check(
            "D6_current_behaviour_dependant_inert",
            status == "running"
            and never_ran
            and not repairs
            and downstream.get("status") == "waiting",
            {
                "program_status": status,
                "downstream": downstream.get("status"),
                "repairs": sorted(repairs),
            },
        )
        self.defect(
            "D6",
            "dead-lettered job left its program 'running' and its dependant 'waiting' "
            "(recover_expired_leases does not refresh program status)",
        )

    def evaluate_d7(self, ledger: list[dict[str, Any]]) -> None:
        """One executor error must not end the cycle."""
        records = [(sup, item) for sup in self.supervisors for item in sup.cycles()]
        error_cycles = [
            sup.cycle(item)
            for sup, item in records
            if sup.cycle(item).get("stop_reason") == "error"
        ]
        reported = [
            f for sup, item in records for f in (sup.cycle(item).get("failures") or [])
        ]
        injected = [
            item
            for item in ledger
            if item.get("event") == "fail"
            and str(item.get("worker_id", "")).startswith("autproof-supervisor-")
        ]
        if error_cycles and not reported:
            self.fixed_behaviour["D7"] = False
            codes = sorted(
                {str((c.get("error") or {}).get("code")) for c in error_cycles}
            )
            self.check(
                "D7_current_behaviour_error_ends_cycle_only_for_injected_faults",
                set(codes) <= INJECTED_ERROR_CODES,
                {"error_cycles": len(error_cycles), "codes": codes},
            )
            self.defect(
                "D7",
                f"{len(error_cycles)} cycle(s) ended at an injected executor error "
                "(stop_reason='error'): run_deterministic_program_cycle returns on the first "
                "executor exception instead of continuing to other runnable jobs",
                codes=codes,
            )
            return
        self.fixed_behaviour["D7"] = True
        codes = Counter(str(f.get("code")) for f in reported)
        self.check(
            "D7_fixed_failures_do_not_end_the_cycle",
            not error_cycles
            and len(reported) == len(injected) > 0
            and set(codes) <= INJECTED_ERROR_CODES,
            {
                "error_cycles": len(error_cycles),
                "reported_failures": dict(codes),
                "injected_failures": len(injected),
            },
        )

    def evaluate_d7_crash(
        self,
        jobs: dict[str, Any],
        ledger: list[dict[str, Any]],
        canaries: dict[str, dict[str, Any]],
    ) -> None:
        """A realistic provider exception must not kill the supervisor process."""
        crashed = {kind: ev for kind, ev in canaries.items() if ev["died_before_stop"]}
        if crashed:
            self.fixed_behaviour["D7-crash"] = False
            self.check(
                "D7_crash_current_behaviour_death_detected",
                all(
                    any(
                        item.get("event") == "fail"
                        and item.get("worker_id") == f"autproof-{CANARIES[kind][0]}"
                        and item.get("code") == CANARY_CODES[kind]
                        for item in ledger
                    )
                    for kind in crashed
                ),
                {kind: ev["crash"] for kind, ev in crashed.items()},
            )
            self.defect(
                "D7-crash",
                "a provider exception outside (LookupError, PermissionError, RuntimeError, "
                "TypeError, ValueError) escapes run_once and ends run_forever: the supervisor "
                "process died",
                crashes={kind: ev["crash"] for kind, ev in crashed.items()},
            )
            return
        self.fixed_behaviour["D7-crash"] = True
        results = {}
        for kind, (name, _owner) in CANARIES.items():
            job = jobs.get(f"{name}-job", {})
            fails = [
                item
                for item in ledger
                if item.get("event") == "fail" and item.get("job_key") == f"{name}-job"
            ]
            results[kind] = (
                job.get("outcome") == "DELIVERED"
                and job.get("attempt_count") == 2
                and len(fails) == 1
                and fails[0]["code"] == CANARY_CODES[kind]
                and canaries[kind]["cycles"] >= 3
                and canaries[kind]["exit_code"] == -signal.SIGTERM
            )
        self.check(
            "D7_crash_fixed_supervisor_survives_realistic_provider_errors",
            bool(results) and all(results.values()),
            results,
        )


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--supervisor-child", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--verify-handshake", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument("--dsn", default=os.environ.get("TEST_DATABASE_URL"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/program-autonomy-timer-proof.json"),
    )
    parser.add_argument(
        "--scenario", choices=("full", "race", "fence", "productive"), default="full"
    )
    parser.add_argument("--supervisors", type=int, default=2)
    parser.add_argument("--target-cycles", type=int, default=10)
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--lease-seconds", type=int, default=60)
    parser.add_argument("--max-jobs-per-cycle", type=int, default=2)
    parser.add_argument("--mid-run-after-cycles", type=int, default=3)
    parser.add_argument("--recovery-hold-seconds", type=int, default=15)
    parser.add_argument("--deadline-seconds", type=int, default=420)
    parser.add_argument(
        "--require-defect-fixes",
        action="store_true",
        default=os.environ.get(REQUIRE_FIXES_ENV, "").strip().lower()
        in {"1", "true", "yes"},
        help=f"fail on any open known defect (D6, D7, D7-crash); also {REQUIRE_FIXES_ENV}=1",
    )
    parser.add_argument("--workdir", default=None)
    parser.add_argument("--keep-workdir", action="store_true")
    args = parser.parse_args(argv)
    if args.supervisor_child:
        return args
    if not args.dsn:
        parser.error("--dsn or TEST_DATABASE_URL is required")
    if args.scenario == "productive" and (
        args.supervisors != 1 or args.max_jobs_per_cycle != 1
    ):
        parser.error("productive proof requires --supervisors 1 --max-jobs-per-cycle 1")
    if args.scenario != "productive" and args.supervisors < 2:
        parser.error("--supervisors must be >= 2")
    if args.scenario in {"full", "productive"} and args.target_cycles < 10:
        parser.error("--target-cycles must be >= 10")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    if args.supervisor_child:
        return _supervisor_child(verify_only=args.verify_handshake)
    proof = Proof(args)
    report: dict[str, Any]
    try:
        report = proof.run()
    except BaseException as exc:
        proof.stop_all()
        report = {
            "schema": EVIDENCE_SCHEMA,
            "status": "FAIL",
            "error": f"{type(exc).__name__}: {exc}",
        }
        if not isinstance(exc, Exception):
            raise
    finally:
        try:
            proof.drop_schema()
        except Exception as exc:  # noqa: BLE001 - a leftover disposable schema is reported
            print(
                f"schema cleanup failed: {type(exc).__name__}: {exc}", file=sys.stderr
            )
    if report.get("status") != "PASS":
        report["stderr_tails"] = {
            path.name: path.read_text(encoding="utf-8", errors="replace")[-2000:]
            for path in sorted(proof.workdir.glob("*.stderr.log"))
        }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    summary = {
        "status": report.get("status"),
        "scenario": report.get("scenario"),
        "cycles": {s["name"]: s["cycles"] for s in report.get("supervisors", [])},
        "duration_seconds": report.get("duration_seconds"),
        "failed": [a["name"] for a in report.get("assertions", []) if not a["passed"]],
        "known_defects": [d["id"] for d in report.get("known_defects", [])],
        "output": str(args.output),
    }
    print(json.dumps(summary, sort_keys=True))
    if not args.keep_workdir and args.workdir is None:
        for path in sorted(proof.workdir.rglob("*"), reverse=True):
            if path.is_dir():
                path.rmdir()
            else:
                path.unlink()
        proof.workdir.rmdir()
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
