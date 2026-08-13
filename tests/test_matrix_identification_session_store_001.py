import json
from copy import deepcopy
from pathlib import Path

import pytest

from runtime.matrix_identification_session_store import (
    FileMatrixSessionStore,
    MatrixSessionPersistenceError,
    PostgresMatrixSessionStore,
    configured_matrix_session_store,
    durable_requested,
    matrix_session_persistence_status,
)


def _record(owner: str = "owner-a") -> dict:
    return {
        "schema_version": "matrix-identification-session/v1",
        "session_id": "11111111-1111-1111-1111-111111111111",
        "actor": owner,
        "registry": {
            "registry_id": "demo",
            "version": "1",
            "checksum_sha256": "abc123",
        },
        "revision": 0,
        "status": "active",
        "created_at": "2026-08-11T22:00:00+00:00",
        "updated_at": "2026-08-11T22:00:00+00:00",
        "observations": [],
    }


def test_file_store_preserves_owner_scope_and_record(tmp_path: Path):
    store = FileMatrixSessionStore(tmp_path)
    record = _record()
    store.save(record)

    assert record["persistence_version"] == 1
    restored = store.get(record["session_id"], access_actor="owner-a")
    assert restored == record
    assert store.get(record["session_id"], access_actor="owner-b") is None
    assert store.get(record["session_id"], access_actor=None) == record
    status = store.status()
    assert status["durable"] is False
    assert status["ready"] is True
    assert status["optimistic_concurrency"] is True


def test_file_store_rejects_stale_revision_overwrite(tmp_path: Path):
    store = FileMatrixSessionStore(tmp_path)
    current = _record()
    current["revision"] = 2
    current["observations"] = [{"observation_id": "newer"}]
    store.save(current)

    stale = deepcopy(current)
    stale["revision"] = 1
    stale["observations"] = [{"observation_id": "stale"}]
    with pytest.raises(MatrixSessionPersistenceError, match="STALE_REVISION"):
        store.save(stale)

    restored = store.get(current["session_id"], access_actor="owner-a")
    assert restored["revision"] == 2
    assert restored["observations"] == [{"observation_id": "newer"}]


def test_file_store_rejects_same_revision_stale_writer(tmp_path: Path):
    store = FileMatrixSessionStore(tmp_path)
    original = _record()
    store.save(original)

    writer_a = deepcopy(original)
    writer_b = deepcopy(original)

    writer_a["latest_evaluation"] = {"candidate": "A"}
    store.save(writer_a)
    assert writer_a["persistence_version"] == 2

    writer_b["identification_reports"] = [{"report_id": "stale-write"}]
    with pytest.raises(MatrixSessionPersistenceError, match="stale persistence version"):
        store.save(writer_b)

    restored = store.get(original["session_id"], access_actor="owner-a")
    assert restored["persistence_version"] == 2
    assert restored["latest_evaluation"] == {"candidate": "A"}
    assert "identification_reports" not in restored


def test_legacy_zero_version_record_is_adopted_once(tmp_path: Path):
    store = FileMatrixSessionStore(tmp_path)
    legacy = _record()
    path = tmp_path / f"{legacy['session_id']}.json"
    path.write_text(json.dumps(legacy), encoding="utf-8")

    writer_a = store.get(legacy["session_id"], access_actor="owner-a")
    writer_b = deepcopy(writer_a)
    assert "persistence_version" not in writer_a

    writer_a["latest_evaluation"] = {"candidate": "legacy-A"}
    store.save(writer_a)
    assert writer_a["persistence_version"] == 1

    writer_b["identification_reports"] = [{"report_id": "legacy-stale"}]
    with pytest.raises(MatrixSessionPersistenceError, match="stale persistence version"):
        store.save(writer_b)

    restored = store.get(legacy["session_id"], access_actor="owner-a")
    assert restored["persistence_version"] == 1
    assert restored["latest_evaluation"] == {"candidate": "legacy-A"}
    assert "identification_reports" not in restored


def test_missing_record_rejects_nonzero_persistence_version(tmp_path: Path):
    store = FileMatrixSessionStore(tmp_path)
    record = _record()
    record["persistence_version"] = 4

    with pytest.raises(MatrixSessionPersistenceError, match="missing record"):
        store.save(record)


def test_explicit_root_always_selects_file_store_for_bounded_tests(
    tmp_path: Path, monkeypatch
):
    monkeypatch.setenv("CALYX_MATRIX_SESSION_DURABLE_ENABLED", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    store = configured_matrix_session_store(root=tmp_path)
    assert isinstance(store, FileMatrixSessionStore)
    assert store.status()["mode"] == "file_ephemeral"


def test_durable_mode_fails_closed_without_database_url(monkeypatch):
    monkeypatch.setenv("CALYX_MATRIX_SESSION_DURABLE_ENABLED", "true")
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert durable_requested() is True
    with pytest.raises(MatrixSessionPersistenceError, match="DATABASE_URL_REQUIRED"):
        configured_matrix_session_store()

    status = matrix_session_persistence_status()
    assert status["durable_requested"] is True
    assert status["durable"] is True
    assert status["ready"] is False
    assert status["optimistic_concurrency"] is True
    assert status["legacy_zero_version_adoption"] is True
    assert "DATABASE_URL_REQUIRED" in status["error"]


def test_default_mode_remains_explicitly_ephemeral_until_governed_activation(
    monkeypatch, tmp_path: Path
):
    monkeypatch.delenv("CALYX_MATRIX_SESSION_DURABLE_ENABLED", raising=False)
    monkeypatch.setenv("CALYX_MATRIX_SESSION_DIR", str(tmp_path))

    store = configured_matrix_session_store()
    status = store.status()
    assert status["mode"] == "file_ephemeral"
    assert status["durable"] is False
    assert status["optimistic_concurrency"] is True
    assert "not restart-durable" in status["warning"]


def test_postgres_store_rejects_partial_schema_before_read(monkeypatch):
    store = PostgresMatrixSessionStore("postgresql://example.invalid/test")
    monkeypatch.setattr(
        store,
        "schema_inspection",
        lambda: {
            "migration_612_schema_ready": False,
            "blockers": ["MATRIX_SESSION_REQUIRED_INDEXES_MISSING"],
        },
    )

    with pytest.raises(MatrixSessionPersistenceError, match="REQUIRED_INDEXES_MISSING"):
        store.get(_record()["session_id"], access_actor="owner-a")


def test_postgres_store_rejects_partial_schema_before_write(monkeypatch):
    store = PostgresMatrixSessionStore("postgresql://example.invalid/test")
    monkeypatch.setattr(
        store,
        "schema_inspection",
        lambda: {
            "migration_612_schema_ready": False,
            "blockers": ["MATRIX_SESSION_COLUMN_TYPE_MISMATCH"],
        },
    )

    with pytest.raises(MatrixSessionPersistenceError, match="COLUMN_TYPE_MISMATCH"):
        store.save(_record())


def test_postgres_status_exposes_full_schema_contract_and_cas(monkeypatch):
    store = PostgresMatrixSessionStore("postgresql://example.invalid/test")
    monkeypatch.setattr(
        store,
        "schema_inspection",
        lambda: {
            "migration_612_schema_ready": True,
            "blockers": [],
            "missing_columns": [],
            "missing_indexes": [],
        },
    )

    status = store.status()
    assert status["ready"] is True
    assert status["schema_contract"]["migration_612_schema_ready"] is True
    assert status["optimistic_concurrency"] is True
    assert status["legacy_zero_version_adoption"] is True


def test_postgres_nonzero_version_uses_atomic_compare_and_swap(monkeypatch):
    store = PostgresMatrixSessionStore("postgresql://example.invalid/test")
    monkeypatch.setattr(store, "_require_schema", lambda: None)
    captured: dict[str, object] = {}

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql, params):
            captured["sql"] = sql
            captured["params"] = params

        def fetchone(self):
            return None

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return Cursor()

        def commit(self):
            captured["committed"] = True

    monkeypatch.setattr(
        "runtime.matrix_identification_session_store.psycopg.connect",
        lambda *args, **kwargs: Connection(),
    )

    record = _record()
    record["persistence_version"] = 3
    record["latest_evaluation"] = {"candidate": "newer"}

    with pytest.raises(MatrixSessionPersistenceError, match="stale persistence version"):
        store.save(record)

    sql = str(captured["sql"])
    params = captured["params"]
    assert "UPDATE matrix_identification_sessions" in sql
    assert "record->>'persistence_version'" in sql
    assert params[-1] == 3
    assert "committed" not in captured
