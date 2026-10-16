from __future__ import annotations

import pytest

from app.atlas_intelligence.assembler import assemble_map_manifest
from app.atlas_intelligence.fixtures import build_vertical_slice
from app.atlas_intelligence.models import ThematicMapRequest


def test_duplicate_layer_single_repeated_id() -> None:
    """Test that a single repeated layer id raises ValueError with correct message."""
    result = build_vertical_slice()
    request = ThematicMapRequest(
        map_id="duplicate-test-1",
        title="Duplicate layer test",
        layer_ids=["layer:taxon-distribution", "layer:taxon-distribution"],
        projection="EPSG:4326",
    )

    with pytest.raises(ValueError, match="duplicate layer references: \\['layer:taxon-distribution'\\]"):
        assemble_map_manifest(request, result["layers"], result["datasets"])


def test_duplicate_layer_multiple_repeated_ids() -> None:
    """Test that multiple repeated layer ids are sorted and unique in error message."""
    result = build_vertical_slice()
    request = ThematicMapRequest(
        map_id="duplicate-test-2",
        title="Duplicate layer test",
        layer_ids=[
            "layer:protected-area",
            "layer:taxon-distribution",
            "layer:protected-area",
            "layer:taxon-distribution",
        ],
        projection="EPSG:4326",
    )

    with pytest.raises(ValueError, match="duplicate layer references: \\['layer:protected-area', 'layer:taxon-distribution'\\]"):
        assemble_map_manifest(request, result["layers"], result["datasets"])


def test_distinct_layer_ids_succeed() -> None:
    """Test that distinct layer ids produce a valid manifest as before."""
    result = build_vertical_slice()

    # Use the original request with all distinct ids
    manifest = assemble_map_manifest(result["request"], result["layers"], result["datasets"])

    # Verify the manifest is valid and contains all layers
    assert manifest.ordered_layer_ids == [
        "layer:taxon-distribution",
        "layer:elevation",
        "layer:protected-area",
        "layer:sampling-effort",
    ]
    assert len(manifest.manifest_checksum) == 64
    # Verify it's the same checksum as the fixture (deterministic)
    assert manifest.manifest_checksum == result["manifest"].manifest_checksum
