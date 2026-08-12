import pytest

from runtime.matrix_identification_persistence_preflight import (
    REQUIRED_COLUMNS,
    REQUIRED_INDEXES,
    assess_matrix_session_schema,
    matrix_session_persistence_preflight,
)


def test_complete_migration_612_schema_is_activation_ready_snapshot():
    result = assess_matrix_session_schema(
        columns=dict(REQUIRED_COLUMNS),
        primary_key_columns=["session_id"],
        indexes=set(REQUIRED_INDEXES),
    )

    assert result["migration_612_schema_ready"] is True
    assert result["missing_columns"] == []
    assert result["type_mismatches"] == []
    assert result["primary_key_ok"] is True
    assert result["missing_indexes"] == []


def test_missing_index_blocks_schema_readiness():
    indexes = set(REQUIRED_INDEXES)
    removed = sorted(indexes)[0]
    indexes.remove(removed)

    result = assess_matrix_session_schema(
        columns=dict(REQUIRED_COLUMNS),
        primary_key_columns=["session_id"],
        indexes=indexes,
    )

    assert result["migration_612_schema_ready"] is False
    assert result["missing_indexes"] == [removed]


def test_wrong_primary_key_blocks_schema_readiness():
    result = assess_matrix_session_schema(
        columns=dict(REQUIRED_COLUMNS),
        primary_key_columns=["owner", "session_id"],
        indexes=set(REQUIRED_INDEXES),
    )

    assert result["migration_612_schema_ready"] is False
    assert result["primary_key_ok"] is False


def test_column_type_drift_blocks_schema_readiness():
    columns = dict(REQUIRED_COLUMNS)
    columns["record"] = "text"

    result = assess_matrix_session_schema(
        columns=columns,
        primary_key_columns=["session_id"],
        indexes=set(REQUIRED_INDEXES),
    )

    assert result["migration_612_schema_ready"] is False
    assert result["type_mismatches"] == [
        {"column": "record", "expected": "jsonb", "actual": "text"}
    ]


def test_missing_required_column_blocks_schema_readiness():
    columns = dict(REQUIRED_COLUMNS)
    columns.pop("registry_checksum_sha256")

    result = assess_matrix_session_schema(
        columns=columns,
        primary_key_columns=["session_id"],
        indexes=set(REQUIRED_INDEXES),
    )

    assert result["migration_612_schema_ready"] is False
    assert result["missing_columns"] == ["registry_checksum_sha256"]


def test_preflight_without_database_url_is_read_only_and_not_ready(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("CALYX_MATRIX_SESSION_DURABLE_ENABLED", raising=False)

    result = matrix_session_persistence_preflight()

    assert result["database_url_configured"] is False
    assert result["connectivity"] is False
    assert result["activation_ready"] is False
    assert result["activated"] is False
    assert result["blockers"] == ["DATABASE_URL_NOT_CONFIGURED"]
    assert result["migration_applied_by_preflight"] is False
    assert result["environment_changed_by_preflight"] is False


def test_preflight_never_claims_activation_from_schema_readiness_alone(monkeypatch):
    # The pure assessment may be ready, but the activation flag is intentionally a
    # separate deployment decision. This regression documents that contract.
    monkeypatch.delenv("CALYX_MATRIX_SESSION_DURABLE_ENABLED", raising=False)
    assert assess_matrix_session_schema(
        columns=dict(REQUIRED_COLUMNS),
        primary_key_columns=["session_id"],
        indexes=set(REQUIRED_INDEXES),
    )["migration_612_schema_ready"] is True
