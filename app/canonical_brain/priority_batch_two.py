from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def checksum(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# BUILD-ATLAS-401 — persistent spatial layer registry
class SpatialLayerRecord(StrictModel):
    layer_id: str
    dataset_id: str
    category: Literal["biodiversity", "earth-science", "conservation", "sampling"]
    crs: str
    source_uri: str
    license_id: str
    content_checksum: str = Field(min_length=64, max_length=64)


class SpatialLayerRegistry:
    def __init__(self) -> None:
        self._layers: dict[str, SpatialLayerRecord] = {}

    def register(self, layer: SpatialLayerRecord) -> SpatialLayerRecord:
        if not layer.crs.startswith("EPSG:"):
            raise ValueError("layer CRS must use an EPSG identifier")
        existing = self._layers.get(layer.layer_id)
        if existing and existing != layer:
            raise ValueError(f"conflicting layer identity: {layer.layer_id}")
        self._layers[layer.layer_id] = layer
        return layer

    def snapshot(self) -> list[SpatialLayerRecord]:
        return sorted(self._layers.values(), key=lambda item: item.layer_id)


# BUILD-ATLAS-402 — Earth Systems adapter framework
class EarthDatasetCandidate(StrictModel):
    dataset_id: str
    provider: str
    variable: str
    version: str
    source_uri: str
    license_id: str
    checksum: str = Field(min_length=64, max_length=64)


class EarthSystemsAdapter:
    def __init__(self, provider: str, supported_variables: set[str]) -> None:
        self.provider = provider
        self.supported_variables = supported_variables

    def normalize(self, variable: str, version: str, source_uri: str, license_id: str) -> EarthDatasetCandidate:
        if variable not in self.supported_variables:
            raise ValueError(f"unsupported Earth-system variable: {variable}")
        body = {"provider": self.provider, "variable": variable, "version": version, "source_uri": source_uri}
        return EarthDatasetCandidate(
            dataset_id=f"earth:{self.provider.lower()}:{variable}:{version}",
            provider=self.provider,
            variable=variable,
            version=version,
            source_uri=source_uri,
            license_id=license_id,
            checksum=checksum(body),
        )


# BUILD-ATLAS-403 — deterministic thematic renderer
class RenderedMapArtifact(StrictModel):
    map_id: str
    layer_ids: list[str] = Field(min_length=1)
    format: Literal["svg", "png", "pdf", "json"]
    artifact_checksum: str = Field(min_length=64, max_length=64)
    publication_enabled: bool = False


def render_thematic_map(map_id: str, layers: list[SpatialLayerRecord], output_format: str) -> RenderedMapArtifact:
    required = {"biodiversity", "earth-science", "conservation", "sampling"}
    present = {layer.category for layer in layers}
    if not required.issubset(present):
        raise ValueError(f"missing required map categories: {sorted(required - present)}")
    ordered = sorted(layer.layer_id for layer in layers)
    return RenderedMapArtifact(
        map_id=map_id,
        layer_ids=ordered,
        format=output_format,
        artifact_checksum=checksum({"map_id": map_id, "layers": ordered, "format": output_format}),
    )


# BUILD-RS-500 — governed research evidence workspace
class EvidenceItem(StrictModel):
    evidence_id: str
    source_uri: str
    checksum: str = Field(min_length=64, max_length=64)
    claim_scope: str


class ResearchWorkspace(StrictModel):
    workspace_id: str
    hypothesis: str
    evidence: list[EvidenceItem]
    candidate_conclusions: list[str] = Field(default_factory=list)
    publication_enabled: bool = False

    def conclusion_ready(self) -> bool:
        return bool(self.evidence) and bool(self.candidate_conclusions)


# BUILD-CON-600 — specimen, QR, and label vertical slice
class SpecimenRecord(StrictModel):
    specimen_id: str
    accession_number: str
    taxon_name: str
    location_code: str
    provenance_uri: str

    @property
    def qr_payload(self) -> str:
        return f"orchid-continuum://specimens/{self.specimen_id}"

    @property
    def label_text(self) -> str:
        return f"{self.accession_number} | {self.taxon_name} | {self.location_code}"


# BUILD-MATRIX-700 — character ontology and comparison engine
class CharacterState(StrictModel):
    character_id: str
    label: str
    value: str | float | int | None
    evidence_uri: str | None = None


class MatrixTaxon(StrictModel):
    taxon_id: str
    states: list[CharacterState]


def compare_taxa(left: MatrixTaxon, right: MatrixTaxon) -> dict[str, object]:
    lmap = {item.character_id: item.value for item in left.states}
    rmap = {item.character_id: item.value for item in right.states}
    shared = sorted(set(lmap) & set(rmap))
    matches = [cid for cid in shared if lmap[cid] == rmap[cid] and lmap[cid] is not None]
    differences = [cid for cid in shared if lmap[cid] != rmap[cid] and None not in {lmap[cid], rmap[cid]}]
    missing = [cid for cid in shared if None in {lmap[cid], rmap[cid]}]
    return {"matches": matches, "differences": differences, "missing": missing}


# BUILD-VISION-800 — governed visual observations
class VisualObservation(StrictModel):
    observation_id: str
    asset_uri: str
    region: tuple[float, float, float, float]
    proposed_character_id: str
    proposed_value: str
    confidence: float = Field(ge=0, le=1)
    status: Literal["candidate", "reviewed", "rejected"] = "candidate"

    def is_publishable(self) -> bool:
        return self.status == "reviewed"


# BUILD-PUB-900 — evidence-backed publication package
class PublicationSection(StrictModel):
    heading: str
    text: str
    evidence_ids: list[str] = Field(min_length=1)


class PublicationPackage(StrictModel):
    package_id: str
    title: str
    sections: list[PublicationSection] = Field(min_length=1)
    review_status: Literal["candidate", "approved", "rejected"] = "candidate"
    publication_enabled: bool = False


# BUILD-INT-950 — cross-system event envelope
class IntegrationEvent(StrictModel):
    event_id: str
    event_type: str
    producer: str
    subject_id: str
    payload_checksum: str = Field(min_length=64, max_length=64)
    candidate_only: bool = True


def make_event(event_type: str, producer: str, subject_id: str, payload: object) -> IntegrationEvent:
    digest = checksum(payload)
    event_id = hashlib.sha256(f"{event_type}:{producer}:{subject_id}:{digest}".encode()).hexdigest()
    return IntegrationEvent(
        event_id=event_id,
        event_type=event_type,
        producer=producer,
        subject_id=subject_id,
        payload_checksum=digest,
    )


# BUILD-MC-201 — cross-system readiness projection
class ReadinessProjection(StrictModel):
    subsystem_status: dict[str, str]
    blocked_subsystems: list[str]
    ready_count: int


def build_readiness_projection(statuses: dict[str, str], dependencies: dict[str, list[str]]) -> ReadinessProjection:
    blocked: list[str] = []
    for subsystem, deps in sorted(dependencies.items()):
        if any(statuses.get(dep) != "ready" for dep in deps):
            blocked.append(subsystem)
    ready_count = sum(value == "ready" for value in statuses.values())
    return ReadinessProjection(subsystem_status=dict(sorted(statuses.items())), blocked_subsystems=blocked, ready_count=ready_count)
