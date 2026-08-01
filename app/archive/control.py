from __future__ import annotations

import os
import socket
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from app.archive.registry import ArchiveRegistry


class ArchiveRunConflict(RuntimeError):
    pass


class ArchiveRunControl:
    def __init__(self, registry: ArchiveRegistry | None = None) -> None:
        self.registry = registry or ArchiveRegistry()
        self.lease_seconds = int(os.getenv("ARCHIVE_LEASE_SECONDS", "300"))
        self.owner = f"{socket.gethostname()}:{os.getpid()}"

    def create_queued_run(self, source_path: str, options: dict[str, Any]) -> uuid.UUID:
        run_id = uuid.uuid4()
        with self.registry.connection() as conn:
            conn.execute(
                "INSERT INTO archive_import_runs (id,source_path,status,options) VALUES (%s,%s,'queued',%s)",
                (run_id, source_path, Jsonb(options)),
            )
            conn.commit()
        return run_id

    def set_dispatch_reference(self, run_id: uuid.UUID, reference: str) -> None:
        with self.registry.connection() as conn:
            conn.execute(
                "UPDATE archive_import_runs SET dispatch_reference=%s,updated_at=now() WHERE id=%s",
                (reference, run_id),
            )
            conn.commit()

    def claim(self, run_id: uuid.UUID) -> None:
        expires = datetime.now(UTC) + timedelta(seconds=self.lease_seconds)
        with self.registry.connection() as conn:
            row = conn.execute(
                """
                UPDATE archive_import_runs
                SET status='running', lease_owner=%s, lease_expires_at=%s,
                    heartbeat_at=now(), attempt_count=attempt_count+1, updated_at=now()
                WHERE id=%s
                  AND status IN ('queued','interrupted','failed')
                  AND (lease_expires_at IS NULL OR lease_expires_at < now())
                RETURNING id
                """,
                (self.owner, expires, run_id),
            ).fetchone()
            conn.commit()
        if not row:
            raise ArchiveRunConflict("archive import run is already active or not claimable")

    def heartbeat(self, run_id: uuid.UUID) -> None:
        expires = datetime.now(UTC) + timedelta(seconds=self.lease_seconds)
        with self.registry.connection() as conn:
            conn.execute(
                "UPDATE archive_import_runs SET heartbeat_at=now(),lease_expires_at=%s,updated_at=now() WHERE id=%s AND lease_owner=%s",
                (expires, run_id, self.owner),
            )
            conn.commit()

    def request_cancel(self, run_id: uuid.UUID) -> bool:
        with self.registry.connection() as conn:
            row = conn.execute(
                """
                UPDATE archive_import_runs
                SET cancel_requested=true,
                    status=CASE WHEN status='running' THEN 'cancelling' ELSE status END,
                    updated_at=now()
                WHERE id=%s AND status IN ('queued','running','cancelling','interrupted')
                RETURNING id
                """,
                (run_id,),
            ).fetchone()
            conn.commit()
        return bool(row)

    def cancellation_requested(self, run_id: uuid.UUID) -> bool:
        with self.registry.connection() as conn:
            row = conn.execute(
                "SELECT cancel_requested FROM archive_import_runs WHERE id=%s", (run_id,)
            ).fetchone()
        return bool(row and row["cancel_requested"])

    def complete(self, run_id: uuid.UUID, status: str) -> None:
        with self.registry.connection() as conn:
            conn.execute(
                """
                UPDATE archive_import_runs
                SET status=%s, finished_at=CASE WHEN %s IN ('completed','cancelled','failed') THEN now() ELSE finished_at END,
                    lease_owner=NULL, lease_expires_at=NULL, heartbeat_at=now(), updated_at=now()
                WHERE id=%s
                """,
                (status, status, run_id),
            )
            conn.commit()

    def recover_stale_runs(self) -> int:
        with self.registry.connection() as conn:
            result = conn.execute(
                """
                UPDATE archive_import_runs
                SET status='interrupted', lease_owner=NULL, lease_expires_at=NULL,
                    last_error='worker lease expired', updated_at=now()
                WHERE status IN ('running','cancelling') AND lease_expires_at < now()
                """
            )
            conn.commit()
            return result.rowcount
