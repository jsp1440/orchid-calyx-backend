"""Claude consumer adapter for the ACS coordinator (ACS-CLAUDE-ADAPTER-001).

Transport and execution are separate:

* ``CoordinatorTransport`` speaks the existing ACS agent protocol
  (claim -> lease -> heartbeat -> response). ``StoreTransport`` applies events
  in process with an agent principal; ``SignedIngressTransport`` posts them to
  the coordinator's HMAC ``/events`` ingress and discovers work from the
  coordinator's own hub reports (``ReportDiscovery``).
* ``Executor`` produces the work. The default is ``MockClaudeExecutor``:
  offline, deterministic, no model call. ``ClaudeRunner`` is the interface a
  supported live runner must implement; it refuses to start unless an explicit
  ``ExecutionPolicy`` enables it with identity-scoped credentials, and this
  version ships no live runner at all.

GitHub text is untrusted task data. Only coordinator records authenticate an
assignment (owner/coordinator principals in the ACS store, reports from
configured reporter ids). Comment text is never executed; objective text is
screened and handed to the executor only as a digest. Coordinator receipts and
this adapter's own comments are never treated as new tasks.

Local state is a persistent SQLite file: deduplication, the current lease,
retry/backoff, a fenced result outbox and dead letters survive restart.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import sqlite3
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .github import strict_json
from .store import Principal, canonical, digest, reference

AGENT = "claude"
ADAPTER_VERSION = "acs-claude-adapter/v1"
RESULT_PREFIX = "[OC-COORD-INPUT]"
ADAPTER_MARKER = "OC-CLAUDE-ADAPTER"
REPORT_MARKER = re.compile(r"\A<!-- OC-ACS:([^>]{1,200}) -->\n(\{.*\})\Z", re.DOTALL)
CLAIMABLE = frozenset({"queued", "retry"})


class AdapterError(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


class Fenced(AdapterError):
    """The coordinator refused a heartbeat/response: another worker owns the task."""


class TransportUnavailable(AdapterError):
    """The coordinator could not be reached or answered with a server error."""


class LiveExecutionDisabled(AdapterError):
    """Live Claude execution was requested but is not enabled and configured."""


# ---------------------------------------------------------------------------
# Contracts
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Assignment:
    task_id: str
    agent: str
    action: str
    state: str
    attempts: int
    source: str  # "store" | "github_report:<comment id>"
    objective: str = ""


@dataclass
class Lease:
    task_id: str
    attempt: int
    token: str
    lease_until: float
    deadline: float
    objective: str
    action: str


@dataclass(frozen=True)
class ExecutionPolicy:
    live_enabled: bool = False
    max_concurrent: int = 1
    max_executions_per_day: int = 10
    allowed_actions: frozenset = frozenset({"engineering"})
    allowed_capabilities: frozenset = frozenset(
        {"write_repository_artifact", "run_offline_checks"}
    )
    max_local_retries: int = 3
    backoff_base: float = 10.0
    backoff_cap: float = 300.0
    deadline_margin: float = 5.0

    def __post_init__(self):
        if self.max_concurrent != 1:
            # One lease at a time keeps fencing auditable; raise only with a
            # reviewed scheduler change, never by configuration alone.
            raise ValueError("CONCURRENCY_LIMIT_IS_ONE")
        if self.max_executions_per_day < 0 or self.max_local_retries < 1:
            raise ValueError("INVALID_LIMITS")
        if not self.allowed_actions <= {"engineering"}:
            raise ValueError("PRIVILEGED_ACTIONS_NOT_ALLOWED")


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    attempt: int
    objective: str
    objective_digest: str
    capabilities: frozenset
    workdir: Path


@dataclass
class ExecutionResult:
    artifacts: list
    checks: dict
    summary: str

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(self.checks.values())


class CoordinatorTransport(Protocol):
    def discover(self, limit: int) -> list: ...

    def claim(self, task_id: str, event_id: str) -> Lease: ...

    def heartbeat(self, lease: Lease, event_id: str) -> float: ...

    def respond(self, lease: Lease, outcome: str, ref: str, event_id: str) -> dict: ...


class Executor(Protocol):
    name: str

    def start(self, spec: TaskSpec) -> ExecutorJob: ...


class ExecutorJob(Protocol):
    def step(self) -> bool: ...  # True when finished

    def result(self) -> ExecutionResult: ...

    def cancel(self) -> None: ...


# ---------------------------------------------------------------------------
# Untrusted text
# ---------------------------------------------------------------------------

_INJECTION = (
    (
        "SHELL_BLOCK",
        re.compile(r"```\s*(?:bash|sh|shell|zsh|powershell|cmd)\b", re.IGNORECASE),
    ),
    (
        "PIPE_TO_SHELL",
        re.compile(r"\b(?:curl|wget)\b[^\n|]*\|\s*(?:ba)?sh\b", re.IGNORECASE),
    ),
    (
        "DESTRUCTIVE_COMMAND",
        re.compile(r"\brm\s+-rf\b|\bdrop\s+table\b|--force\b", re.IGNORECASE),
    ),
    (
        "INSTRUCTION_OVERRIDE",
        re.compile(
            r"\b(?:ignore|disregard)\s+(?:all\s+)?(?:previous|prior|above)\s+instructions\b",
            re.IGNORECASE,
        ),
    ),
    (
        "CREDENTIAL_REQUEST",
        re.compile(
            r"\b(?:print|reveal|send|post|echo|exfiltrate)\b[^\n]{0,40}"
            r"\b(?:token|secret|password|api[ _-]?key|credential)s?\b",
            re.IGNORECASE,
        ),
    ),
    (
        "GATED_ACTION",
        re.compile(
            r"\b(?:merge (?:this|the) (?:pr|pull request)|deploy to production|"
            r"force[- ]push|enable paid|run the migration)\b",
            re.IGNORECASE,
        ),
    ),
)


def screen_untrusted(text: str) -> list:
    """Reasons an objective text must not reach an executor (empty list if none)."""
    if not isinstance(text, str):
        return ["NOT_TEXT"]
    return sorted({code for code, rx in _INJECTION if rx.search(text)})


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------


class StoreTransport:
    """In-process transport: the adapter acts as the ``agent:claude`` principal."""

    def __init__(self, store, principal: Principal | None = None):
        self.store = store
        self.principal = principal or Principal("agent", AGENT)
        if self.principal.role != "agent" or self.principal.name != AGENT:
            raise ValueError("CLAUDE_AGENT_PRINCIPAL_REQUIRED")

    def discover(self, limit: int) -> list:
        now = self.store.clock()
        with self.store.transaction() as conn:
            rows = self.store.sql(
                conn,
                """SELECT id, agent, action, state, attempts, objective FROM acs_tasks
                WHERE agent=? AND (state IN ('queued','retry','owner_gate')) AND available_at<=?
                ORDER BY available_at, id LIMIT ?""",
                (AGENT, now, int(limit)),
            ).fetchall()
        return [
            Assignment(
                r["id"],
                r["agent"],
                r["action"],
                r["state"],
                r["attempts"],
                "store",
                r["objective"],
            )
            for r in rows
        ]

    def _apply(self, event: dict) -> dict:
        try:
            return self.store.apply(event, self.principal)
        except PermissionError as exc:
            raise Fenced(str(exc)) from None
        except ValueError as exc:
            raise AdapterError(str(exc)) from None

    def claim(self, task_id: str, event_id: str) -> Lease:
        row = self._apply(
            {"version": 1, "event_id": event_id, "task_id": task_id, "kind": "claim"}
        )
        return Lease(
            task_id,
            row["attempts"],
            row["lease_token"],
            row["lease_until"],
            row["deadline"],
            row["objective"],
            row["action"],
        )

    def heartbeat(self, lease: Lease, event_id: str) -> float:
        row = self._apply(
            {
                "version": 1,
                "event_id": event_id,
                "task_id": lease.task_id,
                "kind": "heartbeat",
                "lease_token": lease.token,
            }
        )
        return row["lease_until"]

    def respond(self, lease: Lease, outcome: str, ref: str, event_id: str) -> dict:
        return self._apply(
            {
                "version": 1,
                "event_id": event_id,
                "task_id": lease.task_id,
                "kind": "response",
                "lease_token": lease.token,
                "outcome": outcome,
                "reference": ref,
            }
        )


class ReportDiscovery:
    """Claude assignments from the coordinator's public hub reports.

    Only comments authored by configured reporter ids and carrying the exact
    ``<!-- OC-ACS:... -->`` + canonical JSON projection count. Anything else
    (a self-declared "Claude", an ``[OC-COORD-AUTO]`` receipt, this adapter's
    own results) is ignored, so no comment can mint work or loop back.
    """

    def __init__(self, github, reporter_ids):
        if not reporter_ids or any(type(i) is not int or i < 1 for i in reporter_ids):
            raise ValueError("REPORTER_IDS_REQUIRED")
        self.github = github
        self.reporter_ids = frozenset(reporter_ids)

    def discover(self, limit: int) -> list:
        latest: dict[str, tuple[int, dict]] = {}
        for comment in self.github.comments():
            if (
                comment.get("user", {}).get("id") not in self.reporter_ids
                or type(comment.get("id")) is not int
            ):
                continue
            m = REPORT_MARKER.match(comment.get("body") or "")
            if not m:
                continue
            try:
                body = strict_json(m.group(2))
            except ValueError:
                continue
            if not isinstance(body, dict) or set(body) != {
                "version",
                "task_id",
                "agent",
                "state",
                "reason",
                "action",
                "attempts",
            }:
                continue
            if (
                body["agent"] != AGENT
                or body["version"] != 1
                or canonical(body) != m.group(2)
            ):
                continue
            prev = latest.get(body["task_id"])
            if prev is None or prev[0] < comment["id"]:
                latest[body["task_id"]] = (comment["id"], body)
        out = []
        for task_id, (cid, body) in sorted(latest.items(), key=lambda kv: kv[1][0]):
            if body["state"] in CLAIMABLE | {"owner_gate"}:
                out.append(
                    Assignment(
                        task_id,
                        AGENT,
                        body["action"],
                        body["state"],
                        body["attempts"],
                        f"github_report:{cid}",
                    )
                )
        return out[:limit]


class SignedIngressTransport:
    """HMAC-signed events to the coordinator ingress (``X-ACS-Key`` etc.).

    The key must be an agent-only identity for ``claude`` issued by the
    owner; it is never an owner credential. ``from_env`` returns ``None`` when
    no key is provisioned, so the adapter reports that blocker instead of
    guessing.
    """

    def __init__(
        self,
        url: str,
        key_id: str,
        secret: str,
        discovery: ReportDiscovery,
        *,
        opener=None,
        clock=time.time,
    ):
        if not re.fullmatch(
            r"(?:https://[^\s/]+|http://127\.0\.0\.1:\d{1,5})/events", url or ""
        ):
            raise ValueError("INGRESS_URL_MUST_BE_TLS_OR_LOOPBACK")
        if not key_id or len(secret or "") < 32:
            raise ValueError("AGENT_KEY_REQUIRED")
        self.url, self.key_id, self.secret = url, key_id, secret
        self.discovery = discovery
        self.opener = opener or urllib.request.build_opener()
        self.clock = clock

    @classmethod
    def from_env(cls, env, discovery):
        url, key_id, secret = (
            env.get("ACS_CLAUDE_INGRESS_URL"),
            env.get("ACS_CLAUDE_KEY_ID"),
            env.get("ACS_CLAUDE_KEY_SECRET"),
        )
        if not (url and key_id and secret):
            return None
        return cls(url, key_id, secret, discovery)

    def discover(self, limit: int) -> list:
        return self.discovery.discover(limit)

    def _post(self, event: dict) -> dict:
        body = canonical(event).encode()
        ts = f"{self.clock():.3f}"
        sig = hmac.new(
            self.secret.encode(), ts.encode() + b"." + body, hashlib.sha256
        ).hexdigest()
        req = urllib.request.Request(
            self.url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-ACS-Key": self.key_id,
                "X-ACS-Time": ts,
                "X-ACS-Signature": sig,
                "User-Agent": ADAPTER_VERSION,
            },
        )
        try:
            with self.opener.open(req, timeout=20) as resp:
                return strict_json(resp.read(65536))
        except urllib.error.HTTPError as exc:
            if exc.code == 403:
                raise Fenced("AUTHORITY_OR_LEASE_REFUSED") from None
            if exc.code == 400:
                raise AdapterError("EVENT_REFUSED") from None
            raise TransportUnavailable(f"HTTP_{exc.code}") from None
        except (OSError, ValueError):
            raise TransportUnavailable("INGRESS_UNREACHABLE") from None

    def claim(self, task_id: str, event_id: str) -> Lease:
        row = self._post(
            {"version": 1, "event_id": event_id, "task_id": task_id, "kind": "claim"}
        )
        return Lease(
            task_id,
            row["attempts"],
            row["lease_token"],
            row["lease_until"],
            row["deadline"],
            row["objective"],
            row["action"],
        )

    def heartbeat(self, lease: Lease, event_id: str) -> float:
        return self._post(
            {
                "version": 1,
                "event_id": event_id,
                "task_id": lease.task_id,
                "kind": "heartbeat",
                "lease_token": lease.token,
            }
        )["lease_until"]

    def respond(self, lease: Lease, outcome: str, ref: str, event_id: str) -> dict:
        return self._post(
            {
                "version": 1,
                "event_id": event_id,
                "task_id": lease.task_id,
                "kind": "response",
                "lease_token": lease.token,
                "outcome": outcome,
                "reference": ref,
            }
        )


# ---------------------------------------------------------------------------
# Executors
# ---------------------------------------------------------------------------


class MockClaudeExecutor:
    """Offline stand-in for Claude: writes one bounded artifact and checks it.

    ``steps`` simulates work length; ``on_step`` lets tests advance a clock or
    inject a crash; ``hang=True`` never finishes (timeout tests).
    """

    name = "mock-claude-offline"
    MAX_ARTIFACT_BYTES = 4096

    def __init__(
        self,
        *,
        steps: int = 3,
        hang: bool = False,
        on_step=None,
        fail_checks: bool = False,
    ):
        self.steps, self.hang, self.on_step, self.fail_checks = (
            steps,
            hang,
            on_step,
            fail_checks,
        )
        self.started: list = []

    def start(self, spec: TaskSpec) -> _MockJob:
        if not spec.capabilities <= {"write_repository_artifact", "run_offline_checks"}:
            raise AdapterError("CAPABILITY_NOT_SUPPORTED_BY_MOCK")
        self.started.append((spec.task_id, spec.attempt))
        return _MockJob(self, spec)


class _MockJob:
    def __init__(self, executor: MockClaudeExecutor, spec: TaskSpec):
        self.ex, self.spec, self.done_steps, self.cancelled = executor, spec, 0, False

    def step(self) -> bool:
        if self.cancelled:
            raise AdapterError("JOB_CANCELLED")
        self.done_steps += 1
        if self.ex.on_step:
            self.ex.on_step(self.spec, self.done_steps)
        if self.ex.hang:
            return False
        return self.done_steps >= self.ex.steps

    def result(self) -> ExecutionResult:
        path = (
            self.spec.workdir
            / "acs"
            / AGENT
            / self.spec.task_id
            / f"attempt-{self.spec.attempt}.md"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        text = (
            f"# {self.spec.task_id} (attempt {self.spec.attempt})\n\n"
            f"Executor: {self.ex.name} (offline; no model call, no network).\n"
            f"Objective reference: {self.spec.objective}\n"
            f"Objective text digest: {self.spec.objective_digest}\n"
        )
        path.write_text(text, encoding="utf-8")
        data = path.read_bytes()
        checks = {
            "artifact_bounded": len(data) <= MockClaudeExecutor.MAX_ARTIFACT_BYTES,
            "artifact_inside_workdir": self.spec.workdir.resolve()
            in path.resolve().parents,
            "no_secret_markers": not re.search(
                rb"(?i)(token|secret|password)\s*[:=]", data
            ),
            "objective_is_reference": reference(self.spec.objective),
        }
        if self.ex.fail_checks:
            checks["forced_failure"] = False
        return ExecutionResult(
            [str(path)], checks, f"{len(data)} bytes; offline checks: {sorted(checks)}"
        )

    def cancel(self) -> None:
        self.cancelled = True


class ClaudeRunner:
    """Interface for a supported live Claude runner (none is shipped).

    A real implementation must run Claude with identity-scoped credentials
    that are not owner credentials, inside the task's allowed capabilities,
    and stop on ``cancel``. Construction is refused unless the policy enables
    live execution, credentials and an owner approval reference are given;
    even then this base class has no runner and refuses to start.
    """

    name = "claude-live-runner"

    def __init__(
        self,
        policy: ExecutionPolicy,
        *,
        credential_ref: str | None,
        approval_ref: str | None,
    ):
        if not policy.live_enabled:
            raise LiveExecutionDisabled("LIVE_EXECUTION_DISABLED_BY_POLICY")
        if not credential_ref or not approval_ref or not reference(approval_ref):
            raise LiveExecutionDisabled(
                "IDENTITY_SCOPED_CREDENTIAL_AND_OWNER_APPROVAL_REQUIRED"
            )
        self.policy = policy

    def start(self, spec: TaskSpec):
        raise LiveExecutionDisabled("NO_SUPPORTED_LIVE_RUNNER_CONFIGURED")


# ---------------------------------------------------------------------------
# Durable local state
# ---------------------------------------------------------------------------

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS seen (key TEXT PRIMARY KEY, at REAL NOT NULL)",
    """CREATE TABLE IF NOT EXISTS work (task_id TEXT PRIMARY KEY, attempt INTEGER, state TEXT NOT NULL,
    token TEXT, lease_until REAL, deadline REAL, objective TEXT, action TEXT, artifact TEXT,
    reason TEXT NOT NULL, local_retries INTEGER NOT NULL DEFAULT 0, next_at REAL NOT NULL DEFAULT 0,
    updated REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, body TEXT NOT NULL, state TEXT NOT NULL,
    attempts INTEGER NOT NULL, available_at REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS dead_letters (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, reason TEXT NOT NULL,
    at REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS audit (seq INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL,
    kind TEXT NOT NULL, task_id TEXT, detail TEXT NOT NULL)""",
)
_TERMINAL = frozenset(
    {"responded_delivered", "responded_blocked", "refused", "dead_letter"}
)


class AdapterState:
    def __init__(self, path: str | Path, clock=time.time):
        if not path or str(path) == ":memory:":
            raise ValueError("PERSISTENT_STATE_REQUIRED")
        self.path, self.clock = str(path), clock
        with self.tx() as conn:
            for stmt in _SCHEMA:
                conn.execute(stmt)

    @contextmanager
    def tx(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def audit(self, conn, kind: str, task_id: str | None, **detail) -> None:
        conn.execute(
            "INSERT INTO audit (at,kind,task_id,detail) VALUES (?,?,?,?)",
            (self.clock(), kind, task_id, canonical(detail)),
        )

    def seen(self, key: str) -> bool:
        with self.tx() as conn:
            return (
                conn.execute("SELECT 1 FROM seen WHERE key=?", (key,)).fetchone()
                is not None
            )

    def mark_seen(self, key: str) -> bool:
        """True the first time ``key`` is seen; False for a duplicate/replay."""
        with self.tx() as conn:
            if conn.execute("SELECT 1 FROM seen WHERE key=?", (key,)).fetchone():
                return False
            conn.execute("INSERT INTO seen (key,at) VALUES (?,?)", (key, self.clock()))
            return True

    def work(self, task_id: str) -> dict | None:
        with self.tx() as conn:
            row = conn.execute(
                "SELECT * FROM work WHERE task_id=?", (task_id,)
            ).fetchone()
            return dict(row) if row else None

    def put(self, task_id: str, **fields) -> None:
        now = self.clock()
        with self.tx() as conn:
            row = conn.execute(
                "SELECT * FROM work WHERE task_id=?", (task_id,)
            ).fetchone()
            merged = (
                dict(row)
                if row
                else {
                    "task_id": task_id,
                    "state": "new",
                    "reason": "",
                    "local_retries": 0,
                    "next_at": 0,
                }
            )
            merged.update(fields, updated=now)
            cols = [
                "task_id",
                "attempt",
                "state",
                "token",
                "lease_until",
                "deadline",
                "objective",
                "action",
                "artifact",
                "reason",
                "local_retries",
                "next_at",
                "updated",
            ]
            conn.execute(
                f"INSERT OR REPLACE INTO work ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                tuple(merged.get(c) for c in cols),
            )
            self.audit(
                conn, "work", task_id, state=merged["state"], reason=merged["reason"]
            )

    def active(self) -> list:
        with self.tx() as conn:
            return [
                dict(r)
                for r in conn.execute(
                    "SELECT * FROM work WHERE state IN ('claimed','running')"
                )
            ]

    def executions_since(self, since: float) -> int:
        with self.tx() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM audit WHERE kind='execution_started' AND at>=?",
                (since,),
            ).fetchone()[0]

    def log(self, kind: str, task_id: str | None, **detail) -> None:
        with self.tx() as conn:
            self.audit(conn, kind, task_id, **detail)

    def dead_letter(self, task_id: str, reason: str, key: str) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO dead_letters (id,task_id,reason,at) VALUES (?,?,?,?)",
                (key, task_id, reason, self.clock()),
            )
            self.audit(conn, "dead_letter", task_id, reason=reason)

    def dead_letters(self) -> list:
        with self.tx() as conn:
            return [
                dict(r) for r in conn.execute("SELECT * FROM dead_letters ORDER BY id")
            ]

    def enqueue(self, marker: str, body: str) -> None:
        with self.tx() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO outbox (id,body,state,attempts,available_at) VALUES (?,?,?,0,?)",
                (marker, body, "pending", self.clock()),
            )

    def outbox(self) -> list:
        with self.tx() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM outbox ORDER BY id")]

    def audit_log(self) -> list:
        with self.tx() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM audit ORDER BY seq")]


# ---------------------------------------------------------------------------
# Result publishing (canonical PR) with ambiguous-POST reconciliation
# ---------------------------------------------------------------------------


class ResultPublisher:
    """Posts receipts/results to the adapter's canonical PR.

    Each message carries a stable marker. Before every POST the PR is re-read:
    if an identical marked comment from the reporter identity already exists,
    the earlier (ambiguous) POST is reconciled instead of posting twice.
    """

    def __init__(
        self, github_pr, reporter_ids, state: AdapterState, *, max_attempts: int = 3
    ):
        self.github, self.reporter_ids, self.state, self.max_attempts = (
            github_pr,
            frozenset(reporter_ids),
            state,
            max_attempts,
        )

    def flush(self) -> dict:
        counts = {"sent": 0, "reconciled": 0, "failed": 0, "dead_letter": 0}
        now = self.state.clock()
        for item in self.state.outbox():
            if item["state"] in {"sent", "dead_letter"} or item["available_at"] > now:
                continue
            try:
                present = any(
                    c.get("body") == item["body"]
                    and c.get("user", {}).get("id") in self.reporter_ids
                    for c in self.github.comments()
                )
                if present:
                    new_state, key = "sent", "reconciled"
                elif item["attempts"] >= self.max_attempts:
                    new_state, key = "dead_letter", "dead_letter"
                else:
                    self._bump(item["id"], item["attempts"] + 1, "sending", now)
                    self.github.post(item["body"])
                    new_state, key = "sent", "sent"
                self._bump(item["id"], None, new_state, now)
                if new_state == "dead_letter":
                    self.state.dead_letter(
                        item["id"],
                        "RESULT_DELIVERY_UNCONFIRMED",
                        f"outbox:{item['id']}",
                    )
                counts[key] += 1
            except (OSError, ValueError):
                attempts = item["attempts"] + 1
                self._bump(
                    item["id"],
                    attempts,
                    "uncertain",
                    now + min(300, 10 * 2 ** (attempts - 1)),
                )
                counts["failed"] += 1
        return counts

    def _bump(
        self, oid: str, attempts: int | None, state: str, available_at: float
    ) -> None:
        with self.state.tx() as conn:
            if attempts is None:
                conn.execute("UPDATE outbox SET state=? WHERE id=?", (state, oid))
            else:
                conn.execute(
                    "UPDATE outbox SET attempts=?, state=?, available_at=? WHERE id=?",
                    (attempts, state, available_at, oid),
                )


def result_body(marker_id: str, payload: dict) -> str:
    return (
        f"<!-- {ADAPTER_MARKER}:{marker_id} -->\n{RESULT_PREFIX} {payload['type']}: {payload['task_id']}\n\n"
        "```json\n" + canonical(payload) + "\n```"
    )


# ---------------------------------------------------------------------------
# The adapter
# ---------------------------------------------------------------------------


@dataclass
class ClaudeAdapter:
    transport: CoordinatorTransport
    executor: Executor
    state: AdapterState
    publisher: ResultPublisher
    canonical_ref: str
    workdir: Path
    policy: ExecutionPolicy = field(default_factory=ExecutionPolicy)
    objective_reader: object | None = None  # .read(url) -> untrusted text
    kill_switch: Path | None = None
    worker_id: str = "claude-adapter"
    clock: object = time.time

    def __post_init__(self):
        if not reference(self.canonical_ref):
            raise ValueError("CANONICAL_REFERENCE_REQUIRED")
        self.workdir = Path(self.workdir)

    # -- helpers -------------------------------------------------------------
    def killed(self) -> bool:
        return bool(self.kill_switch and Path(self.kill_switch).exists())

    def _eid(self, kind: str, task_id: str, attempt: int, n: int = 0) -> str:
        return f"claude.{self.worker_id}.{kind}.{task_id}.{attempt}.{n}"[:128]

    def _emit(self, kind: str, task_id: str, attempt: int, **fields) -> None:
        payload = {
            "type": kind,
            "task_id": task_id,
            "attempt": attempt,
            "agent": AGENT,
            "adapter": ADAPTER_VERSION,
            "executor": self.executor.name,
            **fields,
        }
        marker_id = f"{kind.lower()}:{task_id}:{attempt}"
        self.state.enqueue(marker_id, result_body(marker_id, payload))

    def _backoff(self, retries: int) -> float:
        return min(
            self.policy.backoff_cap, self.policy.backoff_base * 2 ** max(0, retries - 1)
        )

    # -- one bounded cycle ---------------------------------------------------
    def run_once(self) -> dict:
        report = {
            "claimed": [],
            "delivered": [],
            "blocked": [],
            "refused": [],
            "skipped": [],
            "fenced": [],
            "timed_out": [],
            "dead_letter": [],
            "errors": [],
        }
        if self.killed():
            for w in self.state.active():
                self._cancel(w, report)
            report["status"] = "KILL_SWITCH_ENGAGED"
            report["outbox"] = self.publisher.flush()
            return report
        for w in self.state.active():
            self._recover(w, report)
        try:
            candidates = self.transport.discover(limit=20)
        except TransportUnavailable as exc:
            report["errors"].append(exc.code)
            candidates = []
        for a in candidates:
            if len(report["claimed"]) >= self.policy.max_concurrent:
                break
            self._consider(a, report)
        report["outbox"] = self.publisher.flush()
        report["status"] = "OK"
        return report

    def _consider(self, a: Assignment, report: dict) -> None:
        if a.agent != AGENT:
            return
        local = self.state.work(a.task_id)
        # Deduplicate decisive outcomes only (claimed / refused). A failed claim
        # must stay retryable, so it never consumes the key.
        seen_key = f"{a.source}|{a.task_id}|{a.state}|{a.attempts}"
        if self.state.seen(seen_key):
            report["skipped"].append(a.task_id)
            return
        if a.action not in self.policy.allowed_actions or a.state == "owner_gate":
            self.state.mark_seen(seen_key)
            if not local or local["state"] != "refused":
                self.state.put(
                    a.task_id,
                    state="refused",
                    action=a.action,
                    reason="OWNER_GATED_ZERO_EXECUTION",
                )
                self._emit(
                    "BLOCKED",
                    a.task_id,
                    a.attempts,
                    outcome="refused",
                    reason="OWNER_GATED_ZERO_EXECUTION",
                    action=a.action,
                    executions=0,
                )
            report["refused"].append(a.task_id)
            return
        if local and local["state"] in _TERMINAL and local.get("attempt") == a.attempts:
            report["skipped"].append(a.task_id)
            return
        if local and local["next_at"] > self.clock():
            report["skipped"].append(a.task_id)
            return
        since = self.clock() - 86400
        if self.state.executions_since(since) >= self.policy.max_executions_per_day:
            report["blocked"].append(a.task_id)
            self.state.log(
                "budget_exhausted", a.task_id, limit=self.policy.max_executions_per_day
            )
            return
        try:
            lease = self.transport.claim(
                a.task_id, self._eid("claim", a.task_id, a.attempts + 1)
            )
        except TransportUnavailable as exc:
            retries = (local or {}).get("local_retries", 0) + 1
            if retries > self.policy.max_local_retries:
                self.state.put(
                    a.task_id,
                    state="dead_letter",
                    reason="TRANSPORT_RETRIES_EXHAUSTED",
                    local_retries=retries,
                )
                self.state.dead_letter(
                    a.task_id,
                    "TRANSPORT_RETRIES_EXHAUSTED",
                    f"claim:{a.task_id}:{retries}",
                )
                report["dead_letter"].append(a.task_id)
            else:
                self.state.put(
                    a.task_id,
                    state="backoff",
                    reason=exc.code,
                    local_retries=retries,
                    next_at=self.clock() + self._backoff(retries),
                )
                report["errors"].append(exc.code)
            return
        except (Fenced, AdapterError) as exc:
            self.state.log("claim_refused", a.task_id, code=exc.code)
            report["skipped"].append(a.task_id)
            return
        self.state.mark_seen(seen_key)
        self.state.put(
            a.task_id,
            state="claimed",
            attempt=lease.attempt,
            token=lease.token,
            lease_until=lease.lease_until,
            deadline=lease.deadline,
            objective=lease.objective,
            action=lease.action,
            reason="claimed",
            local_retries=0,
            next_at=0,
        )
        report["claimed"].append(a.task_id)
        self._emit(
            "RECEIPT",
            a.task_id,
            lease.attempt,
            source=a.source,
            executor_mode="mock_offline" if not self.policy.live_enabled else "live",
        )
        self._execute(lease, report)

    def _spec(self, lease: Lease, text: str) -> TaskSpec:
        return TaskSpec(
            lease.task_id,
            lease.attempt,
            lease.objective,
            hashlib.sha256(text.encode()).hexdigest(),
            self.policy.allowed_capabilities,
            self.workdir,
        )

    def _execute(self, lease: Lease, report: dict) -> None:
        text = ""
        if self.objective_reader is not None:
            try:
                text = self.objective_reader.read(lease.objective)
            except (OSError, ValueError):
                self._respond(
                    lease,
                    "blocked",
                    "OBJECTIVE_UNREADABLE_ZERO_EXECUTION",
                    report,
                    executions=0,
                )
                return
            reasons = screen_untrusted(text)
            if reasons:
                self._respond(
                    lease,
                    "blocked",
                    "UNTRUSTED_INSTRUCTIONS_REJECTED",
                    report,
                    executions=0,
                    screen=reasons,
                )
                return
        self.state.put(lease.task_id, state="running", reason="executing")
        self.state.log(
            "execution_started",
            lease.task_id,
            attempt=lease.attempt,
            executor=self.executor.name,
        )
        job = self.executor.start(self._spec(lease, text))
        beats = 0
        while True:
            if self.killed():
                job.cancel()
                self._respond(
                    lease, "blocked", "KILL_SWITCH_ENGAGED", report, executions=1
                )
                return
            if self.clock() >= lease.deadline - self.policy.deadline_margin:
                job.cancel()
                self.state.put(
                    lease.task_id,
                    state="timed_out",
                    reason="ATTEMPT_DEADLINE_REACHED",
                    token=None,
                )
                report["timed_out"].append(lease.task_id)
                return
            done = job.step()
            beats += 1
            try:
                lease.lease_until = self.transport.heartbeat(
                    lease, self._eid("hb", lease.task_id, lease.attempt, beats)
                )
                self.state.put(lease.task_id, lease_until=lease.lease_until)
            except Fenced:
                job.cancel()
                if self.clock() >= lease.deadline:
                    # The attempt deadline passed mid-step: a timeout, not a takeover.
                    self.state.put(
                        lease.task_id,
                        state="timed_out",
                        reason="ATTEMPT_DEADLINE_REACHED",
                        token=None,
                    )
                    report["timed_out"].append(lease.task_id)
                    return
                self.state.put(
                    lease.task_id,
                    state="fenced",
                    reason="LEASE_LOST_RESULT_DISCARDED",
                    token=None,
                )
                report["fenced"].append(lease.task_id)
                return
            except TransportUnavailable as exc:
                report["errors"].append(
                    exc.code
                )  # lease may still be valid; keep working until deadline
            if done:
                break
        result = job.result()
        artifact = result.artifacts[0] if result.artifacts else ""
        self.state.put(lease.task_id, artifact=artifact)
        outcome = "delivered" if result.passed else "blocked"
        self._respond(
            lease,
            outcome,
            "OFFLINE_CHECKS_PASSED" if result.passed else "OFFLINE_CHECKS_FAILED",
            report,
            executions=1,
            checks=result.checks,
            artifact_sha256=hashlib.sha256(Path(artifact).read_bytes()).hexdigest()
            if artifact
            else "",
        )

    def _respond(
        self, lease: Lease, outcome: str, reason: str, report: dict, **extra
    ) -> None:
        try:
            self.transport.respond(
                lease,
                outcome,
                self.canonical_ref,
                self._eid("resp", lease.task_id, lease.attempt),
            )
        except Fenced:
            self.state.put(
                lease.task_id,
                state="fenced",
                reason="LEASE_LOST_RESULT_DISCARDED",
                token=None,
            )
            report["fenced"].append(lease.task_id)
            return
        except TransportUnavailable as exc:
            # Keep the lease; the response is retried on recovery while the lease is valid.
            self.state.put(
                lease.task_id, state="running", reason="RESPONSE_PENDING:" + exc.code
            )
            report["errors"].append(exc.code)
            return
        self.state.put(
            lease.task_id, state=f"responded_{outcome}", reason=reason, token=None
        )
        self._emit(
            "RESULT",
            lease.task_id,
            lease.attempt,
            outcome=outcome,
            reason=reason,
            reference=self.canonical_ref,
            **extra,
        )
        report["delivered" if outcome == "delivered" else "blocked"].append(
            lease.task_id
        )

    def _recover(self, w: dict, report: dict) -> None:
        """Resume or abandon a lease recorded before a restart."""
        now = self.clock()
        if not w.get("token") or now >= min(w["lease_until"] or 0, w["deadline"] or 0):
            self.state.put(
                w["task_id"],
                state="timed_out",
                reason="RESTART_LEASE_EXPIRED",
                token=None,
            )
            report["timed_out"].append(w["task_id"])
            return
        lease = Lease(
            w["task_id"],
            w["attempt"],
            w["token"],
            w["lease_until"],
            w["deadline"],
            w["objective"],
            w["action"],
        )
        try:
            lease.lease_until = self.transport.heartbeat(
                lease, self._eid("hb-recover", lease.task_id, lease.attempt, int(now))
            )
        except Fenced:
            self.state.put(
                w["task_id"], state="fenced", reason="RESTART_LEASE_FENCED", token=None
            )
            report["fenced"].append(w["task_id"])
            return
        except TransportUnavailable as exc:
            report["errors"].append(exc.code)
            return
        self.state.log("resumed_after_restart", lease.task_id, attempt=lease.attempt)
        report["claimed"].append(lease.task_id)
        self._execute(lease, report)

    def _cancel(self, w: dict, report: dict) -> None:
        if not w.get("token"):
            return
        lease = Lease(
            w["task_id"],
            w["attempt"],
            w["token"],
            w["lease_until"] or 0,
            w["deadline"] or 0,
            w["objective"] or "",
            w["action"] or "",
        )
        self._respond(lease, "blocked", "KILL_SWITCH_ENGAGED", report, executions=0)


# ---------------------------------------------------------------------------
# Live readiness
# ---------------------------------------------------------------------------


def live_readiness(
    *,
    agent_key_configured: bool,
    runner_configured: bool,
    distinct_identity: bool,
    observed_live_result_url: str | None,
) -> dict:
    """Unattended operation may be claimed only when every item is observed."""
    missing = [
        name
        for name, ok in (
            ("agent_only_signed_key", agent_key_configured),
            ("supported_live_runner", runner_configured),
            ("distinct_agent_identity", distinct_identity),
            (
                "observed_live_claude_result",
                bool(observed_live_result_url)
                and reference((observed_live_result_url or "").split("#")[0]),
            ),
        )
        if not ok
    ]
    return {"ready": not missing, "missing": missing}


def assignment_digest(task_id: str, agent: str, objective: str, action: str) -> str:
    """Same digest the coordinator binds owner approvals to."""
    return digest(
        {"task_id": task_id, "agent": agent, "objective": objective, "action": action}
    )


# ---------------------------------------------------------------------------
# Operator CLI (mock executor only; live execution is refused)
# ---------------------------------------------------------------------------


def main(argv=None) -> int:
    import argparse
    import os

    from .store import Store

    parser = argparse.ArgumentParser(
        prog="python -m coordination.claude_adapter",
        description="Claude consumer adapter (offline mock executor)",
    )
    parser.add_argument("command", choices=("once", "status", "readiness"))
    parser.add_argument("--state", required=True, help="Persistent adapter SQLite file")
    parser.add_argument(
        "--coordinator-sqlite", help="Co-located ACS store (StoreTransport)"
    )
    parser.add_argument(
        "--workdir", default=".", help="Directory for bounded artifacts"
    )
    parser.add_argument(
        "--canonical-ref",
        default="https://github.com/jsp1440/orchid-calyx-backend/pull/1836",
    )
    parser.add_argument(
        "--kill-switch", help="Path whose existence stops claims and cancels work"
    )
    parser.add_argument(
        "--live", action="store_true", help="Refused: no live runner is configured"
    )
    args = parser.parse_args(argv)
    state = AdapterState(args.state)
    if args.command == "status":
        print(
            canonical(
                {
                    "active": state.active(),
                    "dead_letters": state.dead_letters(),
                    "outbox": [
                        {k: o[k] for k in ("id", "state", "attempts")}
                        for o in state.outbox()
                    ],
                }
            )
        )
        return 0
    if args.command == "readiness":
        print(
            canonical(
                live_readiness(
                    agent_key_configured=bool(os.environ.get("ACS_CLAUDE_KEY_ID")),
                    runner_configured=False,
                    distinct_identity=False,
                    observed_live_result_url=None,
                )
            )
        )
        return 0
    if args.live:
        ClaudeRunner(
            ExecutionPolicy(), credential_ref=None, approval_ref=None
        )  # raises LiveExecutionDisabled
    if not args.coordinator_sqlite:
        print(
            canonical(
                {
                    "status": "BLOCKED",
                    "reason": "NO_COORDINATOR_TRANSPORT_CONFIGURED",
                    "executions": 0,
                }
            )
        )
        return 2

    class _NoPublish:
        def comments(self):
            return []

        def post(self, body):
            raise OSError("RESULT_TRANSPORT_NOT_CONFIGURED")

    adapter = ClaudeAdapter(
        transport=StoreTransport(Store(args.coordinator_sqlite)),
        executor=MockClaudeExecutor(),
        state=state,
        publisher=ResultPublisher(_NoPublish(), {1}, state),
        canonical_ref=args.canonical_ref,
        workdir=Path(args.workdir),
        kill_switch=Path(args.kill_switch) if args.kill_switch else None,
    )
    print(canonical(adapter.run_once()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
