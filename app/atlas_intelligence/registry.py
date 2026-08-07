from __future__ import annotations

from dataclasses import dataclass, field

from .models import AtlasLayer, MapArtifact, SpatialDataset, ThematicMapManifest


@dataclass
class AtlasRegistry:
    """Deterministic, fail-closed registry boundary for Atlas records.

    This first slice is intentionally storage-agnostic. A database adapter can
    implement the same behavior later without changing the public contract.
    """

    datasets: dict[str, SpatialDataset] = field(default_factory=dict)
    layers: dict[str, AtlasLayer] = field(default_factory=dict)
    manifests: dict[str, ThematicMapManifest] = field(default_factory=dict)
    artifacts: dict[str, MapArtifact] = field(default_factory=dict)

    def register_dataset(self, dataset: SpatialDataset) -> SpatialDataset:
        existing = self.datasets.get(dataset.dataset_id)
        if existing and existing != dataset:
            raise ValueError(f"dataset ID already registered with different content: {dataset.dataset_id}")
        self.datasets[dataset.dataset_id] = dataset
        return dataset

    def register_layer(self, layer: AtlasLayer) -> AtlasLayer:
        if layer.dataset_id not in self.datasets:
            raise ValueError(f"layer references unregistered dataset: {layer.dataset_id}")
        existing = self.layers.get(layer.layer_id)
        if existing and existing != layer:
            raise ValueError(f"layer ID already registered with different content: {layer.layer_id}")
        self.layers[layer.layer_id] = layer
        return layer

    def register_manifest(self, manifest: ThematicMapManifest) -> ThematicMapManifest:
        missing = [layer_id for layer_id in manifest.ordered_layer_ids if layer_id not in self.layers]
        if missing:
            raise ValueError(f"manifest references unregistered layers: {sorted(missing)}")
        existing = self.manifests.get(manifest.map_id)
        if existing and existing.manifest_checksum != manifest.manifest_checksum:
            raise ValueError(f"map ID already registered with different manifest: {manifest.map_id}")
        self.manifests[manifest.map_id] = manifest
        return manifest

    def register_artifact(self, artifact: MapArtifact) -> MapArtifact:
        manifest = self.manifests.get(artifact.map_id)
        if manifest is None:
            raise ValueError(f"artifact references unregistered map: {artifact.map_id}")
        if artifact.source_manifest_checksum != manifest.manifest_checksum:
            raise ValueError("artifact source checksum does not match registered manifest")
        existing = self.artifacts.get(artifact.artifact_id)
        if existing and existing != artifact:
            raise ValueError(f"artifact ID already registered with different content: {artifact.artifact_id}")
        self.artifacts[artifact.artifact_id] = artifact
        return artifact

    def get_dataset(self, dataset_id: str) -> SpatialDataset:
        try:
            return self.datasets[dataset_id]
        except KeyError as exc:
            raise KeyError(f"unknown Atlas dataset: {dataset_id}") from exc

    def get_layer(self, layer_id: str) -> AtlasLayer:
        try:
            return self.layers[layer_id]
        except KeyError as exc:
            raise KeyError(f"unknown Atlas layer: {layer_id}") from exc

    def get_manifest(self, map_id: str) -> ThematicMapManifest:
        try:
            return self.manifests[map_id]
        except KeyError as exc:
            raise KeyError(f"unknown Atlas map: {map_id}") from exc

    def list_layers(self, *, kind: str | None = None) -> list[AtlasLayer]:
        values = sorted(self.layers.values(), key=lambda item: item.layer_id)
        return [item for item in values if kind is None or item.kind == kind]

    def status(self) -> dict[str, int]:
        return {
            "datasets": len(self.datasets),
            "layers": len(self.layers),
            "manifests": len(self.manifests),
            "artifacts": len(self.artifacts),
        }
