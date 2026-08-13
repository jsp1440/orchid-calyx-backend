"""Persistence backends for immutable Matrix Identification registry versions.

Explicit roots remain file-backed for bounded tests/local development. Production
can opt into PostgreSQL only after migration 613 is present and the durable-registry
activation flag is explicitly enabled.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

MATRIX_REGISTRY_TABLE = "matrix_identification_registry_versions"

REQUIRED_COLUMNS: dict[str, str] = {
    "registry_id": "text",
    "version": "text",
    "checksum_sha256": "text",
    "publication_state": "text",
    "record": "jsonb",
    "created_by": "text",
    "created_at": "timestamp with time zone",
}
REQUIRED_INDEXES = {
    "idx_matrix_registry_checksum",
    "idx_matrix_registry_created_at",
}


class MatrixRegistryPersistenceError(RuntimeError):
    pass


class MatrixRegistryStore(Protocol):
    mode: str

    def get(self, registry_id: str, version: str) -> dict[str, Any] | None: ...

    def save(self, record: dict[str, Any]) -> dict[str, Any]: ...

    def list_records(self) -> list[dict[str, Any]]: ...

    def status(self) -> dict[str, Any]: ...


def default_registry_root() -> Path:
    return Path(os.getenv("CALYX_MATRIX_REGISTRY_DIR", "/tmp/calyx/matrix-identification-registry"))


class FileMatrixRegistryStore:
    mode = "file_ephemeral"

    def __init__(self, root: Path) -> None:
        self.root = root

    @staticmethod
    def _safe_component(value: str, field: str) -> str:
        cleaned = value.strip()
        if not cleaned or any(part in cleaned for part in ("/", "\\", "..")):
            raise ValueError(f"invalid {field}")
        return cleaned

    def _path(self, registry_id: str, version: str) -> Path:
        registry_id = self._safe_component(registry_id, "registry_id")
        version = self._safe_component(version, "version")
        return self.root / registry_id / f"{version}.json"

    def get(self, registry_id: str, version: str) -> dict[str, Any] | None:
        path = self._path(registry_id, version)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        path = self._path(str(record["registry_id"]), str(record["version"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
            if existing.get("checksum_sha256") == record.get("checksum_sha256"):
                return {"created": False, "record": existing}
            raise ValueError("registry version already exists with different content")
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temp.replace(path)
        return {"created": True, "record": record}

    def list_records(self) -> list[dict[str, Any]]:
        if not self.root.exists():
            return []
        records: list[dict[str, Any]] = []
        for path in sorted(self.root.glob("*/*.json")):
            try:
                records.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                continue
        return records

    def status(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "durable": False,
            "ready": True,
            "root": str(self.root),
            "warning": "File-backed Matrix registry versions are not restart-durable on ephemeral hosts.",
        }


def assess_registry_schema(
    *,
    columns: dict[str, str],
    primary_key_columns: list[str],
    indexes: set[str],
) -> dict[str, Any]:
    missing_columns = sorted(set(REQUIRED_COLUMNS) - set(columns))
    type_mismatches = [
        {"column": name, "expected": expected, "actual": columns.get(name)}
        for name, expected in REQUIRED_COLUMNS.items()
        if name in columns and columns[name] != expected
    ]
    primary_key_ok = primary_key_columns == ["registry_id", "version"]
    missing_indexes = sorted(REQUIRED_INDEXES - indexes)
    ready = not missing_columns and not type_mismatches and primary_key_ok and not missing_indexes
    return {
        "missing_columns": missing_columns,
        "type_mismatches": type_mismatches,
        "primary_key_columns": primary_key_columns,
        "primary_key_ok": primary_key_ok,
        "missing_indexes": missing_indexes,
        "migration_613_schema_ready": ready,
    }


class PostgresMatrixRegistryStore:
    mode = "postgres"

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn.strip()
        if not self.dsn:
            raise MatrixRegistryPersistenceError("MATRIX_REGISTRY_DATABASE_URL_REQUIRED")

    def schema_inspection(self) -> dict[str, Any]:
        base: dict[str, Any] = {
            "connectivity": False,
            "table_exists": False,
            "migration_613_schema_ready": False,
        }
        try:
            with psycopg.connect(
                self.dsn, connect_timeout=5, row_factory=dict_row
            ) as conn, conn.cursor() as cur:
                base["connectivity"] = True
                cur.execute(
                    "SELECT to_regclass(%s) AS table_name",
                    (f"public.{MATRIX_REGISTRY_TABLE}",),
                )
                row = cur.fetchone()
                if not row or not row["table_name"]:
                    base["blockers"] = ["MATRIX_REGISTRY_TABLE_NOT_FOUND"]
                    return base
                base["table_exists"] = True
                cur.execute(
                    """
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema='public' AND table_name=%s
                    ORDER BY ordinal_position
                    """,
                    (MATRIX_REGISTRY_TABLE,),
                )
                columns = {
                    str(item["column_name"]): str(item["data_type"])
                    for item in cur.fetchall()
                }
                cur.execute(
                    """
                    SELECT a.attname AS column_name
                    FROM pg_index i
                    JOIN pg_class t ON t.oid=i.indrelid
                    JOIN pg_namespace n ON n.oid=t.relnamespace
                    JOIN unnest(i.indkey) WITH ORDINALITY AS key(attnum, ord) ON true
                    JOIN pg_attribute a ON a.attrelid=t.oid AND a.attnum=key.attnum
                    WHERE n.nspname='public' AND t.relname=%s AND i.indisprimary
                    ORDER BY key.ord
                    """,
                    (MATRIX_REGISTRY_TABLE,),
                )
                primary_key_columns = [
                    str(item["column_name"]) for item in cur.fetchall()
                ]
                cur.execute(
                    "SELECT indexname FROM pg_indexes WHERE schemaname='public' AND tablename=%s",
                    (MATRIX_REGISTRY_TABLE,),
                )
                indexes = {str(item["indexname"]) for item in cur.fetchall()}
        except (psycopg.Error, OSError, ValueError, TypeError, KeyError) as exc:
            base["blockers"] = ["DATABASE_CONNECTIVITY_OR_INSPECTION_FAILED"]
            base["error_type"] = type(exc).__name__
            return base

        assessment = assess_registry_schema(
            columns=columns,
            primary_key_columns=primary_key_columns,
            indexes=indexes,
        )
        base.update(assessment)
        blockers: list[str] = []
        if assessment["missing_columns"]:
            blockers.append("MATRIX_REGISTRY_REQUIRED_COLUMNS_MISSING")
        if assessment["type_mismatches"]:
            blockers.append("MATRIX_REGISTRY_COLUMN_TYPE_MISMATCH")
        if not assessment["primary_key_ok"]:
            blockers.append("MATRIX_REGISTRY_PRIMARY_KEY_MISMATCH")
        if assessment["missing_indexes"]:
            blockers.append("MATRIX_REGISTRY_REQUIRED_INDEXES_MISSING")
        base["blockers"] = blockers
        return base

    def _require_schema(self) -> None:
        inspection = self.schema_inspection()
        if not inspection.get("migration_613_schema_ready"):
            blockers = inspection.get("blockers") or ["MATRIX_REGISTRY_SCHEMA_NOT_READY"]
            raise MatrixRegistryPersistenceError(
                "MATRIX_REGISTRY_SCHEMA_NOT_READY: "
                + ",".join(map(str, blockers))
                + "; apply/repair governed migration 613 before enabling durable registry persistence"
            )

    def get(self, registry_id: str, version: str) -> dict[str, Any] | None:
        self._require_schema()
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT record FROM {MATRIX_REGISTRY_TABLE} WHERE registry_id=%s AND version=%s",
                (registry_id, version),
            )
            row = cur.fetchone()
            return dict(row["record"]) if row is not None else None

    def save(self, record: dict[str, Any]) -> dict[str, Any]:
        self._require_schema()
        registry_id = str(record.get("registry_id") or "").strip()
        version = str(record.get("version") or "").strip()
        checksum = str(record.get("checksum_sha256") or "").strip()
        if not registry_id or not version or not checksum:
            raise ValueError("registry_id, version and checksum_sha256 are required")
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {MATRIX_REGISTRY_TABLE}(
                    registry_id, version, checksum_sha256, publication_state,
                    record, created_by, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, COALESCE(%s::timestamptz, now()))
                ON CONFLICT (registry_id, version) DO NOTHING
                RETURNING registry_id
                """,
                (
                    registry_id,
                    version,
                    checksum,
                    str(record.get("publication_state") or "review_required"),
                    Jsonb(record),
                    str(record.get("created_by") or ""),
                    record.get("created_at"),
                ),
            )
            inserted = cur.fetchone()
            if inserted is not None:
                conn.commit()
                return {"created": True, "record": record}

            cur.execute(
                f"SELECT checksum_sha256, record FROM {MATRIX_REGISTRY_TABLE} WHERE registry_id=%s AND version=%s",
                (registry_id, version),
            )
            existing = cur.fetchone()
            if existing is None:
                raise MatrixRegistryPersistenceError(
                    "MATRIX_REGISTRY_WRITE_CONFLICT: registry version conflict could not be resolved"
                )
            if str(existing["checksum_sha256"]) == checksum:
                return {"created": False, "record": dict(existing["record"])}
            raise ValueError("registry version already exists with different content")

    def list_records(self) -> list[dict[str, Any]]:
        self._require_schema()
        with psycopg.connect(self.dsn, row_factory=dict_row) as conn, conn.cursor() as cur:
            cur.execute(
                f"SELECT record FROM {MATRIX_REGISTRY_TABLE} ORDER BY registry_id, version"
            )
            return [dict(item["record"]) for item in cur.fetchall()]

    def status(self) -> dict[str, Any]:
        inspection = self.schema_inspection()
        ready = bool(inspection.get("migration_613_schema_ready"))
        return {
            "mode": self.mode,
            "durable": True,
            "ready": ready,
            "schema": MATRIX_REGISTRY_TABLE,
            "schema_contract": inspection,
            "error": None if ready else "MATRIX_REGISTRY_SCHEMA_NOT_READY",
        }


def registry_durable_requested() -> bool:
    return os.getenv("CALYX_MATRIX_REGISTRY_DURABLE_ENABLED", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def configured_matrix_registry_store(*, root: Path | None = None) -> MatrixRegistryStore:
    if root is not None:
        return FileMatrixRegistryStore(root)
    if registry_durable_requested():
        dsn = os.getenv("DATABASE_URL", "").strip()
        if not dsn:
            raise MatrixRegistryPersistenceError("MATRIX_REGISTRY_DATABASE_URL_REQUIRED")
        return PostgresMatrixRegistryStore(dsn)
    return FileMatrixRegistryStore(default_registry_root())


def matrix_registry_persistence_status() -> dict[str, Any]:
    requested = registry_durable_requested()
    try:
        status = configured_matrix_registry_store().status()
    except MatrixRegistryPersistenceError as exc:
        status = {
            "mode": "postgres" if requested else "unavailable",
            "durable": requested,
            "ready": False,
            "error": str(exc),
        }
    status["durable_requested"] = requested
    status["activation_boundary"] = (
        "Production migration 613, registry data copy and durable-registry activation are separate governed deployment actions."
    )
    return status
