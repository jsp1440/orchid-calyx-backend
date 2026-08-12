from pathlib import Path

import pytest

from runtime.matrix_identification_registry_store import (
    FileMatrixRegistryStore,
    MatrixRegistryPersistenceError,
    PostgresMatrixRegistryStore,
    REQUIRED_COLUMNS,
    REQUIRED_INDEXES,
    assess_registry_schema,
    configured_matrix_registry_store,
    matrix_registry_persistence_status,
)


def _record(checksum: str = "a" * 64) -> dict:
    return {
        "schema_version": "matrix-identification-registry/v1",
        "registry_id": "demo",
        "version": "1",
        "title": "Demo registry",
        "scope": {"genus": "Demo"},
        "characters": [{"character": "flower_shape", "label": "Flower shape", "weight": 1}],
        "candidates": [{"taxon_id": "demo:1", "scientific_name": "Demo alpha", "states": {"flower_shape": "round"}}],
        "provenance": {"source": "test"},
        "created_at": "2026-08-12T00:00:00+00:00",
        "created_by": "reviewer",
        "checksum_sha256": checksum,
        "publication_state": "review_required",
    }


def test_file_registry_store_is_immutable_and_idempotent(tmp_path: Path):
    store = FileMatrixRegistryStore(tmp_path)
    first = store.save(_record())
    second = store.save(_record())

    assert first["created"] is True
    assert second["created"] is False
    assert store.get("demo", "1")["checksum_sha256"] == "a" * 64
    assert store.list_records()[0]["registry_id"] == "demo"

    with pytest.raises(ValueError, match="different content"):
        store.save(_record("b" * 64))


def test_explicit_root_stays_file_backed_when_durable_registry_is_requested(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CALYX_MATRIX_REGISTRY_DURABLE_ENABLED", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    store = configured_matrix_registry_store(root=tmp_path)
    assert isinstance(store, FileMatrixRegistryStore)
    assert store.status()["mode"] == "file_ephemeral"


def test_durable_registry_mode_fails_closed_without_database_url(monkeypatch):
    monkeypatch.setenv("CALYX_MATRIX_REGISTRY_DURABLE_ENABLED", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    with pytest.raises(MatrixRegistryPersistenceError, match="DATABASE_URL_REQUIRED"):
        configured_matrix_registry_store()

    status = matrix_registry_persistence_status()
    assert status["durable_requested"] is True
    assert status["ready"] is False
    assert "DATABASE_URL_REQUIRED" in status["error"]


def test_migration_613_contract_requires_columns_primary_key_and_indexes():
    ready = assess_registry_schema(
        columns=dict(REQUIRED_COLUMNS),
        primary_key_columns=["registry_id", "version"],
        indexes=set(REQUIRED_INDEXES),
    )
    assert ready["migration_613_schema_ready"] is True

    missing = set(REQUIRED_INDEXES)
    missing.remove("idx_matrix_registry_checksum")
    blocked = assess_registry_schema(
        columns=dict(REQUIRED_COLUMNS),
        primary_key_columns=["registry_id", "version"],
        indexes=missing,
    )
    assert blocked["migration_613_schema_ready"] is False
    assert blocked["missing_indexes"] == ["idx_matrix_registry_checksum"]


def test_postgres_registry_store_rejects_partial_schema_before_read(monkeypatch):
    store = PostgresMatrixRegistryStore("postgresql://example.invalid/test")
    monkeypatch.setattr(
        store,
        "schema_inspection",
        lambda: {
            "migration_613_schema_ready": False,
            "blockers": ["MATRIX_REGISTRY_REQUIRED_COLUMNS_MISSING"],
        },
    )

    with pytest.raises(MatrixRegistryPersistenceError, match="REQUIRED_COLUMNS_MISSING"):
        store.get("demo", "1")


def test_postgres_registry_store_rejects_partial_schema_before_write(monkeypatch):
    store = PostgresMatrixRegistryStore("postgresql://example.invalid/test")
    monkeypatch.setattr(
        store,
        "schema_inspection",
        lambda: {
            "migration_613_schema_ready": False,
            "blockers": ["MATRIX_REGISTRY_PRIMARY_KEY_MISMATCH"],
        },
    )

    with pytest.raises(MatrixRegistryPersistenceError, match="PRIMARY_KEY_MISMATCH"):
        store.save(_record())
