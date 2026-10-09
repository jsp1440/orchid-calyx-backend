"""Static contract verification for governed migrations 612 and 613.

These tests reconcile the committed migration SQL with the schema contracts the
runtime stores and preflight inspectors enforce at activation time. They run
without a database: applying either migration to any environment remains a
separate governed deployment action, and nothing here mutates one.

If a future change edits the runtime contracts (REQUIRED_COLUMNS, index
expectations, table names) or the migration files, this suite fails until the
two sides agree again.
"""

from __future__ import annotations

import re
from pathlib import Path

from runtime import matrix_identification_persistence_preflight as session_preflight
from runtime.matrix_identification_registry_store import (
    MATRIX_REGISTRY_TABLE,
    REQUIRED_COLUMNS as REGISTRY_REQUIRED_COLUMNS,
    REQUIRED_INDEXES as REGISTRY_REQUIRED_INDEXES,
)
from runtime.matrix_identification_session_store import MATRIX_SESSION_TABLE

REPO_ROOT = Path(__file__).resolve().parents[1]
MIGRATION_612 = REPO_ROOT / "migrations" / "612_matrix_identification_sessions.sql"
MIGRATION_613 = REPO_ROOT / "migrations" / "613_matrix_identification_registry_versions.sql"

_SQL_TYPE_BY_PREFLIGHT = {
    "uuid": "UUID",
    "text": "TEXT",
    "integer": "INTEGER",
    "jsonb": "JSONB",
    "timestamp with time zone": "TIMESTAMPTZ",
}


def _read(path: Path) -> str:
    assert path.exists(), f"migration file missing: {path}"
    return path.read_text(encoding="utf-8")


def _normalized(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip().lower()


def _column_definitions(sql: str) -> dict[str, str]:
    match = re.search(
        r"CREATE TABLE IF NOT EXISTS\s+\w+\s*\((.*?)\);",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    assert match, "CREATE TABLE statement not found"
    columns: dict[str, str] = {}
    for raw_line in match.group(1).split(","):
        line = raw_line.strip()
        if not line or line.upper().startswith(
            ("PRIMARY KEY", "CONSTRAINT", "CHECK ", "CHECK(", "UNIQUE")
        ):
            continue
        name = line.split()[0].strip('"').lower()
        columns[name] = _normalized(line)
    return columns


def test_migration_612_defines_every_required_column_with_contract_types() -> None:
    sql = _read(MIGRATION_612)
    assert f"CREATE TABLE IF NOT EXISTS {MATRIX_SESSION_TABLE}" in sql
    columns = _column_definitions(sql)
    for name, preflight_type in session_preflight.REQUIRED_COLUMNS.items():
        assert name in columns, f"612 missing required column: {name}"
        expected_sql_type = _SQL_TYPE_BY_PREFLIGHT[preflight_type]
        assert expected_sql_type.lower() in columns[name], (
            f"612 column {name} must use {expected_sql_type}: {columns[name]}"
        )
        assert (
            "not null" in columns[name] or "primary key" in columns[name]
        ), f"612 column {name} must be NOT NULL"


def test_migration_612_defaults_primary_key_and_revision_check() -> None:
    sql = _read(MIGRATION_612)
    columns = _column_definitions(sql)
    assert "primary key" in columns["session_id"]
    assert re.search(r"default\s+0", columns["revision"])
    assert re.search(r"check\s*\(\s*revision\s*>=\s*0\s*\)", sql, re.IGNORECASE)
    assert re.search(r"default\s+'active'", columns["status"])
    for name in ("created_at", "updated_at"):
        assert re.search(r"default\s+now\(\)", columns[name])


def test_migration_612_defines_every_required_index_with_contract_columns() -> None:
    normalized = _normalized(_read(MIGRATION_612))
    for index_name, expected_columns in session_preflight.REQUIRED_INDEX_COLUMNS.items():
        assert index_name in normalized, f"612 missing required index: {index_name}"
        pattern = (
            rf"create index if not exists {index_name} on {MATRIX_SESSION_TABLE}"
            r"\(([^)]+)\)"
        )
        match = re.search(pattern, normalized)
        assert match, f"612 index definition not found for {index_name}"
        observed = tuple(part.strip() for part in match.group(1).split(","))
        assert observed == expected_columns, (
            f"612 index {index_name} columns {observed} != {expected_columns}"
        )


def test_migration_612_keeps_governed_activation_boundary() -> None:
    sql = _read(MIGRATION_612)
    assert "CALYX_MATRIX_SESSION_DURABLE_ENABLED" in sql
    assert re.search(r"^\s*BEGIN\s*;", sql, re.MULTILINE)
    assert re.search(r"^\s*COMMIT\s*;", sql, re.MULTILINE)


def test_migration_613_defines_every_required_column_with_contract_types() -> None:
    sql = _read(MIGRATION_613)
    assert f"CREATE TABLE IF NOT EXISTS {MATRIX_REGISTRY_TABLE}" in sql
    columns = _column_definitions(sql)
    for name, store_type in REGISTRY_REQUIRED_COLUMNS.items():
        assert name in columns, f"613 missing required column: {name}"
        expected_sql_type = _SQL_TYPE_BY_PREFLIGHT[store_type]
        assert expected_sql_type.lower() in columns[name], (
            f"613 column {name} must use {expected_sql_type}: {columns[name]}"
        )
        assert "not null" in columns[name], f"613 column {name} must be NOT NULL"


def test_migration_613_primary_key_defaults_and_indexes() -> None:
    sql = _read(MIGRATION_613)
    normalized = _normalized(sql)
    assert re.search(
        r"primary key\s*\(\s*registry_id\s*,\s*version\s*\)", normalized
    ), "613 must keep the composite (registry_id, version) primary key"
    columns = _column_definitions(sql)
    assert re.search(r"default\s+'review_required'", columns["publication_state"])
    assert re.search(r"default\s+now\(\)", columns["created_at"])
    for index_name in REGISTRY_REQUIRED_INDEXES:
        assert index_name in normalized, f"613 missing required index: {index_name}"
    assert re.search(
        rf"create index if not exists idx_matrix_registry_checksum on {MATRIX_REGISTRY_TABLE}\(checksum_sha256\)",
        normalized,
    )
    assert re.search(
        rf"create index if not exists idx_matrix_registry_created_at on {MATRIX_REGISTRY_TABLE}\(created_at desc\)",
        normalized,
    )


def test_migration_613_keeps_governed_activation_boundary() -> None:
    sql = _read(MIGRATION_613)
    assert "CALYX_MATRIX_REGISTRY_DURABLE_ENABLED" in sql
    assert re.search(r"^\s*BEGIN\s*;", sql, re.MULTILINE)
    assert re.search(r"^\s*COMMIT\s*;", sql, re.MULTILINE)


def test_session_schema_assessor_accepts_contract_shaped_snapshot() -> None:
    assessment = session_preflight.assess_matrix_session_schema(
        columns=dict(session_preflight.REQUIRED_COLUMNS),
        nullable={name: False for name in session_preflight.REQUIRED_COLUMNS},
        defaults=dict(session_preflight.REQUIRED_DEFAULTS),
        primary_key_columns=["session_id"],
        index_definitions={
            name: f"CREATE INDEX {name} ON {MATRIX_SESSION_TABLE}({', '.join(cols)})"
            for name, cols in session_preflight.REQUIRED_INDEX_COLUMNS.items()
        },
        check_constraints=["CHECK (revision >= 0)"],
    )
    assert assessment["migration_612_schema_ready"] is True
    assert assessment["primary_key_ok"] is True
    assert assessment["revision_nonnegative_check_ok"] is True


def test_session_schema_assessor_rejects_drifted_snapshot() -> None:
    drifted_columns = dict(session_preflight.REQUIRED_COLUMNS)
    drifted_columns.pop("registry_checksum_sha256")
    assessment = session_preflight.assess_matrix_session_schema(
        columns=drifted_columns,
        nullable={name: False for name in drifted_columns},
        defaults=dict(session_preflight.REQUIRED_DEFAULTS),
        primary_key_columns=["session_id"],
        index_definitions={},
        check_constraints=[],
    )
    assert assessment["migration_612_schema_ready"] is False
    assert "registry_checksum_sha256" in assessment["missing_columns"]
    assert assessment["missing_indexes"]
    assert assessment["revision_nonnegative_check_ok"] is False
