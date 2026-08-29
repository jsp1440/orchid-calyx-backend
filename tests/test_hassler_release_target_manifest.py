from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.hassler_release_target import load_hassler_release_target

VALID = {
    "filename": "WorldOrchids 26-09 (Sep 3 2026).csv",
    "size_bytes": 12345,
    "sha256": "a" * 64,
    "version_label": "26-09",
    "acquired_at": "2026-09-03",
    "execution_confirmation": "UPLOAD_WORLD_ORCHIDS_26_09",
}


def _manifest(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "release.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_new_release_identity_is_data_not_python(tmp_path: Path) -> None:
    target = load_hassler_release_target(_manifest(tmp_path, VALID))
    assert target.filename == VALID["filename"]
    assert target.size_bytes == VALID["size_bytes"]
    assert target.sha256 == VALID["sha256"]
    assert target.version_label == VALID["version_label"]
    assert target.acquired_at == VALID["acquired_at"]
    assert target.execution_confirmation == VALID["execution_confirmation"]
    assert target.as_dict()["execution_authorized"] is False
    assert target.as_dict()["taxonomy_activation_authorized"] is False
    assert target.as_dict()["knowledge_graph_mutation_authorized"] is False


def test_environment_can_select_next_verified_release_without_code_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _manifest(tmp_path, VALID)
    monkeypatch.setenv("CALYX_HASSLER_RELEASE_MANIFEST", str(path))
    target = load_hassler_release_target()
    assert target.filename == VALID["filename"]
    assert target.sha256 == VALID["sha256"]


@pytest.mark.parametrize(
    "mutation",
    [
        {"filename": "../WorldOrchids.csv"},
        {"size_bytes": 0},
        {"size_bytes": True},
        {"sha256": "not-a-sha"},
        {"acquired_at": "September 3 2026"},
        {"execution_confirmation": "YES_UPLOAD_IT"},
    ],
)
def test_malformed_or_unsafe_manifest_fails_closed(
    tmp_path: Path, mutation: dict
) -> None:
    payload = {**VALID, **mutation}
    with pytest.raises(ValueError):
        load_hassler_release_target(_manifest(tmp_path, payload))


def test_non_object_manifest_fails_with_type_error(tmp_path: Path) -> None:
    path = tmp_path / "release.json"
    path.write_text(json.dumps([VALID]), encoding="utf-8")
    with pytest.raises(TypeError):
        load_hassler_release_target(path)


def test_repository_default_manifest_remains_current_verified_release() -> None:
    target = load_hassler_release_target()
    assert target.filename == "WorldOrchids 26-08 (Aug 2 2026).csv"
    assert target.size_bytes == 11_529_836
    assert (
        target.sha256
        == "e5be9268e1a48cb0e1777137ac386a9a870f3581c35f10678c9b810c59688c6f"
    )
    assert target.version_label == "26-08"
    assert target.acquired_at == "2026-08-02"
    assert target.execution_confirmation == "UPLOAD_WORLD_ORCHIDS_26_08"


def test_discovery_adapter_applies_manifest_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _manifest(tmp_path, VALID)
    monkeypatch.setenv("CALYX_HASSLER_RELEASE_MANIFEST", str(path))
    from scripts import discover_hassler_release_target as adapter

    applied = adapter.apply_release_target()
    assert applied["filename"] == VALID["filename"]
    assert adapter.discovery.EXPECTED_FILENAME == VALID["filename"]
    assert adapter.discovery.EXPECTED_SHA256 == VALID["sha256"]


def test_guarded_upload_adapter_applies_all_manifest_guards(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _manifest(tmp_path, VALID)
    monkeypatch.setenv("CALYX_HASSLER_RELEASE_MANIFEST", str(path))
    from scripts import upload_hassler_release_target as adapter

    applied = adapter.apply_release_target()
    assert applied["filename"] == VALID["filename"]
    assert adapter.uploader.EXPECTED_FILENAME == VALID["filename"]
    assert adapter.uploader.EXPECTED_SIZE_BYTES == VALID["size_bytes"]
    assert adapter.uploader.EXPECTED_SHA256 == VALID["sha256"]
    assert adapter.uploader.VERSION_LABEL == VALID["version_label"]
    assert adapter.uploader.ACQUIRED_AT == VALID["acquired_at"]
    assert adapter.uploader.EXECUTION_CONFIRMATION == VALID["execution_confirmation"]
