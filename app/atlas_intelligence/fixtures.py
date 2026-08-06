from __future__ import annotations

from datetime import datetime, timezone

from .assembler import assemble_brain_records, assemble_map_manifest, build_reasoning_response
from .models import AtlasLayer, SourceLineage, SpatialDataset, SpatialExtent, TemporalExtent, ThematicMapRequest


def _lineage(source_id: str, checksum_char: str, license_name: str = "CC BY 4.0") -> SourceLineage:
    return SourceLineage(
        source_id=source_id,
        source_version="2026.08",
        source_uri=f"fixture://{source_id}",
        license=license_name,
        attribution=f"Fixture attribution for {source_id}",
        acquired_at=datetime(2026, 8, 6, tzinfo=timezone.utc),
        checksum=checksum_char * 64,
    )


def build_vertical_slice() -> dict[str, object]:
    extent = SpatialExtent(west=-80, south=-15, east=-65, north=2)
    temporal = TemporalExtent(
        start=datetime(1990, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    datasets = [
        SpatialDataset(
            dataset_id="ds:taxon-occurrence",
            title="Fixture orchid taxon occurrences",
            version="1.0.0",
            crs="EPSG:4326",
            extent=extent,
            temporal_extent=temporal,
            lineage=_lineage("taxon-occurrence", "a"),
            taxon_id="taxon:fixture-orchid",
        ),
        SpatialDataset(
            dataset_id="ds:elevation",
            title="Fixture elevation surface",
            version="1.0.0",
            crs="EPSG:4326",
            extent=extent,
            lineage=_lineage("elevation", "b", "CC0-1.0"),
        ),
        SpatialDataset(
            dataset_id="ds:protected-area",
            title="Fixture protected areas",
            version="1.0.0",
            crs="EPSG:4326",
            extent=extent,
            lineage=_lineage("protected-area", "c"),
        ),
        SpatialDataset(
            dataset_id="ds:sampling-effort",
            title="Fixture sampling effort",
            version="1.0.0",
            crs="EPSG:4326",
            extent=extent,
            temporal_extent=temporal,
            lineage=_lineage("sampling-effort", "d"),
        ),
    ]
    layers = [
        AtlasLayer(
            layer_id="layer:taxon-distribution",
            title="Orchid distribution",
            kind="biodiversity",
            dataset_id="ds:taxon-occurrence",
            geometry_type="point",
            variable="occurrence_count",
            units="records",
            classification="density",
            temporal_required=True,
        ),
        AtlasLayer(
            layer_id="layer:elevation",
            title="Elevation",
            kind="earth_science",
            dataset_id="ds:elevation",
            geometry_type="raster",
            variable="elevation",
            units="m",
            classification="continuous",
        ),
        AtlasLayer(
            layer_id="layer:protected-area",
            title="Protected areas",
            kind="conservation",
            dataset_id="ds:protected-area",
            geometry_type="polygon",
            variable="protected_status",
            classification="categorical",
        ),
        AtlasLayer(
            layer_id="layer:sampling-effort",
            title="Sampling effort",
            kind="sampling_effort",
            dataset_id="ds:sampling-effort",
            geometry_type="hexagon",
            variable="record_count",
            units="records",
            classification="density",
            temporal_required=True,
        ),
    ]
    request = ThematicMapRequest(
        map_id="atlas-fixture-001",
        title="Fixture Orchid Distribution and Earth Systems Context",
        layer_ids=[layer.layer_id for layer in layers],
        projection="EPSG:4326",
        audience="research",
        output_formats=["json", "svg"],
    )
    manifest = assemble_map_manifest(request, layers, datasets)
    reasoning = build_reasoning_response(manifest, layers)
    brain_records = assemble_brain_records(manifest)
    return {
        "datasets": datasets,
        "layers": layers,
        "request": request,
        "manifest": manifest,
        "reasoning": reasoning,
        "brain_records": brain_records,
    }
