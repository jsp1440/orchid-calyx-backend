"""Read-only durable persistence preflight for governed Matrix Identification sessions.

This module never creates or alters database objects. It verifies whether the target
PostgreSQL database already satisfies migration 612 strongly enough for durable
Matrix session activation to be considered safe.
"""

from __future__ import annotations

import os
from typing import Any

import psycopg
from psycopg.rows import dict_row

from runtime.matrix_identification_session_store import MATRIX_SESSION_TABLE, durable_requested

PREFLIGHT_SCHEMA_VERSION = "matrix-identification-persistence-preflight/v1"

REQUIRED_COLUMNS: dict[str, str] = {
    "session_id": "uuid",
    "owner": "text",
    "schema_version": "text",
    "registry_id": "text",
    "registry_version": "text",
    "registry_checksum_sha256": "text",
    "revision": "integer",
    "status": "text",
    "record": "jsonb",
    "created_at": "timestamp with time zone",
    "updated_at": "timestamp with time zone",
}

REQUIRED_INDEXES = {
    "idx_matrix_identification_sessions_owner_updated",
    "idx_matrix_identification_sessions_registry",
    "idx_matrix_identification_sessions_registry_checksum",
}


def assess_matrix_session_schema(
    *,
    columns: dict[str, str],
    primary_key_columns: list[str],
    indexes: set[str],
) -> dict[str, Any]:
    """Assess an already-read PostgreSQL schema snapshot without mutating it."""
    missing_columns = sorted(set(REQUIRED_COLUMNS) - set(columns))
    type_mismatches = [
        {
            "column": name,
            "expected": expected,
            "actual": columns.get(name),
        }
        for name, expected in REQUIRED_COLUMNS.items()
        if name in columns and columns[name] != expected
    ]
    missing_indexes = sorted(REQUIRED_INDEXES - indexes)
    primary_key_ok = primary_key_columns == ["session_id"]
    schema_ready = not missing_columns and not type_mismatches and primary_key_ok and not missing_indexes
    return {
        "required_columns": REQUIRED_COLUMNS,
        "observed_columns": columns,
        "missing_columns": missing_columns,
        "type_mismatches": type_mismatches,
        "primary_key_columns": primary_key_columns,
        "primary_key_ok": primary_key_ok,
        "required_indexes": sorted(REQUIRED_INDEXES),
        "observed_indexes": sorted(indexes),
        "missing_indexes": missing_indexes,
        "migration_612_schema_ready": schema_ready,
    }


def matrix_session_persistence_preflight() -> dict[str, Any]:
    """Inspect activation prerequisites without applying migration 612 or changing flags."""
    requested = durable_requested()
    dsn = os.getenv("DATABASE_URL", "").strip()
    base: dict[str, Any] = {
        "schema_version": PREFLIGHT_SCHEMA_VERSION,
        "database_url_configured": bool(dsn),
        "durable_requested": requested,
        "activated": False,
        "connectivity": False,
        "table_exists": False,
        "migration_612_schema_ready": False,
        "activation_ready": False,
        "migration_applied_by_preflight": False,
        "environment_changed_by_preflight": False,
        "governance_boundary": (
            "Applying migration 612 and enabling CALYX_MATRIX_SESSION_DURABLE_ENABLED are separate governed deployment actions."
        ),
    }
    if not dsn:
        base["blockers"] = ["DATABASE_URL_NOT_CONFIGURED"]
        return base

    try:
        with psycopg.connect(dsn, connect_timeout=5, row_factory=dict_row) as conn, conn.cursor() as cur:
            base["connectivity"] = True
            cur.execute("SELECT to_regclass(%s) AS table_name", (f"public.{MATRIX_SESSION_TABLE}",))
            row = cur.fetchone()
            if not row or not row["table_name"]:
                base["blockers"] = ["MATRIX_SESSION_TABLE_NOT_FOUND"]
                return base
            base["table_exists"] = True

            cur.execute(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema='public' AND table_name=%s
                ORDER BY ordinal_position
                """,
                (MATRIX_SESSION_TABLE,),
            )
            columns = {str(item["column_name"]): str(item["data_type"]) for item in cur.fetchall()}

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
                (MATRIX_SESSION_TABLE,),
            )
            primary_key_columns = [str(item["column_name"]) for item in cur.fetchall()]

            cur.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname='public' AND tablename=%s
                """,
                (MATRIX_SESSION_TABLE,),
            )
            indexes = {str(item["indexname"]) for item in cur.fetchall()}
    except Exception as exc:
        base["blockers"] = ["DATABASE_CONNECTIVITY_OR_INSPECTION_FAILED"]
        base["error_type"] = type(exc).__name__
        return base

    assessment = assess_matrix_session_schema(
        columns=columns,
        primary_key_columns=primary_key_columns,
        indexes=indexes,
    )
    base.update(assessment)
    blockers: list[str] = []
    if assessment["missing_columns"]:
        blockers.append("MATRIX_SESSION_REQUIRED_COLUMNS_MISSING")
    if assessment["type_mismatches"]:
        blockers.append("MATRIX_SESSION_COLUMN_TYPE_MISMATCH")
    if not assessment["primary_key_ok"]:
        blockers.append("MATRIX_SESSION_PRIMARY_KEY_MISMATCH")
    if assessment["missing_indexes"]:
        blockers.append("MATRIX_SESSION_REQUIRED_INDEXES_MISSING")
    base["blockers"] = blockers
    base["activation_ready"] = bool(base["connectivity"] and assessment["migration_612_schema_ready"])
    base["activated"] = bool(requested and base["activation_ready"])
    return base
