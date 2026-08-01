from __future__ import annotations

import os
import socket
import threading
import uuid
from contextlib import contextmanager
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

    def claim(self, run_id: uuid.UUID) -> int:
        expires = datetime.now(UTC) + timedelta(seconds=self.lease_seconds)
        with self.registry.connection() as conn:
            row = conn.execute(
                """
                UPDATE archive_import_runs
                SET status='running', lease_owner=%s, lease_expires_at=%s,
                    heartbeat_at=now(), attempt_count=attempt_count+1, updated_at=now()
                WHERE id=%s
                  AND status IN ('queued','interrupted','failed')
                  AND cancel_requested=false
                  AND (lease_expires_at IS NULL OR lease_expires_at < now())
                RETURNING attempt_count
                """,
                (self.owner, expires, run_id),
            ).fetchone()
            conn.commit()
        if not row:
            raise ArchiveRunConflict("archive import run is already active or not claimable")
        return int(row["attempt_count"])

    def heartbeat(self, run_id: uuid.UUID, attempt: int) -> bool:
        expires = datetime.now(UTC) + timedelta(seconds=self.lease_seconds)
        with self.registry.connection() as conn:
            row = conn.execute(
                """
                UPDATE archive_import_runs
                SET heartbeat_at=now(),lease_expires_at=%s,updated_at=now()
                WHERE id=%s AND lease_owner=%s AND attempt_count=%s
                  AND status IN ('running','cancelling')
                RETURNING id
                """,
                (expires, run_id, self.owner, attempt),
            ).fetchone()
            conn.commit()
        return bool(row)

    @contextmanager
    def lease_guard(self, run_id: uuid.UUID, attempt: int):
        stop = threading.Event()
        lease_lost = threading.Event()
        interval = max(1.0, self.lease_seconds / 3)

        def refresh() -> None:
            while not stop.wait(interval):
                if not self.heartbeat(run_id, attempt):
                    lease_lost.set()
                    return

        if not self.heartbeat(run_id, attempt):
            raise ArchiveRunConflict("archive import lease was lost before execution")
        thread = threading.Thread(target=refresh, name=f"archive-lease-{run_id}", daemon=True)
        thread.start()
        try:
            yield
            if lease_lost.is_set():
                raise ArchiveRunConflict("archive import lease was lost during execution")
        finally:
            stop.set()
            thread.join(timeout=min(2.0, interval))

    def owns_claim(self, run_id: uuid.UUID, attempt: int) -> bool:
        with self.registry.connection() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM archive_import_runs
                WHERE id=%s AND lease_owner=%s AND attempt_count=%s
                  AND status IN ('running','cancelling')
                  AND lease_expires_at >= now()
                """,
                (run_id, self.owner, attempt),
            ).fetchone()
        return bool(row)

    def request_cancel(self, run_id: uuid.UUID) -> bool:
        with self.registry.connection() as conn:
            row = conn.execute(
                """
                UPDATE archive_import_runs
                SET cancel_requested=true,
                    status=CASE
                        WHEN status='queued' THEN 'cancelled'
                        WHEN status='running' THEN 'cancelling'
                        ELSE status
                    END,
                    finished_at=CASE WHEN status='queued' THEN now() ELSE finished_at END,
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

    def fail_unclaimed(self, run_id: uuid.UUID, message: str) -> None:
        with self.registry.connection() as conn:
            conn.execute(
                """
                UPDATE archive_import_runs
                SET status='failed', last_error=%s, finished_at=now(), updated_at=now()
                WHERE id=%s AND status IN ('queued','interrupted','failed')
                  AND lease_owner IS NULL
                """,
                (message[:4000], run_id),
            )
            conn.commit()

    def complete(self, run_id: uuid.UUID, status: str, attempt: int) -> bool:
        with self.registry.connection() as conn:
            row = conn.execute(
                """
                UPDATE archive_import_runs
                SET status=%s,
                    finished_at=CASE WHEN %s IN ('completed','cancelled','failed') THEN now() ELSE finished_at END,
                    lease_owner=NULL, lease_expires_at=NULL, heartbeat_at=now(), updated_at=now()
                WHERE id=%s AND lease_owner=%s AND attempt_count=%s
                RETURNING id
                """,
                (status, status, run_id, self.owner, attempt),
            ).fetchone()
            conn.commit()
        return bool(row)

    def recover_stale_runs(self) -> int:
        with self.registry.connection() as conn:
            result = conn.execute(
                """
                UPDATE archive_import_runs
                SET status=CASE WHEN cancel_requested THEN 'cancelled' ELSE 'interrupted' END,
                    lease_owner=NULL, lease_expires_at=NULL,
                    finished_at=CASE WHEN cancel_requested THEN now() ELSE finished_at END,
                    last_error='worker lease expired', updated_at=now()
                WHERE status IN ('running','cancelling') AND lease_expires_at < now()
                """
            )
            conn.commit()
            return result.rowcount
