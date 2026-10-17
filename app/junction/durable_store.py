"""Durable local backend for the append-only observation store.

``SQLiteObservationStore`` subclasses the canonical reference store
(``app.scientific_observability.store.ObservationStore``) and persists every
append to a local SQLite file, mirroring the DRAFT — NOT APPLIED migration
``migrations/SCI-OBS-001-observation-store.sql`` (same identity, same payload
column, append-only). This is the "durable backend implements the same
interface" path the store's own docstring describes; it applies NO production
migration and touches NO database beyond the local file it is handed.

Durability is what makes subscriber cursors meaningful across restarts: the
router's cursor is a position in this store's append order, and append order is
preserved on reload because idempotent re-append never moves an existing event.
The redaction pass and ``event_id`` idempotency key are inherited unchanged —
this class adds persistence, not a second event system.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from app.scientific_observability.redaction import RedactionReport
from app.scientific_observability.store import ObservationStore

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scientific_observation_events (
    position            INTEGER PRIMARY KEY,  -- append order (autoincrement rowid)
    event_id            TEXT NOT NULL UNIQUE, -- OC:EVENT OCID; idempotency key
    schema_version      TEXT NOT NULL DEFAULT 'sci-obs-event-v1',
    event_type          TEXT NOT NULL,
    occurred_at         TEXT NOT NULL,
    recorded_at         TEXT NOT NULL,
    correlation_id      TEXT NOT NULL,
    parent_event_id     TEXT NULL,
    sequence            INTEGER NOT NULL CHECK (sequence >= 1),
    accepted_name       TEXT NULL,            -- denormalized from taxon.accepted_name
    canonical_taxon_id  TEXT NULL,
    pipeline_stage      TEXT NOT NULL,
    safe_status         TEXT NOT NULL,
    reason_code         TEXT NULL,
    payload             TEXT NOT NULL         -- full redacted envelope (JSON)
);
CREATE INDEX IF NOT EXISTS ix_sci_obs_correlation
    ON scientific_observation_events (correlation_id, sequence);
CREATE INDEX IF NOT EXISTS ix_sci_obs_type
    ON scientific_observation_events (event_type);
"""


class SQLiteObservationStore(ObservationStore):
    """Append-only observation store with a durable local SQLite backing."""

    def __init__(self, path: str | Path) -> None:
        super().__init__()
        self._path = str(path)
        Path(self._path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self._path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(_SCHEMA)
        # Reload the journal in append order, replaying through the inherited
        # idempotent append so in-memory state matches the durable log exactly.
        rows = self._db.execute(
            "SELECT payload FROM scientific_observation_events ORDER BY position"
        ).fetchall()
        for (payload,) in rows:
            super().append(json.loads(payload))

    def append(self, event: dict[str, Any]) -> tuple[dict[str, Any], bool, RedactionReport]:
        """Idempotent append; persists only genuinely new events."""

        stored, created, report = super().append(event)
        if created:
            taxon = stored.get("taxon") or {}
            safe = stored.get("safe_status") or {}
            pipeline = stored.get("pipeline") or {}
            self._db.execute(
                """
                INSERT INTO scientific_observation_events (
                    event_id, schema_version, event_type, occurred_at, recorded_at,
                    correlation_id, parent_event_id, sequence, accepted_name,
                    canonical_taxon_id, pipeline_stage, safe_status, reason_code,
                    payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stored["event_id"],
                    stored.get("schema_version", "sci-obs-event-v1"),
                    stored.get("event_type"),
                    stored.get("occurred_at"),
                    stored.get("recorded_at"),
                    stored.get("correlation_id"),
                    stored.get("parent_event_id"),
                    stored.get("sequence", 1),
                    taxon.get("accepted_name"),
                    taxon.get("canonical_taxon_id"),
                    pipeline.get("stage"),
                    safe.get("status"),
                    safe.get("reason_code"),
                    json.dumps(stored, sort_keys=True),
                ),
            )
            self._db.commit()
        return stored, created, report

    def close(self) -> None:
        self._db.close()
