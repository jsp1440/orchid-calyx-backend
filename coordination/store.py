"""Transactional assignment and report state. Schema setup is explicitly invoked."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass

AGENTS = frozenset({"chatgpt", "claude", "kimi", "copilot", "calyx"})
ACTIONS = frozenset(
    {
        "engineering",
        "merge",
        "deploy",
        "production_db",
        "paid_ai",
        "infrastructure",
        "scientific_publish",
    }
)
FIELDS = {
    "assign": {"agent", "objective", "action"},
    "claim": set(),
    "heartbeat": {"lease_token"},
    "response": {"lease_token", "outcome", "reference"},
    "approve": {"digest", "expires_at"},
    "reject": {"digest"},
}
COMMON = {"version", "event_id", "kind", "task_id"}
SCHEMA = (
    "CREATE TABLE IF NOT EXISTS acs_inbox (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, status TEXT NOT NULL)",
    "CREATE TABLE IF NOT EXISTS acs_events (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, principal TEXT NOT NULL, result TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS acs_tasks (
    id TEXT PRIMARY KEY, agent TEXT NOT NULL, objective TEXT NOT NULL, action TEXT NOT NULL,
    digest TEXT NOT NULL, state TEXT NOT NULL, attempts INTEGER NOT NULL,
    available_at DOUBLE PRECISION NOT NULL, lease_token TEXT, lease_until DOUBLE PRECISION,
    deadline DOUBLE PRECISION, reason TEXT NOT NULL, response_ref TEXT,
    approval_until DOUBLE PRECISION)""",
    """CREATE TABLE IF NOT EXISTS acs_outbox (
    id TEXT PRIMARY KEY, body TEXT NOT NULL, state TEXT NOT NULL,
    attempts INTEGER NOT NULL, available_at DOUBLE PRECISION NOT NULL,
    token TEXT, lease_until DOUBLE PRECISION, reason TEXT NOT NULL)""",
    "CREATE TABLE IF NOT EXISTS acs_agents (id TEXT PRIMARY KEY, last_seen DOUBLE PRECISION NOT NULL)",
)


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def reference(value):
    return isinstance(value, str) and bool(
        re.fullmatch(
            r"https://github\.com/jsp1440/[A-Za-z0-9_.-]+/(?:issues|pull)/[1-9][0-9]*",
            value,
        )
    )


@dataclass(frozen=True)
class Principal:
    role: str
    name: str

    def key(self):
        if self.role not in {"owner", "coordinator", "agent"} or not self.name:
            raise PermissionError("UNTRUSTED_PRINCIPAL")
        return f"{self.role}:{self.name}"


class Store:
    """Dedicated storage only; never falls back to the application's DATABASE_URL."""

    def __init__(
        self,
        url,
        *,
        clock=time.time,
        max_attempts=3,
        lease_seconds=60,
        attempt_seconds=900,
    ):
        if not isinstance(url, str) or not url or url == ":memory:":
            raise ValueError("PERSISTENT_STORE_REQUIRED")
        if max_attempts < 1 or lease_seconds < 1 or attempt_seconds < lease_seconds:
            raise ValueError("INVALID_LIMITS")
        self._local = threading.local()
        self.url = url
        self.postgres = url.startswith(("postgresql://", "postgres://"))
        self.clock = clock
        self.max_attempts = max_attempts
        self.lease_seconds = lease_seconds
        self.attempt_seconds = attempt_seconds

    @contextmanager
    def transaction(self):
        active = getattr(self._local, "connection", None)
        if active is not None:
            yield active
            return
        if self.postgres:
            import psycopg
            from psycopg.rows import dict_row

            conn = psycopg.connect(self.url, row_factory=dict_row, connect_timeout=10)

        else:
            conn = sqlite3.connect(self.url, timeout=10)
            conn.row_factory = sqlite3.Row
        try:
            if self.postgres:
                conn.execute("SELECT pg_advisory_xact_lock(1823001)")
            else:
                conn.execute("BEGIN IMMEDIATE")
            self._local.connection = conn
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            self._local.connection = None
            conn.close()

    def sql(self, conn, text, params=()):
        return conn.execute(text.replace("?", "%s") if self.postgres else text, params)

    def initialize(self):
        """Operator migration, never called by constructors or service startup."""
        with self.transaction() as conn:
            for statement in SCHEMA:
                self.sql(conn, statement)

    def _task(self, conn, task_id):
        row = self.sql(
            conn, "SELECT * FROM acs_tasks WHERE id=?", (task_id,)
        ).fetchone()
        if row is None:
            raise ValueError("TASK_NOT_FOUND")
        return dict(row)

    def task(self, task_id):
        with self.transaction() as conn:
            return self._task(conn, task_id)

    def events(self):
        with self.transaction() as conn:
            return [
                dict(r)
                for r in self.sql(
                    conn, "SELECT * FROM acs_events ORDER BY id"
                ).fetchall()
            ]

    def reports(self):
        with self.transaction() as conn:
            return [
                dict(r)
                for r in self.sql(
                    conn, "SELECT * FROM acs_outbox ORDER BY id"
                ).fetchall()
            ]

    def validate(self, event):
        if not isinstance(event, dict) or event.get("kind") not in FIELDS:
            raise ValueError("UNKNOWN_EVENT")
        expected = COMMON | FIELDS[event["kind"]]
        if event["kind"] in {"heartbeat", "response"} and "attempt" in event:
            expected = expected - {"lease_token"} | {"attempt"}
        if (
            set(event) != expected
            or type(event["version"]) is not int
            or event["version"] != 1
        ):
            raise ValueError("EVENT_SCHEMA_MISMATCH")
        for key in ("task_id", "event_id"):
            if not isinstance(event[key], str) or not re.fullmatch(
                r"[A-Za-z0-9_.:-]{1,128}", event[key]
            ):
                raise ValueError("INVALID_ID")
        if len(canonical(event).encode()) > 16384:
            raise ValueError("EVENT_TOO_LARGE")
        if event["kind"] == "assign" and (
            event["agent"] not in AGENTS
            or event["action"] not in ACTIONS
            or not reference(event["objective"])
        ):
            raise ValueError("ASSIGNMENT_INVALID")
        if "attempt" in event and (
            type(event["attempt"]) is not int or event["attempt"] < 1
        ):
            raise ValueError("ATTEMPT_INVALID")
        if "lease_token" in event and (
            not isinstance(event["lease_token"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", event["lease_token"])
        ):
            raise ValueError("LEASE_TOKEN_INVALID")
        if event["kind"] == "response" and (
            event["outcome"] not in {"delivered", "blocked"}
            or not reference(event["reference"])
        ):
            raise ValueError("RESPONSE_INVALID")
        if event["kind"] in {"approve", "reject"} and (
            not isinstance(event["digest"], str)
            or not re.fullmatch(r"[a-f0-9]{64}", event["digest"])
        ):
            raise ValueError("APPROVAL_DIGEST_INVALID")
        if event["kind"] == "approve" and (
            type(event["expires_at"]) not in {int, float}
            or not self.clock() < event["expires_at"] <= self.clock() + 86400
        ):
            raise ValueError("APPROVAL_EXPIRY_INVALID")

    def _report(self, conn, row, marker):
        # Public projection deliberately omits objective, response and lease token.
        body = f"<!-- OC-ACS:{marker} -->\n" + canonical(
            {
                "version": 1,
                "task_id": row["id"],
                "agent": row["agent"],
                "state": row["state"],
                "reason": row["reason"],
                "action": row["action"],
                "attempts": row["attempts"],
            }
        )
        self.sql(
            conn,
            """INSERT INTO acs_outbox
            (id,body,state,attempts,available_at,reason) VALUES (?,?,?,0,?,?)
            ON CONFLICT (id) DO NOTHING""",
            (marker, body, "pending", self.clock(), ""),
        )

    def _save(self, conn, row):
        keys = [key for key in row if key != "id"]
        self.sql(
            conn,
            "UPDATE acs_tasks SET "
            + ",".join(f"{key}=?" for key in keys)
            + " WHERE id=?",
            tuple(row[k] for k in keys) + (row["id"],),
        )

    def apply(self, event, principal):
        self.validate(event)
        principal_key = principal.key()
        kind = event["kind"]
        if kind == "assign" and principal.role not in {"owner", "coordinator"}:
            raise PermissionError("ASSIGNMENT_AUTHORITY_REQUIRED")
        if kind in {"approve", "reject"} and principal.role != "owner":
            raise PermissionError("OWNER_REQUIRED")
        if kind in {"claim", "heartbeat", "response"} and principal.role != "agent":
            raise PermissionError("AGENT_REQUIRED")
        fingerprint = digest(event)
        now = self.clock()
        with self.transaction() as conn:
            old = self.sql(
                conn, "SELECT * FROM acs_events WHERE id=?", (event["event_id"],)
            ).fetchone()
            if old:
                if old["principal"] != principal_key:
                    raise PermissionError("EVENT_PRINCIPAL_MISMATCH")
                if old["fingerprint"] != fingerprint:
                    raise ValueError("EVENT_ID_CONFLICT")
                return json.loads(old["result"])
            if kind == "assign":
                existing = self.sql(
                    conn, "SELECT id FROM acs_tasks WHERE id=?", (event["task_id"],)
                ).fetchone()
                if existing:
                    raise ValueError("TASK_ALREADY_EXISTS")
                task_digest = digest(
                    {k: event[k] for k in ("task_id", "agent", "objective", "action")}
                )
                self.sql(
                    conn,
                    """INSERT INTO acs_tasks
                    (id,agent,objective,action,digest,state,attempts,available_at,reason)
                    VALUES (?,?,?,?,?,?,0,?,?)""",
                    (
                        event["task_id"],
                        event["agent"],
                        event["objective"],
                        event["action"],
                        task_digest,
                        "queued" if event["action"] == "engineering" else "owner_gate",
                        now,
                        "awaiting_agent"
                        if event["action"] == "engineering"
                        else "privileged_executor_disabled",
                    ),
                )
                row = self._task(conn, event["task_id"])
            else:
                row = self._task(conn, event["task_id"])
                if principal.role == "agent" and row["agent"] != principal.name:
                    raise PermissionError("WRONG_AGENT")
                if kind == "claim":
                    if (
                        row["state"] not in {"queued", "retry"}
                        or row["available_at"] > now
                    ):
                        raise ValueError("TASK_NOT_CLAIMABLE")
                    row.update(
                        state="running",
                        attempts=row["attempts"] + 1,
                        lease_token=secrets.token_hex(32),
                        lease_until=now + self.lease_seconds,
                        deadline=now + self.attempt_seconds,
                        reason="agent_claimed",
                    )
                elif kind in {"heartbeat", "response"}:
                    if (
                        row["state"] != "running"
                        or row["lease_until"] <= now
                        or row["deadline"] <= now
                        or (
                            "lease_token" in event
                            and not secrets.compare_digest(
                                row["lease_token"] or "", event["lease_token"]
                            )
                        )
                        or ("attempt" in event and row["attempts"] != event["attempt"])
                    ):
                        raise PermissionError("LEASE_EXPIRED_OR_FENCED")
                    if kind == "heartbeat":
                        row.update(
                            lease_until=min(now + self.lease_seconds, row["deadline"])
                        )
                    else:
                        row.update(
                            state=event["outcome"],
                            response_ref=event["reference"],
                            lease_token=None,
                            lease_until=None,
                            reason="maker_reported_" + event["outcome"],
                        )
                elif kind in {"approve", "reject"}:
                    if row["state"] != "owner_gate" or row["digest"] != event["digest"]:
                        raise ValueError("APPROVAL_SCOPE_MISMATCH")
                    if kind == "approve":
                        row.update(
                            approval_until=event["expires_at"],
                            reason="owner_acknowledged_executor_disabled",
                        )
                    else:
                        row.update(state="rejected", reason="owner_rejected")
                self._save(conn, row)
                if principal.role == "agent":
                    self.sql(
                        conn,
                        """INSERT INTO acs_agents (id,last_seen) VALUES (?,?)
                        ON CONFLICT (id) DO UPDATE SET last_seen=excluded.last_seen""",
                        (principal.name, now),
                    )
            if kind != "heartbeat":
                self._report(conn, row, "event:" + event["event_id"])
            result = canonical(row)
            self.sql(
                conn,
                "INSERT INTO acs_events (id,fingerprint,principal,result) VALUES (?,?,?,?)",
                (event["event_id"], fingerprint, principal_key, result),
            )
            return json.loads(result)

    def tick(self):
        now = self.clock()
        changed = []
        with self.transaction() as conn:
            for raw in self.sql(
                conn, "SELECT * FROM acs_tasks WHERE state='running'"
            ).fetchall():
                row = dict(raw)
                if min(row["lease_until"], row["deadline"]) > now:
                    continue
                row.update(
                    state="dead_letter"
                    if row["attempts"] >= self.max_attempts
                    else "retry",
                    available_at=now + min(300, 10 * 2 ** (row["attempts"] - 1)),
                    lease_token=None,
                    lease_until=None,
                    reason="heartbeat_or_deadline_expired",
                )
                self._save(conn, row)
                self._report(conn, row, f"timeout:{row['id']}:{row['attempts']}")
                changed.append(row["id"])
            for raw in self.sql(
                conn,
                "SELECT * FROM acs_tasks WHERE state='owner_gate' AND approval_until IS NOT NULL",
            ).fetchall():
                row = dict(raw)
                if row["approval_until"] <= now:
                    row.update(approval_until=None, reason="owner_approval_expired")
                    self._save(conn, row)
                    self._report(conn, row, f"approval-expired:{row['id']}:{int(now)}")
        return changed

    def health(self):
        now = self.clock()
        with self.transaction() as conn:
            known = {
                r["id"]: r["last_seen"]
                for r in self.sql(conn, "SELECT * FROM acs_agents").fetchall()
            }
            return {
                agent: {
                    "last_seen": known.get(agent),
                    "status": (
                        "unknown"
                        if agent not in known
                        else (
                            "healthy"
                            if now - known[agent] < self.lease_seconds
                            else "stale"
                        )
                    ),
                }
                for agent in sorted(AGENTS)
            }

    def take_report(self):
        now = self.clock()
        with self.transaction() as conn:
            raw = self.sql(
                conn,
                """SELECT * FROM acs_outbox WHERE
                (state IN ('pending','uncertain') AND available_at<=?) OR (state IN ('sending','reconciling') AND lease_until<=?)
                ORDER BY available_at,id LIMIT 1""",
                (now, now),
            ).fetchone()
            if not raw:
                return None
            row = dict(raw)
            reconcile_only = row["attempts"] >= self.max_attempts
            row.update(
                token=secrets.token_hex(32),
                lease_until=now + self.lease_seconds,
                attempts=row["attempts"] + (0 if reconcile_only else 1),
                state="reconciling" if reconcile_only else "sending",
                reconcile_only=reconcile_only,
            )
            self.sql(
                conn,
                "UPDATE acs_outbox SET token=?,lease_until=?,attempts=?,state=? WHERE id=?",
                (
                    row["token"],
                    row["lease_until"],
                    row["attempts"],
                    row["state"],
                    row["id"],
                ),
            )
            return row

    def settle_report(self, report_id, token, success):
        now = self.clock()
        with self.transaction() as conn:
            row = self.sql(
                conn, "SELECT * FROM acs_outbox WHERE id=?", (report_id,)
            ).fetchone()
            if (
                not row
                or row["state"] not in {"sending", "reconciling"}
                or row["lease_until"] <= now
                or not secrets.compare_digest(row["token"] or "", token)
            ):
                raise PermissionError("REPORT_LEASE_FENCED")
            state = (
                "sent"
                if success
                else (
                    "dead_letter"
                    if row["state"] == "reconciling"
                    else (
                        "uncertain"
                        if row["attempts"] >= self.max_attempts
                        else "pending"
                    )
                )
            )
            self.sql(
                conn,
                "UPDATE acs_outbox SET state=?,token=NULL,lease_until=NULL,available_at=?,reason=? WHERE id=?",
                (
                    state,
                    now + min(300, 10 * 2 ** (row["attempts"] - 1)),
                    "" if success else "github_delivery_failed",
                    report_id,
                ),
            )
