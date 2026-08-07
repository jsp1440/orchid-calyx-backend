from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from .models import (
    AtlasLayer,
    AtlasReasoningResponse,
    BrainRegistrationRecord,
    ReasoningStatement,
    SpatialDataset,
    ThematicMapManifest,
    ThematicMapRequest,
)


def _canonical_checksum(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def assemble_map_manifest(
    request: ThematicMapRequest,
    layers: list[AtlasLayer],
    datasets: list[SpatialDataset],
) -> ThematicMapManifest:
    layer_by_id = {layer.layer_id: layer for layer in layers}
    dataset_by_id = {dataset.dataset_id: dataset for dataset in datasets}

    if len(layer_by_id) != len(layers):
        raise ValueError("duplicate layer IDs are not allowed")
    if len(dataset_by_id) != len(datasets):
        raise ValueError("duplicate dataset IDs are not allowed")

    missing_layers = [layer_id for layer_id in request.layer_ids if layer_id not in layer_by_id]
    if missing_layers:
        raise ValueError(f"unknown layer references: {sorted(missing_layers)}")

    ordered_layers = [layer_by_id[layer_id] for layer_id in request.layer_ids]
    referenced_datasets: list[SpatialDataset] = []
    for layer in ordered_layers:
        dataset = dataset_by_id.get(layer.dataset_id)
        if dataset is None:
            raise ValueError(f"layer {layer.layer_id} references missing dataset {layer.dataset_id}")
        if layer.temporal_required and dataset.temporal_extent is None:
            raise ValueError(f"layer {layer.layer_id} requires temporal coverage")
        if layer.kind == "biodiversity" and not dataset.taxon_id:
            raise ValueError(f"biodiversity layer {layer.layer_id} requires resolved taxon identity")
        referenced_datasets.append(dataset)

    dataset_versions = {dataset.dataset_id: dataset.version for dataset in sorted(referenced_datasets, key=lambda x: x.dataset_id)}
    lineage_checksums = {
        dataset.dataset_id: dataset.lineage.checksum
        for dataset in sorted(referenced_datasets, key=lambda x: x.dataset_id)
    }
    core = {
        "schema_version": "1.0.0",
        "map_id": request.map_id,
        "title": request.title,
        "projection": request.projection,
        "audience": request.audience,
        "ordered_layer_ids": request.layer_ids,
        "dataset_versions": dataset_versions,
        "lineage_checksums": lineage_checksums,
        "output_formats": request.output_formats,
        "publication_state": "candidate",
    }
    return ThematicMapManifest(**core, manifest_checksum=_canonical_checksum(core))


def build_reasoning_response(manifest: ThematicMapManifest, layers: list[AtlasLayer]) -> AtlasReasoningResponse:
    layer_by_id = {layer.layer_id: layer for layer in layers}
    selected = [layer_by_id[layer_id] for layer_id in manifest.ordered_layer_ids]
    kinds = {layer.kind for layer in selected}

    statements = [
        ReasoningStatement(
            statement_id="atlas-observation-001",
            category="observation",
            text="The manifest combines governed layers with explicit source versions and lineage checksums.",
            supporting_layer_ids=manifest.ordered_layer_ids,
            confidence=1.0,
        )
    ]
    if {"biodiversity", "earth_science"}.issubset(kinds):
        statements.append(
            ReasoningStatement(
                statement_id="atlas-inference-001",
                category="inference",
                text="The selected layers support exploratory comparison between orchid occurrence patterns and environmental context.",
                supporting_layer_ids=[layer.layer_id for layer in selected if layer.kind in {"biodiversity", "earth_science"}],
                confidence=0.7,
            )
        )
    statements.extend(
        [
            ReasoningStatement(
                statement_id="atlas-uncertainty-001",
                category="uncertainty",
                text="Sampling effort and source coverage may influence the visible distribution pattern.",
                supporting_layer_ids=[layer.layer_id for layer in selected if layer.kind == "sampling_effort"],
            ),
            ReasoningStatement(
                statement_id="atlas-unavailable-001",
                category="unavailable",
                text="These layers alone do not establish causation, population abundance, or future habitat suitability.",
            ),
        ]
    )
    return AtlasReasoningResponse(
        response_id=f"reasoning:{manifest.map_id}",
        map_id=manifest.map_id,
        statements=statements,
    )


def assemble_brain_records(manifest: ThematicMapManifest) -> list[BrainRegistrationRecord]:
    created_at = datetime.now(timezone.utc)
    manifest_payload = manifest.model_dump(mode="json")
    checksum = _canonical_checksum(manifest_payload)
    return [
        BrainRegistrationRecord(
            object_id="architecture:atlas-planetary-intelligence",
            object_type="architecture",
            title="Atlas Planetary Intelligence Platform",
            aliases=["Atlas", "Earth Systems Atlas"],
            lifecycle_state="approved",
            related_object_ids=["decision:atlas-001", f"build:{manifest.map_id}"],
            source_uri="docs/architecture/ATLAS_PLANETARY_INTELLIGENCE_PROGRAM.md",
            content_checksum=checksum,
            created_at=created_at,
        ),
        BrainRegistrationRecord(
            object_id="decision:atlas-001",
            object_type="decision",
            title="Earth Systems and Thematic Cartography are core Atlas capabilities",
            aliases=["ADR-ATLAS-001"],
            lifecycle_state="approved",
            related_object_ids=["architecture:atlas-planetary-intelligence"],
            source_uri="docs/architecture/ADR-ATLAS-001-EARTH-SYSTEMS-AND-THEMATIC-CARTOGRAPHY.md",
            content_checksum=checksum,
            created_at=created_at,
        ),
        BrainRegistrationRecord(
            object_id=f"reproducibility:{manifest.map_id}",
            object_type="reproducibility",
            title=f"Reproducibility manifest for {manifest.title}",
            aliases=[manifest.map_id],
            lifecycle_state="implemented",
            related_object_ids=["architecture:atlas-planetary-intelligence"],
            source_uri=f"atlas://manifests/{manifest.map_id}",
            content_checksum=manifest.manifest_checksum,
            created_at=created_at,
        ),
    ]
