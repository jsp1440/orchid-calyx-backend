"""Durable SQLite-backed checkpoint store for Harvester V2.

Replaces the in-memory ``InMemoryCheckpointStore`` for staging runs that must
survive process restarts and support resumable bounded harvests.

Usage::

    store = DurableSqliteCheckpointStore("/tmp/calyx-checkpoints.sqlite3")
    store.save_from_state("gbif", "orchids-2026", {"offset": 300, "processed": 300})
    cp = store.load("gbif", "orchids-2026")
    assert cp.offset == 300
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Mapping

from .models import HarvestCheckpoint

_DDL = """
CREATE TABLE IF NOT EXISTS harvest_checkpoints (
    source   TEXT NOT NULL,
    job_key  TEXT NOT NULL,
    cursor   TEXT,
    offset   INTEGER NOT NULL DEFAULT 0,
    processed INTEGER NOT NULL DEFAULT 0,
    completed INTEGER NOT NULL DEFAULT 0,
    state    TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (source, job_key)
)
"""


class DurableSqliteCheckpointStore:
    """File-backed, restartable checkpoint store.

    Thread-safe.  Multiple workers reading/writing different ``job_key``
    values safely share the same file.
    """

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with self._connect() as conn:
            conn.execute(_DDL)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def load(self, source: str, job_key: str) -> HarvestCheckpoint | None:
        with self._lock:
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT source, job_key, cursor, offset, processed, completed,"
                    " state, updated_at FROM harvest_checkpoints"
                    " WHERE source = ? AND job_key = ?",
                    (source, job_key),
                ).fetchone()
        if row is None:
            return None
        return HarvestCheckpoint(
            source=row[0],
            job_key=row[1],
            cursor=row[2],
            offset=int(row[3]),
            processed=int(row[4]),
            completed=bool(row[5]),
            state=json.loads(row[6] or "{}"),
            updated_at=datetime.fromisoformat(row[7]),
        )

    def save(self, checkpoint: HarvestCheckpoint) -> None:
        updated = replace(checkpoint, updated_at=datetime.now(timezone.utc))
        state_json = json.dumps(dict(updated.state or {}), default=str)
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO harvest_checkpoints"
                    " (source, job_key, cursor, offset, processed, completed, state, updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?)"
                    " ON CONFLICT(source, job_key) DO UPDATE SET"
                    "   cursor     = excluded.cursor,"
                    "   offset     = excluded.offset,"
                    "   processed  = excluded.processed,"
                    "   completed  = excluded.completed,"
                    "   state      = excluded.state,"
                    "   updated_at = excluded.updated_at",
                    (
                        updated.source,
                        updated.job_key,
                        updated.cursor,
                        updated.offset,
                        updated.processed,
                        int(updated.completed),
                        state_json,
                        updated.updated_at.isoformat(),
                    ),
                )
                conn.commit()

    def save_from_state(
        self, source: str, job_key: str, state: Mapping[str, Any]
    ) -> None:
        checkpoint = HarvestCheckpoint(
            source=source,
            job_key=job_key,
            cursor=state.get("cursor"),
            offset=int(state.get("offset", 0)),
            processed=int(state.get("processed", 0)),
            completed=bool(state.get("completed", False)),
            state={
                k: v
                for k, v in state.items()
                if k not in {"cursor", "offset", "processed", "completed"}
            },
        )
        self.save(checkpoint)

    def clear(self, source: str, job_key: str) -> None:
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "DELETE FROM harvest_checkpoints WHERE source = ? AND job_key = ?",
                    (source, job_key),
                )
                conn.commit()

    def list_jobs(self, source: str | None = None) -> list[dict[str, Any]]:
        """Return summary rows for all tracked jobs."""
        with self._lock:
            with self._connect() as conn:
                if source is None:
                    rows = conn.execute(
                        "SELECT source, job_key, offset, processed, completed, updated_at"
                        " FROM harvest_checkpoints ORDER BY updated_at DESC"
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT source, job_key, offset, processed, completed, updated_at"
                        " FROM harvest_checkpoints WHERE source = ? ORDER BY updated_at DESC",
                        (source,),
                    ).fetchall()
        return [
            {
                "source": r[0],
                "job_key": r[1],
                "offset": r[2],
                "processed": r[3],
                "completed": bool(r[4]),
                "updated_at": r[5],
            }
            for r in rows
        ]
