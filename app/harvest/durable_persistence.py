"""Durable SQLite-backed persistence for occurrence harvest records.

Replaces the in-memory ``InMemoryHarvestPersistence`` for staging runs that
must survive process restarts.  The store is idempotent: inserting a record
whose ``(source, source_record_id)`` key already exists is a silent no-op,
preserving the first-seen value.

Usage::

    store = DurableSqliteHarvestPersistence("/tmp/calyx-occurrences.sqlite3")
    saved = store.save_batch(source="gbif", records=normalized_records)
    rows  = store.all(source="gbif")
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock
from typing import Any, Mapping

_DDL = """
CREATE TABLE IF NOT EXISTS harvest_records (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    source            TEXT    NOT NULL,
    source_record_id  TEXT    NOT NULL,
    payload           TEXT    NOT NULL,
    canonical_taxon_id TEXT,
    inserted_at       TEXT    NOT NULL DEFAULT (datetime('now')),
    UNIQUE(source, source_record_id)
)
"""


class DurableSqliteHarvestPersistence:
    """Durable file-backed harvest record store.

    Thread-safe.  Safe to call ``save_batch`` from multiple threads; the
    SQLite UNIQUE constraint guarantees idempotency across restarts.
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

    def save_batch(self, *, source: str, records: list[Mapping[str, Any]]) -> int:
        """Persist *records* for *source*.  Returns the number of rows newly inserted."""
        saved = 0
        with self._lock:
            with self._connect() as conn:
                for record in records:
                    source_record_id = str(
                        record.get("source_record_id") or record.get("key") or ""
                    )
                    if not source_record_id:
                        raise ValueError("record is missing source_record_id")
                    payload = json.dumps(dict(record), default=str)
                    result = conn.execute(
                        "INSERT OR IGNORE INTO harvest_records"
                        " (source, source_record_id, payload)"
                        " VALUES (?, ?, ?)",
                        (source, source_record_id, payload),
                    )
                    saved += result.rowcount
                conn.commit()
        return saved

    def update_canonical_taxon_id(
        self,
        *,
        source: str,
        source_record_id: str,
        canonical_taxon_id: str,
    ) -> None:
        """Attach a resolved canonical taxon id to an already-persisted record."""
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE harvest_records SET canonical_taxon_id = ?"
                    " WHERE source = ? AND source_record_id = ?",
                    (canonical_taxon_id, source, source_record_id),
                )
                conn.commit()

    def all(self, source: str | None = None) -> list[dict[str, Any]]:
        """Return all stored records, optionally filtered by *source*."""
        with self._lock:
            with self._connect() as conn:
                if source is None:
                    rows = conn.execute(
                        "SELECT source, source_record_id, payload, canonical_taxon_id"
                        " FROM harvest_records ORDER BY id"
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT source, source_record_id, payload, canonical_taxon_id"
                        " FROM harvest_records WHERE source = ? ORDER BY id",
                        (source,),
                    ).fetchall()
        result = []
        for row in rows:
            record = json.loads(row[2] or "{}")
            record["_source"] = row[0]
            record["_source_record_id"] = row[1]
            record["_canonical_taxon_id"] = row[3]
            result.append(record)
        return result

    def count(self, source: str | None = None) -> int:
        with self._lock:
            with self._connect() as conn:
                if source is None:
                    return conn.execute(
                        "SELECT count(*) FROM harvest_records"
                    ).fetchone()[0]
                return conn.execute(
                    "SELECT count(*) FROM harvest_records WHERE source = ?",
                    (source,),
                ).fetchone()[0]
