"""Read-only durable persistence preflight for governed Matrix Identification sessions.

This module never creates or alters database objects. It verifies whether the target
PostgreSQL database already satisfies migration 612 strongly enough for durable
Matrix session activation to be considered safe.
"""

from __future__ import annotations

import os
import re
from typing import Any

import psycopg
from psycopg.rows import dict_row

from runtime.matrix_identification_session_store import (
    MATRIX_SESSION_TABLE,
    durable_requested,
)

PREFLIGHT_SCHEMA_VERSION = "matrix-identification-persistence-preflight/v2"

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

REQUIRED_NOT_NULL = frozenset(REQUIRED_COLUMNS)
REQUIRED_DEFAULTS: dict[str, str | None] = {
    "session_id": None,
    "owner": None,
    "schema_version": None,
    "registry_id": None,
    "registry_version": None,
    "registry_checksum_sha256": None,
    "revision": "0",
    "status": "'active'::text",
    "record": None,
    "created_at": "now()",
    "updated_at": "now()",
}
REQUIRED_INDEX_COLUMNS: dict[str, tuple[str, ...]] = {
    "idx_matrix_identification_sessions_owner_updated": ("owner", "updated_at desc"),
    "idx_matrix_identification_sessions_registry": ("registry_id", "registry_version"),
    "idx_matrix_identification_sessions_registry_checksum": ("registry_checksum_sha256",),
}
REQUIRED_INDEXES = frozenset(REQUIRED_INDEX_COLUMNS)


def _normalize_sql(value: str | None) -> str:
    if value is None:
        return ""
    normalized = value.casefold().replace('"', "")
    return re.sub(r"\s+", " ", normalized).strip()


def _normalize_default(value: str | None) -> str | None:
    if value is None:
        return None
    return _normalize_sql(value).replace(" ", "")


def _default_matches(expected: str | None, actual: str | None) -> bool:
    expected_normalized = _normalize_default(expected)
    actual_normalized = _normalize_default(actual)
    if expected_normalized is None:
        return actual_normalized is None
    if expected_normalized == "'active'::text":
        return actual_normalized in {"'active'::text", "'active'"}
    if expected_normalized == "now()":
        return actual_normalized in {"now()", "current_timestamp"}
    return actual_normalized == expected_normalized


def _index_definition_matches(index_name: str, definition: str | None) -> bool:
    expected_columns = REQUIRED_INDEX_COLUMNS[index_name]
    normalized = _normalize_sql(definition)
    if not normalized or " where " in f" {normalized} ":
        return False
    open_paren = normalized.find("(")
    close_paren = normalized.rfind(")")
    if open_paren < 0 or close_paren <= open_paren:
        return False
    observed_columns = tuple(
        part.strip() for part in normalized[open_paren + 1 : close_paren].split(",")
    )
    return observed_columns == expected_columns


def _revision_check_present(check_constraints: list[str]) -> bool:
    for definition in check_constraints:
        normalized = _normalize_sql(definition)
        compact = re.sub(r"[\s()]", "", normalized)
        if compact in {"checkrevision>=0", "checkrevision>=0::integer"}:
            return True
        if compact.startswith("check") and "revision>=0" in compact:
            return True
    return False


def assess_matrix_session_schema(
    *,
    columns: dict[str, str],
    nullable: dict[str, bool],
    defaults: dict[str, str | None],
    primary_key_columns: list[str],
    index_definitions: dict[str, str],
    check_constraints: list[str],
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
    nullable_mismatches = [
        name
        for name in sorted(REQUIRED_NOT_NULL)
        if name in columns and nullable.get(name, True)
    ]
    default_mismatches = [
        {
            "column": name,
            "expected": expected,
            "actual": defaults.get(name),
        }
        for name, expected in REQUIRED_DEFAULTS.items()
        if name in columns and not _default_matches(expected, defaults.get(name))
    ]
    observed_indexes = set(index_definitions)
    missing_indexes = sorted(REQUIRED_INDEXES - observed_indexes)
    index_definition_mismatches = [
        {
            "index": name,
            "expected_columns": list(REQUIRED_INDEX_COLUMNS[name]),
            "actual": index_definitions.get(name),
        }
        for name in sorted(REQUIRED_INDEXES & observed_indexes)
        if not _index_definition_matches(name, index_definitions.get(name))
    ]
    primary_key_ok = primary_key_columns == ["session_id"]
    revision_check_ok = _revision_check_present(check_constraints)
    schema_ready = not any(
        (
            missing_columns,
            type_mismatches,
            nullable_mismatches,
            default_mismatches,
            missing_indexes,
            index_definition_mismatches,
        )
    ) and primary_key_ok and revision_check_ok
    return {
        "required_columns": REQUIRED_COLUMNS,
        "observed_columns": columns,
        "missing_columns": missing_columns,
        "type_mismatches": type_mismatches,
        "required_not_null_columns": sorted(REQUIRED_NOT_NULL),
        "observed_nullable": nullable,
        "nullable_mismatches": nullable_mismatches,
        "required_defaults": REQUIRED_DEFAULTS,
        "observed_defaults": defaults,
        "default_mismatches": default_mismatches,
        "primary_key_columns": primary_key_columns,
        "primary_key_ok": primary_key_ok,
        "required_index_columns": {
            name: list(columns) for name, columns in REQUIRED_INDEX_COLUMNS.items()
        },
        "observed_index_definitions": index_definitions,
        "missing_indexes": missing_indexes,
        "index_definition_mismatches": index_definition_mismatches,
        "check_constraints": check_constraints,
        "revision_nonnegative_check_ok": revision_check_ok,
        "migration_612_schema_ready": schema_ready,
    }


def inspect_matrix_session_database(dsn: str) -> dict[str, Any]:
    """Read the target database's Matrix-session schema contract without mutation."""
    base: dict[str, Any] = {
        "connectivity": False,
        "read_only": False,
        "table_exists": False,
        "migration_612_schema_ready": False,
    }
    try:
        with psycopg.connect(
            dsn,
            connect_timeout=5,
            row_factory=dict_row,
            options="-c default_transaction_read_only=on",
        ) as conn, conn.cursor() as cur:
            base["connectivity"] = True
            cur.execute("SHOW transaction_read_only")
            read_only_row = cur.fetchone()
            read_only_value = "" if not read_only_row else str(next(iter(read_only_row.values())))
            base["read_only"] = read_only_value.casefold() in {"on", "true"}
            if not base["read_only"]:
                base["blockers"] = ["READ_ONLY_DATABASE_SESSION_NOT_PROVEN"]
                return base

            cur.execute("SELECT to_regclass(%s) AS table_name", (f"public.{MATRIX_SESSION_TABLE}",))
            row = cur.fetchone()
            if not row or not row["table_name"]:
                base["blockers"] = ["MATRIX_SESSION_TABLE_NOT_FOUND"]
                return base
            base["table_exists"] = True

            cur.execute(
                """
                SELECT column_name, data_type, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema='public' AND table_name=%s
                ORDER BY ordinal_position
                """,
                (MATRIX_SESSION_TABLE,),
            )
            column_rows = cur.fetchall()
            columns = {
                str(item["column_name"]): str(item["data_type"]) for item in column_rows
            }
            nullable = {
                str(item["column_name"]): str(item["is_nullable"]).upper() == "YES"
                for item in column_rows
            }
            defaults = {
                str(item["column_name"]): (
                    None if item["column_default"] is None else str(item["column_default"])
                )
                for item in column_rows
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
                (MATRIX_SESSION_TABLE,),
            )
            primary_key_columns = [str(item["column_name"]) for item in cur.fetchall()]

            cur.execute(
                """
                SELECT indexname, indexdef
                FROM pg_indexes
                WHERE schemaname='public' AND tablename=%s
                """,
                (MATRIX_SESSION_TABLE,),
            )
            index_definitions = {
                str(item["indexname"]): str(item["indexdef"]) for item in cur.fetchall()
            }

            cur.execute(
                """
                SELECT pg_get_constraintdef(c.oid, true) AS definition
                FROM pg_constraint c
                JOIN pg_class t ON t.oid=c.conrelid
                JOIN pg_namespace n ON n.oid=t.relnamespace
                WHERE n.nspname='public' AND t.relname=%s AND c.contype='c'
                ORDER BY c.conname
                """,
                (MATRIX_SESSION_TABLE,),
            )
            check_constraints = [str(item["definition"]) for item in cur.fetchall()]
    except psycopg.Error as exc:
        base["blockers"] = ["DATABASE_CONNECTIVITY_OR_INSPECTION_FAILED"]
        base["error_type"] = type(exc).__name__
        return base

    assessment = assess_matrix_session_schema(
        columns=columns,
        nullable=nullable,
        defaults=defaults,
        primary_key_columns=primary_key_columns,
        index_definitions=index_definitions,
        check_constraints=check_constraints,
    )
    base.update(assessment)
    blockers: list[str] = []
    if assessment["missing_columns"]:
        blockers.append("MATRIX_SESSION_REQUIRED_COLUMNS_MISSING")
    if assessment["type_mismatches"]:
        blockers.append("MATRIX_SESSION_COLUMN_TYPE_MISMATCH")
    if assessment["nullable_mismatches"]:
        blockers.append("MATRIX_SESSION_NULLABILITY_MISMATCH")
    if assessment["default_mismatches"]:
        blockers.append("MATRIX_SESSION_DEFAULT_MISMATCH")
    if not assessment["primary_key_ok"]:
        blockers.append("MATRIX_SESSION_PRIMARY_KEY_MISMATCH")
    if assessment["missing_indexes"]:
        blockers.append("MATRIX_SESSION_REQUIRED_INDEXES_MISSING")
    if assessment["index_definition_mismatches"]:
        blockers.append("MATRIX_SESSION_INDEX_DEFINITION_MISMATCH")
    if not assessment["revision_nonnegative_check_ok"]:
        blockers.append("MATRIX_SESSION_REVISION_CHECK_MISSING")
    base["blockers"] = blockers
    return base


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
        "read_only": False,
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

    inspection = inspect_matrix_session_database(dsn)
    base.update(inspection)
    base["activation_ready"] = bool(
        inspection.get("connectivity")
        and inspection.get("read_only")
        and inspection.get("migration_612_schema_ready")
    )
    base["activated"] = bool(requested and base["activation_ready"])
    return base
