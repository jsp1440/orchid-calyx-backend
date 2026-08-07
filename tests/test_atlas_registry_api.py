from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.atlas_intelligence.api import load_fixture_registry, router
from app.atlas_intelligence.fixtures import build_vertical_slice
from app.atlas_intelligence.models import MapArtifact
from app.atlas_intelligence.registry import AtlasRegistry


def _registry() -> AtlasRegistry:
    result = build_vertical_slice()
    registry = AtlasRegistry()
    for dataset in result["datasets"]:
        registry.register_dataset(dataset)
    for layer in result["layers"]:
        registry.register_layer(layer)
    registry.register_manifest(result["manifest"])
    return registry


def test_registry_vertical_slice_counts_and_order() -> None:
    registry = _registry()
    assert registry.status() == {"datasets": 4, "layers": 4, "manifests": 1, "artifacts": 0}
    assert [layer.layer_id for layer in registry.list_layers()] == sorted(registry.layers)
    assert [layer.kind for layer in registry.list_layers(kind="earth_science")] == ["earth_science"]


def test_registry_is_idempotent_but_rejects_conflicting_identity() -> None:
    result = build_vertical_slice()
    registry = AtlasRegistry()
    dataset = result["datasets"][0]
    registry.register_dataset(dataset)
    registry.register_dataset(dataset)

    conflicting = dataset.model_copy(update={"title": "Conflicting title"})
    with pytest.raises(ValueError, match="different content"):
        registry.register_dataset(conflicting)


def test_registry_rejects_orphan_layer_and_manifest() -> None:
    result = build_vertical_slice()
    registry = AtlasRegistry()
    with pytest.raises(ValueError, match="unregistered dataset"):
        registry.register_layer(result["layers"][0])
    with pytest.raises(ValueError, match="unregistered layers"):
        registry.register_manifest(result["manifest"])


def test_artifact_requires_matching_manifest_lineage() -> None:
    registry = _registry()
    manifest = next(iter(registry.manifests.values()))
    artifact = MapArtifact(
        artifact_id="artifact:atlas-fixture-001:svg",
        map_id=manifest.map_id,
        format="svg",
        storage_uri="fixture://artifacts/atlas-fixture-001.svg",
        checksum="e" * 64,
        source_manifest_checksum=manifest.manifest_checksum,
        created_at=datetime(2026, 8, 6, tzinfo=timezone.utc),
    )
    registry.register_artifact(artifact)
    assert registry.status()["artifacts"] == 1

    invalid = artifact.model_copy(
        update={"artifact_id": "artifact:bad", "source_manifest_checksum": "f" * 64}
    )
    with pytest.raises(ValueError, match="does not match"):
        registry.register_artifact(invalid)


def test_read_only_api_exposes_candidate_records() -> None:
    load_fixture_registry()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    status = client.get("/atlas/status")
    assert status.status_code == 200
    assert status.json()["publication_enabled"] is False
    assert status.json()["layers"] == 4

    layers = client.get("/atlas/layers", params={"kind": "earth_science"})
    assert layers.status_code == 200
    assert [item["layer_id"] for item in layers.json()] == ["layer:elevation"]

    manifest = client.get("/atlas/maps/atlas-fixture-001")
    assert manifest.status_code == 200
    assert manifest.json()["publication_state"] == "candidate"

    missing = client.get("/atlas/layers/layer:missing")
    assert missing.status_code == 404
