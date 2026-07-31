from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator
import os
import uuid

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class ArchiveRegistry:
    def __init__(self, database_url: str | None = None) -> None:
        self.database_url = database_url or os.environ.get("DATABASE_URL")

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection[Any]]:
        if not self.database_url:
            raise RuntimeError("DATABASE_URL is required for archive persistence")
        with psycopg.connect(self.database_url, row_factory=dict_row) as conn:
            yield conn

    def create_run(self, source_path: str, options: dict[str, Any]) -> uuid.UUID:
        run_id = uuid.uuid4()
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO archive_import_runs (id, source_path, status, options) VALUES (%s,%s,'running',%s)",
                (run_id, source_path, Jsonb(options)),
            )
            conn.commit()
        return run_id

    def find_file_by_sha256(self, digest: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            return conn.execute(
                "SELECT * FROM archive_files WHERE sha256 = %s ORDER BY created_at LIMIT 1", (digest,)
            ).fetchone()

    def register_document(self, *, run_id: uuid.UUID, relative_path: str, digest: str, size_bytes: int,
                          extraction_method: str, text: str, metadata: dict[str, Any]) -> uuid.UUID:
        document_id = uuid.uuid4()
        file_id = uuid.uuid4()
        with self.connection() as conn:
            conn.execute(
                "INSERT INTO archive_documents (id, canonical_title, extracted_text, metadata) VALUES (%s,%s,%s,%s)",
                (document_id, relative_path, text, Jsonb(metadata)),
            )
            conn.execute(
                "INSERT INTO archive_files (id, document_id, import_run_id, relative_path, sha256, size_bytes, extraction_method, status) VALUES (%s,%s,%s,%s,%s,%s,%s,'indexed')",
                (file_id, document_id, run_id, relative_path, digest, size_bytes, extraction_method),
            )
            conn.commit()
        return document_id

    def record_error(self, run_id: uuid.UUID, relative_path: str, message: str) -> None:
        with self.connection() as conn:
            conn.execute(
                "UPDATE archive_import_runs SET error_count=error_count+1, last_error=%s, updated_at=now() WHERE id=%s",
                (f"{relative_path}: {message}"[:4000], run_id),
            )
            conn.commit()

    def update_run_counters(self, run_id: uuid.UUID, **increments: int) -> None:
        allowed = {"files_discovered", "files_processed", "duplicates_skipped", "documents_indexed", "entities_extracted", "relationships_created"}
        parts, values = [], []
        for key, value in increments.items():
            if key not in allowed or not value:
                continue
            parts.append(f"{key}={key}+%s")
            values.append(value)
        if not parts:
            return
        values.append(run_id)
        with self.connection() as conn:
            conn.execute(f"UPDATE archive_import_runs SET {', '.join(parts)}, updated_at=now() WHERE id=%s", values)
            conn.commit()

    def finish_run(self, run_id: uuid.UUID, status: str = "completed") -> None:
        with self.connection() as conn:
            conn.execute("UPDATE archive_import_runs SET status=%s, finished_at=now(), updated_at=now() WHERE id=%s", (status, run_id))
            conn.commit()

    def run(self, run_id: uuid.UUID) -> dict[str, Any] | None:
        with self.connection() as conn:
            return conn.execute("SELECT * FROM archive_import_runs WHERE id=%s", (run_id,)).fetchone()

    def latest_run(self) -> dict[str, Any] | None:
        with self.connection() as conn:
            return conn.execute("SELECT * FROM archive_import_runs ORDER BY created_at DESC LIMIT 1").fetchone()

    def statistics(self) -> dict[str, int]:
        with self.connection() as conn:
            return conn.execute("SELECT (SELECT count(*) FROM archive_documents) documents, (SELECT count(*) FROM archive_files) files, (SELECT count(*) FROM archive_entities) entities, (SELECT count(*) FROM archive_relationships) relationships, (SELECT count(*) FROM archive_import_runs) import_runs").fetchone()
