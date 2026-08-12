from pathlib import Path

import pytest

from runtime.matrix_identification_session_store import (
    FileMatrixSessionStore,
    MatrixSessionPersistenceError,
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
    store.save(_record())

    assert store.get(_record()["session_id"], access_actor="owner-a") == _record()
    assert store.get(_record()["session_id"], access_actor="owner-b") is None
    assert store.get(_record()["session_id"], access_actor=None) == _record()
    status = store.status()
    assert status["durable"] is False
    assert status["ready"] is True


def test_file_store_rejects_stale_revision_overwrite(tmp_path: Path):
    store = FileMatrixSessionStore(tmp_path)
    current = _record()
    current["revision"] = 2
    current["observations"] = [{"observation_id": "newer"}]
    store.save(current)

    stale = _record()
    stale["revision"] = 1
    stale["observations"] = [{"observation_id": "stale"}]
    with pytest.raises(MatrixSessionPersistenceError, match="STALE_REVISION"):
        store.save(stale)

    restored = store.get(current["session_id"], access_actor="owner-a")
    assert restored["revision"] == 2
    assert restored["observations"] == [{"observation_id": "newer"}]


def test_explicit_root_always_selects_file_store_for_bounded_tests(tmp_path: Path, monkeypatch):
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
    assert "DATABASE_URL_REQUIRED" in status["error"]


def test_default_mode_remains_explicitly_ephemeral_until_governed_activation(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("CALYX_MATRIX_SESSION_DURABLE_ENABLED", raising=False)
    monkeypatch.setenv("CALYX_MATRIX_SESSION_DIR", str(tmp_path))

    store = configured_matrix_session_store()
    status = store.status()
    assert status["mode"] == "file_ephemeral"
    assert status["durable"] is False
    assert "not restart-durable" in status["warning"]
