from __future__ import annotations

import uuid
from typing import Any

from psycopg.types.json import Jsonb

from app.archive.registry import ArchiveRegistry


class CheckpointStore:
    def __init__(self, registry: ArchiveRegistry) -> None:
        self.registry = registry

    def save(self, run_id: uuid.UUID, *, next_index: int, relative_path: str | None, state: dict[str, Any]) -> None:
        with self.registry.connection() as conn:
            conn.execute(
                "INSERT INTO archive_checkpoints (import_run_id, next_file_index, last_relative_path, state) VALUES (%s,%s,%s,%s) ON CONFLICT (import_run_id) DO UPDATE SET next_file_index=excluded.next_file_index, last_relative_path=excluded.last_relative_path, state=excluded.state, updated_at=now()",
                (run_id, next_index, relative_path, Jsonb(state)),
            )
            conn.commit()

    def load(self, run_id: uuid.UUID) -> dict[str, Any] | None:
        with self.registry.connection() as conn:
            return conn.execute("SELECT * FROM archive_checkpoints WHERE import_run_id=%s", (run_id,)).fetchone()
