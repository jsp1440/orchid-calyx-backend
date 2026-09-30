"""Timer-driven proof of the program-autonomy supervisor on real PostgreSQL.

What runs
---------
The harness starts ``runtime.program_autonomy_worker.main()`` in N >= 2
separate supervisor processes, plus one extra "victim" supervisor that is
SIGKILLed mid-lease. ``main()`` enters the real ``run_forever`` loop, and
that loop's own ``time.sleep(poll_seconds)`` timer drives every cycle. The
harness never calls ``run_once``, ``run_forever`` or the cycle function
itself. It only seeds programs, injects faults, reads the database and reads
each supervisor's own stdout, which ``main()`` writes one JSON record per
cycle. Cycles are counted from those records.

Poll and lease intervals are set through the production environment
variables at the smallest values ``ProgramAutonomyPolicy`` accepts
(15 s poll, 60 s lease). The policy bounds are not bypassed.

Why a proof-only executor hook
------------------------------
``AuthoritativeExecutorRegistry`` is a closed allowlist of the roles an
autonomous worker may complete. It has no registration extension point, and
that is deliberate: a plugin or environment hook would let configuration
widen what production workers execute. So this proof does not add one. The
supervisor child process in this file (``_supervisor_child``) rebinds
``program_cycle.AuthoritativeExecutorRegistry`` to a subclass that adds the
fake roles, then calls the unmodified ``main()``. Production cannot reach
the hook: it lives only in this script, which nothing under ``app/`` or
``runtime/`` imports, and it only arms when the harness sets a per-run
token.

Faults injected
---------------
* SIGKILL of the victim supervisor while it holds a live lease on a slow job.
* Duplicate-lease attempts by an intruder against that live lease: a claim,
  a forged completion, a forged heartbeat and a raw conditional UPDATE. After
  recovery, a completion with the dead worker's own original token.
* A fake provider that answers HTTP 503 on a job's first attempt.
* A job whose executor always fails, so it must be dead-lettered after
  ``max_attempts``.
* A mid-run enqueue of a new program while the supervisors are cycling.

No network
----------
Every process (harness and supervisors) installs a socket guard. It denies
Python-level ``connect``/``create_connection``/``getaddrinfo`` to anything
except the loopback PostgreSQL named in the DSN, and logs each attempt. Each
supervisor also runs a self-test at start-up against a TEST-NET address, to
prove the guard is armed. The fake provider never opens a socket. libpq opens
its PostgreSQL connection in C, below this guard, and that is the only
permitted destination. The DSN must be loopback or a unix socket, and the
harness refuses anything else.

The harness creates a unique schema, bootstraps the orchestrator tables into
it with ``ensure_orchestrator_schema``, and drops it afterwards.
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import re
import signal
import socket
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

EVIDENCE_SCHEMA = "oc.program-autonomy-timer-proof.v1"
OWNER = "autonomy-timer-proof-owner"
CHILD_TOKEN_ENV = "OC_AUTPROOF_CHILD_TOKEN"
LEDGER_ENV = "OC_AUTPROOF_LEDGER"
NETLOG_ENV = "OC_AUTPROOF_NETLOG"
ALLOWED_ENDPOINT_ENV = "OC_AUTPROOF_ALLOWED_ENDPOINT"
SELFTEST_ADDRESS = ("192.0.2.1", 443)  # RFC 5737 TEST-NET-1: never routable.
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

PROBE_ROLE = "autonomy_probe"  # real production executor, wrapped for the ledger
PROVIDER_ROLE = "proof_fake_provider_probe"
DEAD_ROLE = "proof_permanent_failure"
SLOW_ROLE = "proof_slow_probe"
FAKE_503_CODE = "FAKE_PROVIDER_HTTP_503"
PERMANENT_CODE = "FAKE_PERMANENT_EXECUTOR_FAILURE"
INJECTED_ERROR_CODES = frozenset({FAKE_503_CODE, PERMANENT_CODE})

_SELFTEST_ACTIVE = threading.local()

_ENV_DENY = re.compile(
    r"(API_KEY|TOKEN|SECRET|PASSWORD|ANTHROPIC|OPENAI|GEMINI|FIRECRAWL|^PG|DATABASE_URL"
    r"|CALYX_PROGRAM_AUTONOMY_)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Socket guard (harness and supervisor children)
# ---------------------------------------------------------------------------


def _install_socket_guard(allowed_endpoint: str, netlog: str | None) -> None:
    """Deny every Python-level outbound connection except loopback PostgreSQL."""
    host, _, port_text = allowed_endpoint.rpartition(":")
    allowed_port = int(port_text) if port_text.isdigit() else None
    allowed_hosts = {host} | (LOOPBACK_HOSTS if host in LOOPBACK_HOSTS else set())

    def record(kind: str, target: object) -> None:
        if not netlog:
            return
        if getattr(_SELFTEST_ACTIVE, "on", False):
            kind = f"selftest_{kind}"
        line = json.dumps(
            {
                "kind": kind,
                "target": repr(target),
                "pid": os.getpid(),
                "t": time.time(),
            },
            sort_keys=True,
        )
        fd = os.open(netlog, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, (line + "\n").encode())
        finally:
            os.close(fd)

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
    if netlog:
        fd = os.open(netlog, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(
                fd,
                (
                    json.dumps(
                        {
                            "kind": "selftest",
                            "blocked": blocked,
                            "pid": os.getpid(),
                            "t": time.time(),
                        },
                        sort_keys=True,
                    )
                    + "\n"
                ).encode(),
            )
        finally:
            os.close(fd)
    return blocked


# ---------------------------------------------------------------------------
# Supervisor child: proof-only executors + the unmodified production main()
# ---------------------------------------------------------------------------


def _ledger_write(event: dict[str, Any]) -> None:
    path = os.environ[LEDGER_ENV]
    line = json.dumps(event, sort_keys=True) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, line.encode())
    finally:
        os.close(fd)


class FakeProviderHTTPError(RuntimeError):
    """Synthetic stand-in for a provider's 503. Never produced by a real call."""


class FakeModelProvider:
    """Scripted, socket-free provider. Answers 503 on the attempts it is told to."""

    def complete(self, *, attempt: int, fail_on_attempts: list[int]) -> dict[str, Any]:
        if attempt in fail_on_attempts:
            raise FakeProviderHTTPError(FAKE_503_CODE)
        return {"status": 200, "synthetic": True, "content": "fake-provider-ok"}


def _supervisor_child() -> int:
    token = os.environ.get(CHILD_TOKEN_ENV, "")
    if not re.fullmatch(r"[0-9a-f]{32}", token):
        print("supervisor child mode requires the harness token", file=sys.stderr)
        return 2
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
    provider = FakeModelProvider()

    def job_meta(assignment: GovernedAssignment) -> dict[str, Any]:
        job = assignment.inputs.get("job")
        if not isinstance(job, dict):
            raise TypeError("PROOF_JOB_INPUT_REQUIRED")
        return job

    def event(kind: str, assignment: GovernedAssignment, **extra: Any) -> None:
        job = job_meta(assignment)
        _ledger_write(
            {
                "event": kind,
                "program_job_id": assignment.assignment_id,
                "job_key": assignment.job_key,
                "role_key": assignment.role_key,
                "attempt": int(job.get("attempt_count") or 0),
                "worker_id": worker_id,
                "pid": os.getpid(),
                "t": time.time(),
                **extra,
            }
        )

    def receipt(
        executor_key: str, assignment: GovernedAssignment, output: dict[str, Any]
    ) -> ExecutionReceipt:
        built = ExecutionReceipt(
            assignment_id=assignment.assignment_id,
            program_id=assignment.program_id,
            job_key=assignment.job_key,
            executor_key=executor_key,
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
            attempt = int(job.get("attempt_count") or 0)
            try:
                answer = provider.complete(
                    attempt=attempt,
                    fail_on_attempts=list(job.get("fail_on_attempts") or []),
                )
            except FakeProviderHTTPError as exc:
                event("fail", assignment, code=str(exc))
                raise
            event("end", assignment)
            return receipt(
                self.executor_key, assignment, {"provider": answer, "side_effects": []}
            )

    class PermanentFailure:
        executor_key = "proof_permanent_failure_v1"

        def execute(self, assignment: GovernedAssignment) -> ExecutionReceipt:
            event("start", assignment)
            event("fail", assignment, code=PERMANENT_CODE)
            raise ValueError(PERMANENT_CODE)

    class SlowProbe:
        executor_key = "proof_slow_probe_v1"

        def execute(self, assignment: GovernedAssignment) -> ExecutionReceipt:
            job = job_meta(assignment)
            event("start", assignment)
            if int(job.get("attempt_count") or 0) in list(
                job.get("slow_on_attempts") or []
            ):
                time.sleep(float(job.get("slow_seconds") or 600))
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
    return program_autonomy_worker.main()


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


def _redact(dsn: str) -> str:
    return re.sub(r"://([^:/@]+):[^@]*@", r"://\1:***@", dsn)


def _endpoint(dsn: str) -> str:
    parts = urlsplit(re.sub(r"^postgres(ql)?\+\w+://", "postgresql://", dsn))
    host = parts.hostname or "localhost"
    if host not in LOOPBACK_HOSTS and not host.startswith("/"):
        raise SystemExit(
            f"refusing non-loopback PostgreSQL host {host!r}: this proof is disposable-only"
        )
    return f"{host}:{parts.port or 5432}"


def _with_search_path(dsn: str, schema: str) -> str:
    option = "options=" + quote(f"-csearch_path={schema}", safe="")
    return dsn + ("&" if "?" in dsn else "?") + option


@dataclass
class Supervisor:
    name: str
    worker_id: str
    process: subprocess.Popen
    started_at: float
    records: list[dict[str, Any]] = field(default_factory=list)
    other_lines: int = 0
    stderr_path: Path | None = None
    killed_at: float | None = None

    def cycles(self) -> list[dict[str, Any]]:
        return [item for item in self.records if item["record"].get("executed") is True]


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
                sup.other_lines += 1
                continue
            if isinstance(record, dict) and "executed" in record:
                sup.records.append({"t": now, "record": record})
            else:
                sup.other_lines += 1


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _overlapping_executions(
    ledger: list[dict[str, Any]], lease_seconds: int
) -> list[dict[str, Any]]:
    """Executions of one job that a live lease should have excluded.

    A job may start again only after its previous execution failed or was
    killed *and* that execution's lease (claimed just before its start) could
    have expired. It may never start again after a successful execution.
    Anything else is a duplicate execution, whatever attempt number it carries.
    """
    by_job: dict[str, list[dict[str, Any]]] = {}
    for item in sorted(ledger, key=lambda entry: entry["t"]):
        by_job.setdefault(item["program_job_id"], []).append(item)
    findings: list[dict[str, Any]] = []
    for job_id, events in by_job.items():
        starts = [item for item in events if item["event"] == "start"]
        for previous, current in itertools.pairwise(starts):
            succeeded = any(
                item["event"] == "end"
                and item["pid"] == previous["pid"]
                and previous["t"] <= item["t"] <= current["t"]
                for item in events
            )
            earliest = previous["t"] + lease_seconds - 1.0
            if succeeded or current["t"] < earliest:
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


class Proof:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.dsn: str = args.dsn
        self.endpoint = _endpoint(self.dsn)
        self.schema = f"oc_autproof_{uuid.uuid4().hex[:12]}"
        self.scoped_dsn = _with_search_path(self.dsn, self.schema)
        self.token = uuid.uuid4().hex
        self.workdir = Path(args.workdir or tempfile.mkdtemp(prefix="oc-autproof-"))
        self.workdir.mkdir(parents=True, exist_ok=True)
        self.ledger = self.workdir / "execution-ledger.jsonl"
        self.netlog = self.workdir / "network-guard.jsonl"
        self.supervisors: list[Supervisor] = []
        self.victim: Supervisor | None = None
        self.assertions: list[dict[str, Any]] = []
        self.timeline: list[dict[str, Any]] = []
        self.defects: list[dict[str, Any]] = []
        self.programs: dict[str, str] = {}
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

        try:
            self.engine.dispose()
        except AttributeError:
            pass
        admin = self._engine(self.dsn)
        with admin.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE'))
        admin.dispose()

    def session(self):
        from sqlalchemy.orm import Session

        return Session(self.engine)

    def create_program(
        self, name: str, specs: list[Any], deps: list[tuple[str, str]]
    ) -> str:
        from app.calyx_orchestrator.program_repository import (
            PersistentProgramRepository,
        )

        with self.session() as db:
            repo = PersistentProgramRepository(db)
            program = repo.create_program(
                owner=OWNER,
                title=f"Timer proof: {name}",
                objective="Synthetic proof workload for the program-autonomy supervisor timer.",
                jobs=specs,
                dependencies=deps,
            )
            repo.start(owner=OWNER, program_id=program.program_id)
            self.programs[name] = program.program_id
            self.timeline.append(
                {"t": time.time() - self.t0, "event": "enqueue", "program": name}
            )
            return program.program_id

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
                    "lease_expires_at": row.lease_expires_at.timestamp()
                    if row.lease_expires_at
                    else None,
                    "blocker": row.blocker,
                    "evidence": json.loads(row.evidence_json)
                    if row.evidence_json
                    else None,
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

    # -- processes ----------------------------------------------------------
    def child_env(self, worker_id: str) -> dict[str, str]:
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
                "CALYX_PROGRAM_AUTONOMY_OWNER": OWNER,
                "CALYX_PROGRAM_AUTONOMY_WORKER_ID": worker_id,
                "CALYX_PROGRAM_AUTONOMY_POLL_SECONDS": str(self.args.poll_seconds),
                "CALYX_PROGRAM_AUTONOMY_LEASE_SECONDS": str(self.args.lease_seconds),
                "CALYX_PROGRAM_AUTONOMY_MAX_JOBS_PER_CYCLE": str(
                    self.args.max_jobs_per_cycle
                ),
                "CALYX_PROGRAM_AUTONOMY_TIMEOUT_SECONDS": "60",
                CHILD_TOKEN_ENV: self.token,
                LEDGER_ENV: str(self.ledger),
                NETLOG_ENV: str(self.netlog),
                ALLOWED_ENDPOINT_ENV: self.endpoint,
            }
        )
        return env

    def spawn(self, name: str, worker_id: str) -> Supervisor:
        stderr_path = self.workdir / f"{name}.stderr.log"
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--supervisor-child"],
            cwd=str(REPO_ROOT),
            env=self.child_env(worker_id),
            stdout=subprocess.PIPE,
            stderr=stderr_path.open("w", encoding="utf-8"),
            text=True,
            bufsize=1,
        )
        sup = Supervisor(name, worker_id, process, time.time(), stderr_path=stderr_path)
        threading.Thread(
            target=_reader, args=(sup, self.workdir / f"{name}.stdout.log"), daemon=True
        ).start()
        self.timeline.append(
            {
                "t": time.time() - self.t0,
                "event": "spawn",
                "supervisor": name,
                "pid": process.pid,
            }
        )
        return sup

    def stop_all(self) -> None:
        for sup in [*self.supervisors, *([self.victim] if self.victim else [])]:
            if sup.process.poll() is None:
                sup.process.send_signal(signal.SIGTERM)
        for sup in [*self.supervisors, *([self.victim] if self.victim else [])]:
            try:
                sup.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                sup.process.kill()
                sup.process.wait(timeout=5)

    # -- assertions ---------------------------------------------------------
    def check(self, name: str, passed: bool, detail: Any = None) -> bool:
        self.assertions.append({"name": name, "passed": bool(passed), "detail": detail})
        return bool(passed)

    def wait_for(self, predicate, timeout: float, interval: float = 0.5) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(interval)
        return bool(predicate())

    # -- the run --------------------------------------------------------------
    def run(self) -> dict[str, Any]:
        from app.calyx_orchestrator.program_repository import ProgramJobSpec

        args = self.args
        _install_socket_guard(self.endpoint, str(self.netlog))
        server_version = self.setup_schema()

        # Phase 1: the victim supervisor alone claims a slow job, then dies.
        self.create_program(
            "slow",
            [
                ProgramJobSpec(
                    "slow-recovered",
                    SLOW_ROLE,
                    "Slow job whose first worker is SIGKILLed mid-lease",
                    "proof/slow",
                    inputs={
                        "slow_on_attempts": [1],
                        "slow_seconds": args.lease_seconds * 10,
                    },
                )
            ],
            [],
        )
        self.victim = self.spawn("victim", "autproof-victim")

        def victim_executing() -> bool:
            job = self.jobs()["slow-recovered"]
            started = any(
                item["event"] == "start" and item["job_key"] == "slow-recovered"
                for item in _read_jsonl(self.ledger)
            )
            return (
                job["status"] == "running"
                and job["lease_owner"] == "autproof-victim"
                and started
            )

        if not self.check(
            "victim_claimed_slow_job", self.wait_for(victim_executing, 60)
        ):
            return self.finish(server_version)
        victim_lease = self.jobs()["slow-recovered"]
        self.timeline.append(
            {
                "t": time.time() - self.t0,
                "event": "victim_claimed",
                "attempt": victim_lease["attempt_count"],
            }
        )

        # Phase 2: long-lived supervisors and the main workload.
        for index in range(1, args.supervisors + 1):
            self.supervisors.append(
                self.spawn(f"supervisor-{index}", f"autproof-supervisor-{index}")
            )
        chain = [
            ProgramJobSpec(f"chain-{i}", PROBE_ROLE, f"Chain job {i}", "proof/chain")
            for i in range(4)
        ]
        self.create_program(
            "chain", chain, [(f"chain-{i}", f"chain-{i + 1}") for i in range(3)]
        )
        self.create_program(
            "parallel",
            [
                ProgramJobSpec(
                    f"parallel-{i}", PROBE_ROLE, f"Parallel job {i}", "proof/parallel"
                )
                for i in range(4)
            ],
            [],
        )
        self.create_program(
            "provider",
            [
                ProgramJobSpec(
                    "provider-503-once",
                    PROVIDER_ROLE,
                    "Fake provider answers 503 on attempt 1",
                    "proof/provider",
                    inputs={"fail_on_attempts": [1]},
                ),
                ProgramJobSpec(
                    "provider-ok-0",
                    PROVIDER_ROLE,
                    "Fake provider healthy",
                    "proof/provider",
                ),
                ProgramJobSpec(
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
                ProgramJobSpec(
                    "dead-always-fails",
                    DEAD_ROLE,
                    "Executor always fails",
                    "proof/deadletter",
                ),
                ProgramJobSpec(
                    "dead-downstream",
                    PROBE_ROLE,
                    "Must never run",
                    "proof/deadletter-downstream",
                ),
            ],
            [("dead-always-fails", "dead-downstream")],
        )

        # Phase 3: duplicate-lease attempts against the victim's live lease.
        self.duplicate_lease_attempts(victim_lease)

        # Phase 4: SIGKILL the victim while its lease is still live.
        live = self.jobs()["slow-recovered"]
        lease_live = (
            live["lease_expires_at"] is not None
            and live["lease_expires_at"] > time.time()
        )
        self.victim.process.send_signal(signal.SIGKILL)
        self.victim.process.wait(timeout=10)
        self.victim.killed_at = time.time()
        self.timeline.append(
            {
                "t": time.time() - self.t0,
                "event": "victim_sigkill",
                "lease_live": lease_live,
            }
        )
        self.check(
            "victim_killed_mid_lease",
            lease_live and self.victim.process.returncode == -signal.SIGKILL,
            {
                "returncode": self.victim.process.returncode,
                "lease_expires_in_s": round(
                    (live["lease_expires_at"] or 0) - self.victim.killed_at, 2
                ),
            },
        )

        # Phase 5: let the timers run; enqueue more work mid-run.
        mid_enqueued = False
        deadline = time.time() + args.deadline_seconds
        while time.time() < deadline:
            counts = [len(sup.cycles()) for sup in self.supervisors]
            if not mid_enqueued and min(counts) >= args.mid_run_after_cycles:
                self.mid_run_enqueue_at = time.time()
                self.create_program(
                    "midrun",
                    [
                        ProgramJobSpec(
                            f"midrun-{i}",
                            PROBE_ROLE,
                            f"Mid-run job {i}",
                            "proof/midrun",
                        )
                        for i in range(3)
                    ],
                    [("midrun-0", "midrun-1"), ("midrun-1", "midrun-2")],
                )
                mid_enqueued = True
            if any(sup.process.poll() is not None for sup in self.supervisors):
                break
            if mid_enqueued and min(counts) >= args.target_cycles and self.settled():
                break
            time.sleep(1.0)
        self.timeline.append({"t": time.time() - self.t0, "event": "stop_supervisors"})
        self.stale_token_after_recovery(victim_lease)
        self.stop_all()
        return self.finish(server_version)

    def settled(self) -> bool:
        jobs = self.jobs()
        done = [
            k
            for k, v in jobs.items()
            if k != "dead-downstream" and v["outcome"] is not None
        ]
        return len(done) == len(jobs) - 1

    def duplicate_lease_attempts(self, victim_lease: dict[str, Any]) -> None:
        from sqlalchemy import update

        from app.calyx_orchestrator.program_models import CalyxProgramJob
        from app.calyx_orchestrator.program_worker import PersistentProgramWorker

        job_id = victim_lease["program_job_id"]
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
            for label, kwargs in (
                (
                    "complete_forged_token",
                    {
                        "worker_id": "autproof-intruder",
                        "lease_token": str(uuid.uuid4()),
                    },
                ),
                (
                    "complete_victim_id_forged_token",
                    {"worker_id": "autproof-victim", "lease_token": str(uuid.uuid4())},
                ),
            ):
                try:
                    worker.complete(
                        program_job_id=job_id, outcome="DELIVERED", **kwargs
                    )
                    results[label] = "accepted"
                except PermissionError as exc:
                    results[label] = f"refused:{exc}"
            try:
                worker.heartbeat(
                    program_job_id=job_id,
                    worker_id="autproof-victim",
                    lease_token=str(uuid.uuid4()),
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
        unchanged = (
            after["lease_token"] == victim_lease["lease_token"]
            and after["lease_owner"] == "autproof-victim"
            and after["attempt_count"] == victim_lease["attempt_count"]
            and after["outcome"] is None
        )
        refused = (
            results["claim_same_role"] == "refused"
            and all(
                results[key].startswith("refused:")
                for key in results
                if key.startswith(("complete", "heartbeat"))
            )
            and results["raw_conditional_claim_rows"] == "0"
        )
        self.timeline.append(
            {"t": time.time() - self.t0, "event": "duplicate_lease_attempts"}
        )
        self.check(
            "duplicate_lease_attempts_refused",
            refused and unchanged,
            {**results, "lease_unchanged": unchanged},
        )

    def stale_token_after_recovery(self, victim_lease: dict[str, Any]) -> None:
        from app.calyx_orchestrator.program_worker import PersistentProgramWorker

        with self.session() as db:
            try:
                PersistentProgramWorker(db).complete(
                    program_job_id=victim_lease["program_job_id"],
                    worker_id="autproof-victim",
                    lease_token=victim_lease["lease_token"],
                    outcome="DELIVERED",
                )
                result = "accepted"
            except (PermissionError, ValueError) as exc:
                result = f"refused:{exc}"
        self.check(
            "dead_worker_token_fenced_after_recovery",
            result.startswith("refused:"),
            result,
        )

    # -- evaluation -----------------------------------------------------------
    def finish(self, server_version: str) -> dict[str, Any]:
        if any(
            sup.process.poll() is None
            for sup in [*self.supervisors, *([self.victim] if self.victim else [])]
        ):
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

        supervisor_evidence = []
        for sup in self.supervisors:
            cycles = sup.cycles()
            gaps = [round(b["t"] - a["t"], 2) for a, b in itertools.pairwise(cycles)]
            stop_reasons = Counter(
                item["record"].get("cycle", {}).get("stop_reason") for item in cycles
            )
            unexpected = [
                item["record"]["cycle"]["error"]
                for item in cycles
                if (item["record"].get("cycle") or {}).get("error")
                and item["record"]["cycle"]["error"].get("code")
                not in INJECTED_ERROR_CODES
            ]
            supervisor_evidence.append(
                {
                    "name": sup.name,
                    "worker_id": sup.worker_id,
                    "pid": sup.process.pid,
                    "cycles": len(cycles),
                    "consecutive_cycles": len(cycles),
                    "records_not_executed": len(sup.records) - len(cycles),
                    "exit_code": sup.process.returncode,
                    "ran_seconds": round(
                        (cycles[-1]["t"] if cycles else sup.started_at)
                        - sup.started_at,
                        2,
                    ),
                    "gap_seconds_min": min(gaps) if gaps else None,
                    "gap_seconds_max": max(gaps) if gaps else None,
                    "stop_reasons": dict(stop_reasons),
                    "jobs_completed": sum(
                        item["record"]["cycle"].get("completed_jobs", 0)
                        for item in cycles
                    ),
                    "unexpected_errors": unexpected,
                }
            )
            cycles_ok = len(cycles) >= args.target_cycles and len(sup.records) == len(
                cycles
            )
            self.check(
                f"{sup.name}_consecutive_timer_cycles",
                cycles_ok,
                {"cycles": len(cycles), "target": args.target_cycles},
            )
            # Terminated by the harness's SIGTERM, not by a crash inside the loop.
            self.check(
                f"{sup.name}_loop_survived_until_stopped",
                sup.process.returncode == -signal.SIGTERM,
                {"returncode": sup.process.returncode},
            )
            timer = (
                bool(gaps)
                and min(gaps) >= args.poll_seconds - 1.0
                and max(gaps) <= args.poll_seconds + 30
            )
            self.check(
                f"{sup.name}_cycles_paced_by_own_timer",
                timer,
                {"min_gap": min(gaps or [0]), "max_gap": max(gaps or [0])},
            )
            self.check(
                f"{sup.name}_no_unexpected_cycle_errors", not unexpected, unexpected[:3]
            )

        by_attempt = Counter(
            (item["program_job_id"], item["attempt"])
            for item in ledger
            if item["event"] == "start"
        )
        successes = Counter(
            item["job_key"] for item in ledger if item["event"] == "end"
        )
        dup_attempts = [
            f"{key[0]}#{key[1]}" for key, count in by_attempt.items() if count > 1
        ]
        dup_success = [key for key, count in successes.items() if count > 1]
        overlapping = _overlapping_executions(ledger, args.lease_seconds)
        self.check(
            "zero_duplicate_executions",
            not dup_attempts and not dup_success and not overlapping,
            {
                "duplicate_attempt_starts": dup_attempts,
                "duplicate_successful_executions": dup_success,
                "overlapping_or_early_reexecutions": overlapping[:5],
                "executions": sum(by_attempt.values()),
            },
        )

        # Every job's durable completion matches exactly one successful execution.
        delivered = {k for k, v in jobs.items() if v["outcome"] == "DELIVERED"}
        self.check(
            "durable_outcomes_match_ledger",
            delivered == set(successes),
            {
                "delivered_without_execution": sorted(delivered - set(successes)),
                "executed_without_delivery": sorted(set(successes) - delivered),
            },
        )

        slow = jobs.get("slow-recovered", {})
        slow_starts = sorted(
            (
                i
                for i in ledger
                if i["job_key"] == "slow-recovered" and i["event"] == "start"
            ),
            key=lambda i: i["t"],
        )
        recovered_start = next((i for i in slow_starts if i["attempt"] == 2), None)
        victim_lease_expiry = (
            slow_starts[0]["t"] + args.lease_seconds if slow_starts else None
        )
        self.check(
            "dead_worker_job_recovered",
            (
                slow.get("outcome") == "DELIVERED"
                and slow.get("attempt_count") == 2
                and len(slow_starts) == 2
                and slow_starts[0]["worker_id"] == "autproof-victim"
                and recovered_start is not None
                and recovered_start["worker_id"].startswith("autproof-supervisor-")
                and recovered_start["t"] >= (victim_lease_expiry or 0) - 1.0
            ),
            {
                "attempts": [(i["attempt"], i["worker_id"]) for i in slow_starts],
                "recovered_after_lease_expiry_s": round(
                    recovered_start["t"] - victim_lease_expiry, 2
                )
                if recovered_start and victim_lease_expiry
                else None,
                "final": {
                    k: slow.get(k) for k in ("status", "outcome", "attempt_count")
                },
            },
        )

        fail_503 = next(
            (
                i
                for i in ledger
                if i["job_key"] == "provider-503-once" and i["event"] == "fail"
            ),
            None,
        )
        retry_503 = next(
            (
                i
                for i in ledger
                if i["job_key"] == "provider-503-once" and i["event"] == "end"
            ),
            None,
        )
        between = [
            i["job_key"]
            for i in ledger
            if i["event"] == "end"
            and fail_503
            and retry_503
            and fail_503["t"] < i["t"] < retry_503["t"]
        ]
        failing_worker = fail_503["worker_id"] if fail_503 else None
        failing_sup = next(
            (s for s in self.supervisors if s.worker_id == failing_worker), None
        )
        later_cycles = (
            [c for c in failing_sup.cycles() if c["t"] > fail_503["t"]]
            if failing_sup and fail_503
            else []
        )
        provider = jobs.get("provider-503-once", {})
        self.check(
            "provider_failure_does_not_stall_other_jobs",
            (
                fail_503 is not None
                and fail_503["code"] == FAKE_503_CODE
                and provider.get("outcome") == "DELIVERED"
                and provider.get("attempt_count") == 2
                and len(between) >= 1
                and len(later_cycles) >= 1
                and jobs.get("provider-ok-0", {}).get("outcome") == "DELIVERED"
                and jobs.get("provider-ok-1", {}).get("outcome") == "DELIVERED"
            ),
            {
                "failing_worker": failing_worker,
                "jobs_completed_while_503_job_waited": len(between),
                "failing_supervisor_cycles_after_failure": len(later_cycles),
                "final": {
                    k: provider.get(k) for k in ("status", "outcome", "attempt_count")
                },
            },
        )

        dead = jobs.get("dead-always-fails", {})
        dead_fails = sorted(
            i["attempt"]
            for i in ledger
            if i["job_key"] == "dead-always-fails" and i["event"] == "fail"
        )
        self.check(
            "dead_letter_after_max_attempts",
            (
                dead.get("outcome") == "DEAD_LETTER"
                and dead.get("status") == "blocked"
                and dead.get("blocker") == "PROGRAM_JOB_ATTEMPTS_EXHAUSTED"
                and dead.get("attempt_count") == dead.get("max_attempts") == 3
                and dead_fails == [1, 2, 3]
            ),
            {
                "failed_attempts": dead_fails,
                "final": {
                    k: dead.get(k)
                    for k in ("status", "outcome", "attempt_count", "blocker")
                },
            },
        )
        downstream = jobs.get("dead-downstream", {})
        never_ran = not any(i["job_key"] == "dead-downstream" for i in ledger)
        # TODO(D6): once a dead-letter refreshes program status and blocks
        # dependants, require programs["deadletter"] == "blocked" and
        # downstream outcome == "BLOCKED" (UPSTREAM_JOB_FAILED) here.
        self.check(
            "dead_letter_dependant_never_executed",
            never_ran and downstream.get("outcome") in (None, "BLOCKED"),
            {
                "downstream": {k: downstream.get(k) for k in ("status", "outcome")},
                "program_status": programs.get("deadletter"),
            },
        )
        if programs.get("deadletter") == "running":
            self.defects.append(
                {
                    "id": "D6",
                    "observed": "dead-lettered job left its program 'running' and its dependant "
                    f"'{downstream.get('status')}' (recover_expired_leases does not refresh program status)",
                }
            )

        error_cycles = [
            (sup.name, c["record"]["cycle"])
            for sup in self.supervisors
            for c in sup.cycles()
            if c["record"]["cycle"].get("stop_reason") == "error"
        ]
        # TODO(D7): once one executor error no longer ends the cycle, require
        # that no injected fault produces stop_reason == "error" and that the
        # failing cycle continues to other runnable jobs.
        if error_cycles:
            self.defects.append(
                {
                    "id": "D7",
                    "observed": f"{len(error_cycles)} cycle(s) ended at an injected executor error "
                    "(stop_reason='error'): run_deterministic_program_cycle returns on the first "
                    "executor exception instead of continuing to other runnable jobs",
                    "codes": sorted(
                        {
                            str((c.get("error") or {}).get("code"))
                            for _, c in error_cycles
                        }
                    ),
                }
            )

        mid = [k for k in jobs if k.startswith("midrun-")]
        mid_ok = len(mid) == 3 and all(
            jobs[k]["outcome"] == "DELIVERED" and jobs[k]["attempt_count"] == 1
            for k in mid
        )
        mid_after = all(
            i["t"] > getattr(self, "mid_run_enqueue_at", float("inf"))
            for i in ledger
            if i["job_key"].startswith("midrun-")
        )
        self.check(
            "mid_run_enqueue_completed_autonomously",
            mid_ok and mid_after,
            {"jobs": {k: jobs[k]["outcome"] for k in mid}},
        )

        normal = [
            k
            for k in jobs
            if k.startswith(("chain-", "parallel-", "midrun-", "provider-ok-"))
        ]
        self.check(
            "durable_state_changed_as_expected",
            (
                bool(normal)
                and all(
                    jobs[k]["status"] == "completed" and jobs[k]["attempt_count"] == 1
                    for k in normal
                )
                and all(
                    v["lease_token"] is None and v["lease_owner"] is None
                    for v in jobs.values()
                    if v["outcome"]
                )
                and all(
                    programs.get(n) == "completed"
                    for n in ("chain", "parallel", "provider", "slow", "midrun")
                )
                and all(
                    (v["evidence"] or {}).get("receipt_type") == "execution"
                    for v in jobs.values()
                    if v["outcome"] == "DELIVERED"
                )
            ),
            {"programs": programs, "normal_jobs": len(normal)},
        )

        blocked_net = [
            item for item in netlog if not item["kind"].startswith("selftest")
        ]
        selftests = [item for item in netlog if item["kind"] == "selftest"]
        expected_children = len(self.supervisors) + (1 if self.victim else 0)
        self.check(
            "no_network_calls",
            not blocked_net
            and len(selftests) >= expected_children
            and all(s["blocked"] for s in selftests),
            {
                "blocked_attempts": blocked_net[:5],
                "guard_selftests_blocked": sum(1 for s in selftests if s["blocked"]),
                "processes_guarded": expected_children,
            },
        )
        harness_ran_cycles = any(
            name in sys.modules
            for name in (
                "runtime.program_autonomy_worker",
                "app.calyx_orchestrator.program_cycle",
            )
        )
        self.check(
            "harness_never_invoked_the_cycle",
            not harness_ran_cycles,
            sorted(
                n
                for n in (
                    "runtime.program_autonomy_worker",
                    "app.calyx_orchestrator.program_cycle",
                )
                if n in sys.modules
            ),
        )

        status = (
            "PASS"
            if self.assertions and all(a["passed"] for a in self.assertions)
            else "FAIL"
        )
        report = {
            "schema": EVIDENCE_SCHEMA,
            "status": status,
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
            },
            "cycle_source": "each supervisor's own per-cycle JSON stdout records emitted by runtime.program_autonomy_worker.main()",
            "supervisors": supervisor_evidence,
            "victim": {
                "worker_id": self.victim.worker_id if self.victim else None,
                "returncode": self.victim.process.returncode if self.victim else None,
                "cycles_emitted_before_kill": len(self.victim.cycles())
                if self.victim
                else 0,
            },
            "executions": {
                "starts": sum(1 for i in ledger if i["event"] == "start"),
                "successes": sum(1 for i in ledger if i["event"] == "end"),
                "injected_failures": sum(1 for i in ledger if i["event"] == "fail"),
            },
            "jobs": {
                k: {
                    f: v[f]
                    for f in (
                        "role_key",
                        "status",
                        "outcome",
                        "attempt_count",
                        "blocker",
                    )
                }
                for k, v in sorted(jobs.items())
            },
            "programs": programs,
            "assertions": self.assertions,
            "defects_observed": self.defects,
            "timeline": [{**item, "t": round(item["t"], 2)} for item in self.timeline],
            "network": {
                "blocked_attempts": len(blocked_net),
                "guard_selftests": len(selftests),
            },
        }
        return report


def _parse(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--supervisor-child", action="store_true", help=argparse.SUPPRESS
    )
    parser.add_argument(
        "--dsn",
        default=os.environ.get("TEST_DATABASE_URL"),
        help="loopback PostgreSQL DSN",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("artifacts/program-autonomy-timer-proof.json"),
    )
    parser.add_argument("--supervisors", type=int, default=2)
    parser.add_argument("--target-cycles", type=int, default=10)
    parser.add_argument("--poll-seconds", type=int, default=15)
    parser.add_argument("--lease-seconds", type=int, default=60)
    parser.add_argument("--max-jobs-per-cycle", type=int, default=2)
    parser.add_argument("--mid-run-after-cycles", type=int, default=3)
    parser.add_argument("--deadline-seconds", type=int, default=600)
    parser.add_argument("--workdir", default=None)
    parser.add_argument("--keep-workdir", action="store_true")
    args = parser.parse_args(argv)
    if args.supervisor_child:
        return args
    if not args.dsn:
        parser.error("--dsn or TEST_DATABASE_URL is required")
    if args.supervisors < 2:
        parser.error("--supervisors must be >= 2")
    if args.target_cycles < 10:
        parser.error("--target-cycles must be >= 10")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse(argv)
    if args.supervisor_child:
        return _supervisor_child()
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
        except Exception as exc:  # noqa: BLE001 - a leftover disposable schema is reported, not fatal
            print(
                f"schema cleanup failed: {type(exc).__name__}: {exc}", file=sys.stderr
            )
    if report.get("status") != "PASS":
        tails = {}
        for path in sorted(proof.workdir.glob("*.stderr.log")):
            tails[path.name] = path.read_text(encoding="utf-8", errors="replace")[
                -2000:
            ]
        report["stderr_tails"] = tails
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    summary = {
        "status": report.get("status"),
        "cycles": {s["name"]: s["cycles"] for s in report.get("supervisors", [])},
        "duration_seconds": report.get("duration_seconds"),
        "failed": [a["name"] for a in report.get("assertions", []) if not a["passed"]],
        "defects_observed": [d["id"] for d in report.get("defects_observed", [])],
        "output": str(args.output),
    }
    print(json.dumps(summary, sort_keys=True))
    if not args.keep_workdir and args.workdir is None:
        for path in proof.workdir.glob("*"):
            path.unlink()
        proof.workdir.rmdir()
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
