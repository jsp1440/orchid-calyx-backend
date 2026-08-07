import json

import pytest

from app.canonical_brain import JsonBrainSnapshotRepository, build_canonical_brain_fixture


def test_json_repository_round_trip_preserves_snapshot(tmp_path) -> None:
    registry = build_canonical_brain_fixture()
    repository = JsonBrainSnapshotRepository(tmp_path / "brain.json")
    saved = repository.save(registry)
    restored = repository.load()
    assert restored.snapshot().snapshot_checksum == saved.snapshot_checksum
    assert restored.get("architecture:atlas") is not None


def test_json_repository_serialization_is_deterministic(tmp_path) -> None:
    path = tmp_path / "brain.json"
    repository = JsonBrainSnapshotRepository(path)
    registry = build_canonical_brain_fixture()
    repository.save(registry)
    first = path.read_text(encoding="utf-8")
    repository.save(registry)
    assert first == path.read_text(encoding="utf-8")


def test_json_repository_detects_tampering(tmp_path) -> None:
    path = tmp_path / "brain.json"
    repository = JsonBrainSnapshotRepository(path)
    repository.save(build_canonical_brain_fixture())
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["objects"][0]["title"] = "Tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="checksum mismatch"):
        repository.load()
