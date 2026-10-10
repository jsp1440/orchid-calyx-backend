"""Durable junction delivery state: cursors, idempotency, retries, dead letters.

One small SQLite file (stdlib only) holds everything the junction router must
survive a restart with:

- ``cursors``       — per-subscriber position in the observation store's append
                      order. Recovery replays from the cursor; replayed signals
                      are applied idempotently.
- ``applied``       — per-subscriber dedupe keys already applied. A dedupe key
                      is never applied twice (idempotent consumption).
- ``attempts``      — per-(subscriber, event) delivery attempt counter and the
                      last machine-readable failure reason.
- ``dead_letters``  — signals that exhausted the retry bound: retained in full
                      with reason code, excluded from further automatic
                      delivery, surfaced for review.
- ``emissions``     — per-module per-minute emission counters enforcing the
                      manifest rate budget (fail-closed governor input).
- ``audit``         — append-only audit trail of port decisions (drops,
                      denials, dead-lettering), because every narrowing of
                      communication must be reconstructible.

This is delivery state only. It is not a queue, not a scheduler, and not a
second event store: the events themselves live in the observation store.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS cursors (
    subscriber  TEXT PRIMARY KEY,
    position    INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS applied (
    subscriber  TEXT NOT NULL,
    dedupe_key  TEXT NOT NULL,
    event_id    TEXT NOT NULL,
    applied_at  TEXT NOT NULL,
    PRIMARY KEY (subscriber, dedupe_key)
);
CREATE TABLE IF NOT EXISTS attempts (
    subscriber  TEXT NOT NULL,
    event_id    TEXT NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    last_reason TEXT NULL,
    updated_at  TEXT NOT NULL,
    PRIMARY KEY (subscriber, event_id)
);
CREATE TABLE IF NOT EXISTS dead_letters (
    id              INTEGER PRIMARY KEY,
    subscriber      TEXT NOT NULL,
    event_id        TEXT NOT NULL,
    dedupe_key      TEXT NOT NULL,
    attempts        INTEGER NOT NULL,
    reason          TEXT NOT NULL,
    event_json      TEXT NOT NULL,
    dead_lettered_at TEXT NOT NULL,
    UNIQUE (subscriber, event_id)
);
CREATE TABLE IF NOT EXISTS emissions (
    module      TEXT NOT NULL,
    window      TEXT NOT NULL,
    count       INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (module, window)
);
CREATE TABLE IF NOT EXISTS audit (
    id      INTEGER PRIMARY KEY,
    at      TEXT NOT NULL,
    actor   TEXT NOT NULL,
    action  TEXT NOT NULL,
    reason  TEXT NULL,
    detail  TEXT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class JunctionStateStore:
    """Durable delivery state for one junction router instance."""

    def __init__(self, path: str | Path) -> None:
        self._path = str(path)
        if self._path != ":memory:":
            Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self._path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)

    # -- cursors -----------------------------------------------------------

    def get_cursor(self, subscriber: str) -> int:
        row = self._db.execute(
            "SELECT position FROM cursors WHERE subscriber = ?", (subscriber,)
        ).fetchone()
        return int(row[0]) if row else 0

    def set_cursor(self, subscriber: str, position: int) -> None:
        self._db.execute(
            "INSERT INTO cursors (subscriber, position) VALUES (?, ?) "
            "ON CONFLICT(subscriber) DO UPDATE SET position = excluded.position",
            (subscriber, int(position)),
        )
        self._db.commit()

    # -- idempotent application ---------------------------------------------

    def is_applied(self, subscriber: str, dedupe_key: str) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM applied WHERE subscriber = ? AND dedupe_key = ?",
            (subscriber, dedupe_key),
        ).fetchone()
        return row is not None

    def mark_applied(self, subscriber: str, dedupe_key: str, event_id: str) -> None:
        self._db.execute(
            "INSERT OR IGNORE INTO applied (subscriber, dedupe_key, event_id, applied_at) "
            "VALUES (?, ?, ?, ?)",
            (subscriber, dedupe_key, event_id, _now()),
        )
        self._db.commit()

    # -- bounded retries -----------------------------------------------------

    def get_attempts(self, subscriber: str, event_id: str) -> int:
        row = self._db.execute(
            "SELECT attempts FROM attempts WHERE subscriber = ? AND event_id = ?",
            (subscriber, event_id),
        ).fetchone()
        return int(row[0]) if row else 0

    def record_attempt(self, subscriber: str, event_id: str, reason: str | None) -> int:
        """Increment and return the attempt count for one delivery."""

        self._db.execute(
            "INSERT INTO attempts (subscriber, event_id, attempts, last_reason, updated_at) "
            "VALUES (?, ?, 1, ?, ?) "
            "ON CONFLICT(subscriber, event_id) DO UPDATE SET "
            "attempts = attempts + 1, last_reason = excluded.last_reason, "
            "updated_at = excluded.updated_at",
            (subscriber, event_id, reason, _now()),
        )
        self._db.commit()
        return self.get_attempts(subscriber, event_id)

    # -- dead letters ---------------------------------------------------------

    def is_dead_lettered(self, subscriber: str, event_id: str) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM dead_letters WHERE subscriber = ? AND event_id = ?",
            (subscriber, event_id),
        ).fetchone()
        return row is not None

    def dead_letter(
        self,
        *,
        subscriber: str,
        event: dict[str, Any],
        attempts: int,
        reason: str,
    ) -> None:
        """Retain the full signal with its reason; exclude it from delivery."""

        junction = (event.get("extensions") or {}).get("junction") or {}
        self._db.execute(
            "INSERT OR IGNORE INTO dead_letters (subscriber, event_id, dedupe_key, attempts, "
            "reason, event_json, dead_lettered_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                subscriber,
                event.get("event_id"),
                junction.get("dedupe_key", ""),
                int(attempts),
                reason,
                json.dumps(event, sort_keys=True),
                _now(),
            ),
        )
        self._db.commit()

    def dead_letters(self, subscriber: str | None = None) -> list[dict[str, Any]]:
        sql = (
            "SELECT subscriber, event_id, dedupe_key, attempts, reason, event_json, "
            "dead_lettered_at FROM dead_letters"
        )
        params: tuple[Any, ...] = ()
        if subscriber is not None:
            sql += " WHERE subscriber = ?"
            params = (subscriber,)
        rows = self._db.execute(sql + " ORDER BY id", params).fetchall()
        return [
            {
                "subscriber": row[0],
                "event_id": row[1],
                "dedupe_key": row[2],
                "attempts": row[3],
                "reason": row[4],
                "event": json.loads(row[5]),
                "dead_lettered_at": row[6],
            }
            for row in rows
        ]

    # -- emission budget -------------------------------------------------------

    def count_emission(self, module: str, window: str) -> int:
        """Increment and return the module's emission count for one window."""

        self._db.execute(
            "INSERT INTO emissions (module, window, count) VALUES (?, ?, 1) "
            "ON CONFLICT(module, window) DO UPDATE SET count = count + 1",
            (module, window),
        )
        self._db.commit()
        row = self._db.execute(
            "SELECT count FROM emissions WHERE module = ? AND window = ?", (module, window)
        ).fetchone()
        return int(row[0])

    # -- audit -----------------------------------------------------------------

    def audit(self, *, actor: str, action: str, reason: str | None, detail: Any = None) -> None:
        self._db.execute(
            "INSERT INTO audit (at, actor, action, reason, detail) VALUES (?, ?, ?, ?, ?)",
            (_now(), actor, action, reason, json.dumps(detail, sort_keys=True) if detail is not None else None),
        )
        self._db.commit()

    def audit_trail(self) -> list[dict[str, Any]]:
        rows = self._db.execute(
            "SELECT at, actor, action, reason, detail FROM audit ORDER BY id"
        ).fetchall()
        return [
            {
                "at": row[0],
                "actor": row[1],
                "action": row[2],
                "reason": row[3],
                "detail": json.loads(row[4]) if row[4] else None,
            }
            for row in rows
        ]

    def close(self) -> None:
        self._db.close()
