"""Persistence backends for governed Matrix Identification sessions.

File persistence remains available for tests/local development. Governed durable
mode uses PostgreSQL and is fail-closed: enabling durable mode without a database
or migrated schema raises an explicit readiness error rather than falling back to
/tmp and silently losing scientific provenance on restart.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

MATRIX_SESSION_TABLE = "matrix_identification_sessions"


class MatrixSessionPersistenceError(RuntimeError):
    pass


class MatrixSessionStore(Protocol):
    mode: str

    def get(self, session_id: str, *, access_actor: str | None = None) -> dict[str, Any] | None: ...

    def save(self, record: dict[str, Any]) -> dict[str, Any]: ...

    def status(self) -> dict[str, Any]: ...


class FileMatrixSessionStore:
    mode = "file_ephemeral"

    def __init__(self, root: Path) -> None:
        self.root = root

    @staticmethod
    def _safe_session_id(session_id: str) -> str:
        if not session_id or any(part in session_id for part in ("/", "\\", "..")):
            raise ValueError("invalid session_id")
        return session_id

    def _path(self, session_id: str) -> Path:
        return self.root / f"{self._safe_session_id(session_id)}.json"

    def get(self, session_id: str, *, access_actor: str | None = None) -> dict[str, Any] | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
        if access_actor is not None and str(record.get("actor") or "") != str(access_actor):
            return None
        return record

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        path = self._path(str(record["session_id"]))
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if int(record.get("revision", 0)) < int(existing.get("revision", 0)):
                raise MatrixSessionPersistenceError("MATRIX_SESSION_STALE_REVISION")
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temp.replace(path)
        return record

    def status(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "durable": False,
            "ready": True,
            "root": str(self.root),
            "warning": "File-backed Matrix sessions are not restart-durable on ephemeral hosts.",
        }


class PostgresMatrixSessionStore:
    mode = "postgres"

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn.strip()
        if not self.dsn:
            raise MatrixSessionPersistenceError("MATRIX_SESSION_DATABASE_URL_REQUIRED")

    def schema_ready(self) -> bool:
        try:
            with psycopg.connect(self.dsn, connect_timeout=5) as conn, conn.cursor() as cur:
                cur.execute("SELECT to_regclass(%s)", (f"public.{MATRIX_SESSION_TABLE}",))
                row = cur.fetchone()
                return bool(row and row[0])
        except Exception:
            return False

    def _require_schema(self) -> None:
        if not self.schema_ready():
            raise MatrixSessionPersistenceError(
                "MATRIX_SESSION_SCHEMA_NOT_READY: apply the governed Matrix session migration before enabling durable persistence"
            )

    def get(self, session_id: str, *, access_actor: str | None = None) -> dict[str, Any] | None:
        self._require_schema()
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn, conn.cursor() as cur:
            if access_actor is None:
                cur.execute(
                    f"SELECT record FROM {MATRIX_SESSION_TABLE} WHERE session_id=%s::uuid",
                    (session_id,),
                )
            else:
                cur.execute(
                    f"SELECT record FROM {MATRIX_SESSION_TABLE} WHERE session_id=%s::uuid AND owner=%s",
                    (session_id, access_actor),
                )
            row = cur.fetchone()
            if row is None:
                return None
            return dict(row["record"])

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        self._require_schema()
        session_id = str(record.get("session_id") or "").strip()
        owner = str(record.get("actor") or "").strip()
        registry = record.get("registry") or {}
        if not session_id or not owner:
            raise ValueError("session_id and actor are required for durable Matrix persistence")
        with psycopg.connect(self.dsn) as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {MATRIX_SESSION_TABLE}(
                    session_id, owner, schema_version, registry_id, registry_version,
                    registry_checksum_sha256, revision, status, record, created_at, updated_at
                ) VALUES (
                    %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s,
                    COALESCE(%s::timestamptz, now()), COALESCE(%s::timestamptz, now())
                )
                ON CONFLICT (session_id) DO UPDATE SET
                    revision=EXCLUDED.revision,
                    status=EXCLUDED.status,
                    record=EXCLUDED.record,
                    updated_at=EXCLUDED.updated_at
                WHERE {MATRIX_SESSION_TABLE}.owner=EXCLUDED.owner
                  AND {MATRIX_SESSION_TABLE}.registry_id=EXCLUDED.registry_id
                  AND {MATRIX_SESSION_TABLE}.registry_version=EXCLUDED.registry_version
                  AND {MATRIX_SESSION_TABLE}.registry_checksum_sha256=EXCLUDED.registry_checksum_sha256
                  AND {MATRIX_SESSION_TABLE}.revision <= EXCLUDED.revision
                RETURNING session_id
                """,
                (
                    session_id,
                    owner,
                    record.get("schema_version"),
                    registry.get("registry_id"),
                    registry.get("version"),
                    registry.get("checksum_sha256"),
                    int(record.get("revision", 0)),
                    str(record.get("status") or "active"),
                    Jsonb(record),
                    record.get("created_at"),
                    record.get("updated_at"),
                ),
            )
            row = cur.fetchone()
            if row is None:
                raise MatrixSessionPersistenceError(
                    "MATRIX_SESSION_WRITE_CONFLICT: immutable identity changed or stale revision attempted"
                )
            conn.commit()
        return record

    def status(self) -> dict[str, Any]:
        ready = self.schema_ready()
        return {
            "mode": self.mode,
            "durable": True,
            "ready": ready,
            "schema": MATRIX_SESSION_TABLE,
            "error": None if ready else "MATRIX_SESSION_SCHEMA_NOT_READY",
        }


def durable_requested() -> bool:
    return os.getenv("CALYX_MATRIX_SESSION_DURABLE_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def configured_matrix_session_store(*, root: Path | None = None) -> MatrixSessionStore:
    if root is not None:
        return FileMatrixSessionStore(root)
    if durable_requested():
        dsn = os.getenv("DATABASE_URL", "").strip()
        if not dsn:
            raise MatrixSessionPersistenceError("MATRIX_SESSION_DATABASE_URL_REQUIRED")
        return PostgresMatrixSessionStore(dsn)
    default_root = Path(
        os.getenv("CALYX_MATRIX_SESSION_DIR", "/tmp/calyx/matrix-identification-sessions")
    )
    return FileMatrixSessionStore(default_root)


def matrix_session_persistence_status() -> dict[str, Any]:
    requested = durable_requested()
    try:
        store = configured_matrix_session_store()
        status = store.status()
    except MatrixSessionPersistenceError as exc:
        status = {
            "mode": "postgres" if requested else "unavailable",
            "durable": requested,
            "ready": False,
            "error": str(exc),
        }
    status["durable_requested"] = requested
    status["activation_boundary"] = (
        "Production migration and durable-mode activation are separate governed deployment actions."
    )
    return status
