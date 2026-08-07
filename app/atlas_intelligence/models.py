from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


PublicationState = Literal["candidate", "reviewed", "approved", "published", "rejected"]
LayerKind = Literal["biodiversity", "earth_science", "conservation", "sampling_effort"]


class SpatialExtent(StrictModel):
    west: float = Field(ge=-180, le=180)
    south: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)

    @model_validator(mode="after")
    def validate_bounds(self) -> SpatialExtent:
        if self.west >= self.east:
            raise ValueError("west must be less than east")
        if self.south >= self.north:
            raise ValueError("south must be less than north")
        return self


class TemporalExtent(StrictModel):
    start: datetime | None = None
    end: datetime | None = None

    @model_validator(mode="after")
    def validate_order(self) -> TemporalExtent:
        if self.start and self.end and self.start > self.end:
            raise ValueError("temporal start must not follow end")
        return self


class SourceLineage(StrictModel):
    source_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    license: str = Field(min_length=1)
    attribution: str = Field(min_length=1)
    acquired_at: datetime
    checksum: str = Field(min_length=16)


class SpatialDataset(StrictModel):
    dataset_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    version: str = Field(min_length=1)
    crs: str = Field(pattern=r"^(EPSG:\d+|OGC:CRS84)$")
    extent: SpatialExtent
    temporal_extent: TemporalExtent | None = None
    lineage: SourceLineage
    taxon_id: str | None = None
    publication_state: PublicationState = "candidate"

    @model_validator(mode="after")
    def validate_state(self) -> SpatialDataset:
        if self.publication_state == "published" and self.lineage.license.lower() in {"unknown", "none"}:
            raise ValueError("published datasets require an explicit usable license")
        return self


class AtlasLayer(StrictModel):
    layer_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    kind: LayerKind
    dataset_id: str = Field(min_length=1)
    geometry_type: Literal["point", "line", "polygon", "raster", "hexagon"]
    variable: str = Field(min_length=1)
    units: str | None = None
    classification: Literal["continuous", "categorical", "binary", "density"]
    temporal_required: bool = False
    publication_state: PublicationState = "candidate"


class ThematicMapRequest(StrictModel):
    map_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    layer_ids: list[str] = Field(min_length=1)
    projection: str = Field(pattern=r"^(EPSG:\d+|OGC:CRS84)$")
    audience: Literal["research", "conservation", "education", "public"] = "research"
    output_formats: list[Literal["json", "geojson", "svg", "png", "pdf", "html"]] = Field(
        default_factory=lambda: ["json"]
    )


class ThematicMapManifest(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    map_id: str
    title: str
    projection: str
    audience: str
    ordered_layer_ids: list[str]
    dataset_versions: dict[str, str]
    lineage_checksums: dict[str, str]
    output_formats: list[str]
    manifest_checksum: str = Field(min_length=16)
    publication_state: PublicationState = "candidate"


class MapArtifact(StrictModel):
    artifact_id: str = Field(min_length=1)
    map_id: str = Field(min_length=1)
    format: Literal["json", "geojson", "svg", "png", "pdf", "html"]
    storage_uri: str = Field(min_length=1)
    checksum: str = Field(min_length=16)
    source_manifest_checksum: str = Field(min_length=16)
    created_at: datetime
    publication_state: PublicationState = "candidate"


class ReasoningStatement(StrictModel):
    statement_id: str
    category: Literal["observation", "inference", "uncertainty", "unavailable"]
    text: str = Field(min_length=1)
    supporting_layer_ids: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def protect_inferences(self) -> ReasoningStatement:
        if self.category == "inference" and not self.supporting_layer_ids:
            raise ValueError("inferences require supporting layers")
        if self.category in {"observation", "inference"} and self.confidence is None:
            raise ValueError("observations and inferences require confidence")
        return self


class AtlasReasoningResponse(StrictModel):
    response_id: str
    map_id: str
    statements: list[ReasoningStatement] = Field(min_length=1)
    causal_claims_allowed: bool = False

    @model_validator(mode="after")
    def reject_unsupported_causality(self) -> AtlasReasoningResponse:
        causal_terms = ("causes", "caused by", "proves", "determines")
        if not self.causal_claims_allowed:
            for statement in self.statements:
                if any(term in statement.text.lower() for term in causal_terms):
                    raise ValueError("unsupported causal language is not allowed")
        return self


class BrainRegistrationRecord(StrictModel):
    object_id: str = Field(min_length=1)
    object_type: Literal["architecture", "decision", "build", "dependency", "validation", "reproducibility"]
    title: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    lifecycle_state: Literal["proposed", "approved", "implemented", "superseded", "deprecated", "archived"]
    related_object_ids: list[str] = Field(default_factory=list)
    source_uri: str = Field(min_length=1)
    content_checksum: str = Field(min_length=16)
    supersedes_id: str | None = None
    created_at: datetime
