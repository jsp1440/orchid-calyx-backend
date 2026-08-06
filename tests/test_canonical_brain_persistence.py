from __future__ import annotations

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
    assert [item.object_id for item in restored.aligned_intents("architecture:atlas")] == [
        "intent:preserve-biodiversity"
    ]


def test_json_repository_serialization_is_deterministic(tmp_path) -> None:
    registry = build_canonical_brain_fixture()
    path = tmp_path / "brain.json"
    repository = JsonBrainSnapshotRepository(path)

    repository.save(registry)
    first = path.read_text(encoding="utf-8")
    repository.save(registry)
    second = path.read_text(encoding="utf-8")

    assert first == second


def test_json_repository_detects_tampering(tmp_path) -> None:
    registry = build_canonical_brain_fixture()
    path = tmp_path / "brain.json"
    repository = JsonBrainSnapshotRepository(path)
    repository.save(registry)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["objects"][0]["title"] = "Tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="checksum mismatch"):
        repository.load()


def test_json_repository_requires_existing_snapshot(tmp_path) -> None:
    repository = JsonBrainSnapshotRepository(tmp_path / "missing.json")

    with pytest.raises(FileNotFoundError):
        repository.load()
