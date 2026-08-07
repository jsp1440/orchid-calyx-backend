from __future__ import annotations

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.atlas_intelligence.assembler import assemble_map_manifest
from app.atlas_intelligence.fixtures import build_vertical_slice
from app.atlas_intelligence.models import (
    AtlasReasoningResponse,
    ReasoningStatement,
    SpatialDataset,
    ThematicMapRequest,
)


def test_vertical_slice_is_complete_and_searchable() -> None:
    result = build_vertical_slice()

    manifest = result["manifest"]
    reasoning = result["reasoning"]
    brain_records = result["brain_records"]

    assert manifest.ordered_layer_ids == [
        "layer:taxon-distribution",
        "layer:elevation",
        "layer:protected-area",
        "layer:sampling-effort",
    ]
    assert len(manifest.manifest_checksum) == 64
    assert {statement.category for statement in reasoning.statements} == {
        "observation",
        "inference",
        "uncertainty",
        "unavailable",
    }
    assert {record.object_type for record in brain_records} == {
        "architecture",
        "decision",
        "reproducibility",
    }
    assert all(record.aliases for record in brain_records)


def test_manifest_assembly_is_deterministic() -> None:
    result = build_vertical_slice()
    first = result["manifest"]
    second = assemble_map_manifest(result["request"], result["layers"], result["datasets"])

    assert first.model_dump() == second.model_dump()


def test_missing_layer_reference_fails_closed() -> None:
    result = build_vertical_slice()
    request = ThematicMapRequest(
        map_id="broken-map",
        title="Broken map",
        layer_ids=["layer:does-not-exist"],
        projection="EPSG:4326",
    )

    with pytest.raises(ValueError, match="unknown layer references"):
        assemble_map_manifest(request, result["layers"], result["datasets"])


def test_biodiversity_layer_requires_resolved_taxon() -> None:
    result = build_vertical_slice()
    datasets = deepcopy(result["datasets"])
    datasets[0] = datasets[0].model_copy(update={"taxon_id": None})

    with pytest.raises(ValueError, match="requires resolved taxon identity"):
        assemble_map_manifest(result["request"], result["layers"], datasets)


def test_temporal_layer_requires_temporal_extent() -> None:
    result = build_vertical_slice()
    datasets = deepcopy(result["datasets"])
    datasets[3] = datasets[3].model_copy(update={"temporal_extent": None})

    with pytest.raises(ValueError, match="requires temporal coverage"):
        assemble_map_manifest(result["request"], result["layers"], datasets)


def test_invalid_crs_is_rejected() -> None:
    result = build_vertical_slice()
    payload = result["datasets"][0].model_dump()
    payload["crs"] = "WGS84-ish"

    with pytest.raises(ValidationError):
        SpatialDataset.model_validate(payload)


def test_missing_license_or_attribution_is_rejected() -> None:
    result = build_vertical_slice()
    payload = result["datasets"][0].model_dump()
    payload["lineage"]["license"] = ""

    with pytest.raises(ValidationError):
        SpatialDataset.model_validate(payload)

    payload = result["datasets"][0].model_dump()
    payload["lineage"]["attribution"] = ""
    with pytest.raises(ValidationError):
        SpatialDataset.model_validate(payload)


def test_unsupported_causal_language_is_rejected() -> None:
    with pytest.raises(ValidationError, match="unsupported causal language"):
        AtlasReasoningResponse(
            response_id="reasoning:bad",
            map_id="bad",
            statements=[
                ReasoningStatement(
                    statement_id="bad-1",
                    category="inference",
                    text="Elevation causes this orchid distribution.",
                    supporting_layer_ids=["layer:elevation"],
                    confidence=0.5,
                )
            ],
        )


def test_inference_without_supporting_layers_is_rejected() -> None:
    with pytest.raises(ValidationError, match="inferences require supporting layers"):
        ReasoningStatement(
            statement_id="unsupported",
            category="inference",
            text="A pattern may exist.",
            confidence=0.3,
        )
