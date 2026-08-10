from __future__ import annotations

import time

from app.persistence.state_repository import PostgresStateMixin

from .memory_repository import MemoryIndexRepository


class PostgresIndexRepository(PostgresStateMixin, MemoryIndexRepository):
    snapshot_kind = "semantic_index"
    lock_id = 8605
    state_attributes = (
        "models",
        "runs",
        "items",
        "documents",
        "vectors",
        "lexical",
        "tombstones",
        "warnings",
        "reviews",
        "cancelled",
        "_id",
    )

    def __init__(self, database_url: str | None = None) -> None:
        MemoryIndexRepository.__init__(self)
        self._snapshot_revision = 0
        self._last_refresh_probe = 0.0
        self.__init_persistence__(database_url)
        self.refresh(force=True)

    def _read_snapshot_revision(self) -> int:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT revision FROM oc_candidate_knowledge.runtime_repository_snapshots WHERE repository_kind=%s",
                (self.snapshot_kind,),
            )
            row = cur.fetchone()
        return int(row["revision"]) if row and row.get("revision") is not None else 0

    def refresh(self, force: bool = False):
        super().refresh()
        self._snapshot_revision = self._read_snapshot_revision()
        self._last_refresh_probe = time.monotonic()
        return self

    def refresh_for_read(self):
        revision = self._read_snapshot_revision()
        self._last_refresh_probe = time.monotonic()
        if revision != self._snapshot_revision:
            super().refresh()
            self._snapshot_revision = revision
        return self

    def atomic(self, operation):
        result = super().atomic(operation)
        self._snapshot_revision = self._read_snapshot_revision()
        self._last_refresh_probe = time.monotonic()
        return result
