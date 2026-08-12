import os
from pathlib import Path

import psycopg
import pytest

from runtime.matrix_identification_persistence_preflight import (
    REQUIRED_COLUMNS,
    REQUIRED_DEFAULTS,
    REQUIRED_INDEX_COLUMNS,
    assess_matrix_session_schema,
    inspect_matrix_session_database,
    matrix_session_persistence_preflight,
)


def _valid_snapshot():
    table = "matrix_identification_sessions"
    index_definitions = {
        "idx_matrix_identification_sessions_owner_updated": (
            f"CREATE INDEX idx_matrix_identification_sessions_owner_updated ON public.{table} "
            "USING btree (owner, updated_at DESC)"
        ),
        "idx_matrix_identification_sessions_registry": (
            f"CREATE INDEX idx_matrix_identification_sessions_registry ON public.{table} "
            "USING btree (registry_id, registry_version)"
        ),
        "idx_matrix_identification_sessions_registry_checksum": (
            f"CREATE INDEX idx_matrix_identification_sessions_registry_checksum ON public.{table} "
            "USING btree (registry_checksum_sha256)"
        ),
    }
    return {
        "columns": dict(REQUIRED_COLUMNS),
        "nullable": {name: False for name in REQUIRED_COLUMNS},
        "defaults": dict(REQUIRED_DEFAULTS),
        "primary_key_columns": ["session_id"],
        "index_definitions": index_definitions,
        "check_constraints": ["CHECK (revision >= 0)"],
    }


def _migration_statements() -> list[str]:
    migration = (
        Path(__file__).resolve().parents[1]
        / "migrations"
        / "612_matrix_identification_sessions.sql"
    ).read_text(encoding="utf-8")
    statements: list[str] = []
    for raw_statement in migration.split(";"):
        sql = "\n".join(
            line for line in raw_statement.splitlines() if not line.strip().startswith("--")
        ).strip()
        if not sql or sql.upper() in {"BEGIN", "COMMIT"}:
            continue
        statements.append(sql)
    return statements


def _reset_live_migration_612_schema(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS matrix_identification_sessions CASCADE")
        for sql in _migration_statements():
            conn.execute(sql)


def _drop_live_matrix_schema(dsn: str) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP TABLE IF EXISTS matrix_identification_sessions CASCADE")


def test_complete_migration_612_schema_is_activation_ready_snapshot():
    result = assess_matrix_session_schema(**_valid_snapshot())

    assert result["migration_612_schema_ready"] is True
    assert result["missing_columns"] == []
    assert result["type_mismatches"] == []
    assert result["nullable_mismatches"] == []
    assert result["default_mismatches"] == []
    assert result["primary_key_ok"] is True
    assert result["missing_indexes"] == []
    assert result["index_definition_mismatches"] == []
    assert result["revision_nonnegative_check_ok"] is True


def test_missing_index_blocks_schema_readiness():
    snapshot = _valid_snapshot()
    removed = sorted(REQUIRED_INDEX_COLUMNS)[0]
    snapshot["index_definitions"].pop(removed)

    result = assess_matrix_session_schema(**snapshot)

    assert result["migration_612_schema_ready"] is False
    assert result["missing_indexes"] == [removed]


def test_same_name_wrong_index_columns_block_schema_readiness():
    snapshot = _valid_snapshot()
    name = "idx_matrix_identification_sessions_registry"
    snapshot["index_definitions"][name] = (
        "CREATE INDEX idx_matrix_identification_sessions_registry "
        "ON public.matrix_identification_sessions USING btree (registry_version, registry_id)"
    )

    result = assess_matrix_session_schema(**snapshot)

    assert result["migration_612_schema_ready"] is False
    assert result["missing_indexes"] == []
    assert result["index_definition_mismatches"][0]["index"] == name


def test_partial_same_name_index_does_not_satisfy_migration_contract():
    snapshot = _valid_snapshot()
    name = "idx_matrix_identification_sessions_registry_checksum"
    snapshot["index_definitions"][name] = (
        "CREATE INDEX idx_matrix_identification_sessions_registry_checksum "
        "ON public.matrix_identification_sessions USING btree (registry_checksum_sha256) "
        "WHERE status = 'active'::text"
    )

    result = assess_matrix_session_schema(**snapshot)

    assert result["migration_612_schema_ready"] is False
    assert result["index_definition_mismatches"][0]["index"] == name


def test_wrong_primary_key_blocks_schema_readiness():
    snapshot = _valid_snapshot()
    snapshot["primary_key_columns"] = ["owner", "session_id"]

    result = assess_matrix_session_schema(**snapshot)

    assert result["migration_612_schema_ready"] is False
    assert result["primary_key_ok"] is False


def test_column_type_drift_blocks_schema_readiness():
    snapshot = _valid_snapshot()
    snapshot["columns"]["record"] = "text"

    result = assess_matrix_session_schema(**snapshot)

    assert result["migration_612_schema_ready"] is False
    assert result["type_mismatches"] == [
        {"column": "record", "expected": "jsonb", "actual": "text"}
    ]


def test_missing_required_column_blocks_schema_readiness():
    snapshot = _valid_snapshot()
    snapshot["columns"].pop("registry_checksum_sha256")

    result = assess_matrix_session_schema(**snapshot)

    assert result["migration_612_schema_ready"] is False
    assert result["missing_columns"] == ["registry_checksum_sha256"]


def test_nullable_drift_blocks_schema_readiness():
    snapshot = _valid_snapshot()
    snapshot["nullable"]["owner"] = True

    result = assess_matrix_session_schema(**snapshot)

    assert result["migration_612_schema_ready"] is False
    assert result["nullable_mismatches"] == ["owner"]


def test_default_drift_blocks_schema_readiness():
    snapshot = _valid_snapshot()
    snapshot["defaults"]["revision"] = "1"

    result = assess_matrix_session_schema(**snapshot)

    assert result["migration_612_schema_ready"] is False
    assert result["default_mismatches"] == [
        {"column": "revision", "expected": "0", "actual": "1"}
    ]


def test_missing_revision_nonnegative_check_blocks_schema_readiness():
    snapshot = _valid_snapshot()
    snapshot["check_constraints"] = []

    result = assess_matrix_session_schema(**snapshot)

    assert result["migration_612_schema_ready"] is False
    assert result["revision_nonnegative_check_ok"] is False


def test_preflight_without_database_url_is_read_only_and_not_ready(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CALYX_MATRIX_SESSION_DURABLE_ENABLED", raising=False)

    result = matrix_session_persistence_preflight()

    assert result["database_url_configured"] is False
    assert result["connectivity"] is False
    assert result["read_only"] is False
    assert result["activation_ready"] is False
    assert result["activated"] is False
    assert result["blockers"] == ["DATABASE_URL_NOT_CONFIGURED"]
    assert result["migration_applied_by_preflight"] is False
    assert result["environment_changed_by_preflight"] is False


def test_preflight_never_claims_activation_from_schema_readiness_alone(monkeypatch):
    monkeypatch.delenv("CALYX_MATRIX_SESSION_DURABLE_ENABLED", raising=False)
    assert assess_matrix_session_schema(**_valid_snapshot())[
        "migration_612_schema_ready"
    ] is True


@pytest.mark.skipif(
    not os.environ.get("CALYX_MATRIX_PREFLIGHT_TEST_DATABASE_URL"),
    reason="PostgreSQL Matrix preflight DSN not configured",
)
def test_live_postgres_exact_migration_612_passes_read_only_preflight():
    dsn = os.environ["CALYX_MATRIX_PREFLIGHT_TEST_DATABASE_URL"]
    _reset_live_migration_612_schema(dsn)
    try:
        result = inspect_matrix_session_database(dsn)
        assert result["connectivity"] is True
        assert result["read_only"] is True
        assert result["table_exists"] is True
        assert result["migration_612_schema_ready"] is True
        assert result["blockers"] == []
    finally:
        _drop_live_matrix_schema(dsn)


@pytest.mark.skipif(
    not os.environ.get("CALYX_MATRIX_PREFLIGHT_TEST_DATABASE_URL"),
    reason="PostgreSQL Matrix preflight DSN not configured",
)
def test_live_postgres_nullability_drift_fails_closed():
    dsn = os.environ["CALYX_MATRIX_PREFLIGHT_TEST_DATABASE_URL"]
    _reset_live_migration_612_schema(dsn)
    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute(
                "ALTER TABLE matrix_identification_sessions ALTER COLUMN owner DROP NOT NULL"
            )
        result = inspect_matrix_session_database(dsn)
        assert result["migration_612_schema_ready"] is False
        assert result["nullable_mismatches"] == ["owner"]
        assert "MATRIX_SESSION_NULLABILITY_MISMATCH" in result["blockers"]
    finally:
        _drop_live_matrix_schema(dsn)
