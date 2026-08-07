from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import BrainObject, BrainRelationship
from .registry import CanonicalBrainRegistry


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BrainCaptureBundle(StrictModel):
    build_id: str = Field(min_length=3)
    objects: list[BrainObject] = Field(min_length=1)
    relationships: list[BrainRelationship] = Field(default_factory=list)
    submitted_at: datetime
    source_uri: str = Field(min_length=3)


class BrainCaptureResult(StrictModel):
    build_id: str
    registered_object_ids: list[str]
    registered_relationship_ids: list[str]
    snapshot_checksum: str


def capture_build_bundle(
    registry: CanonicalBrainRegistry,
    bundle: BrainCaptureBundle,
) -> BrainCaptureResult:
    object_ids = [record.object_id for record in bundle.objects]
    if len(object_ids) != len(set(object_ids)):
        raise ValueError("capture bundle contains duplicate Brain object IDs")

    relationship_ids = [relation.relationship_id for relation in bundle.relationships]
    if len(relationship_ids) != len(set(relationship_ids)):
        raise ValueError("capture bundle contains duplicate Brain relationship IDs")

    staged = CanonicalBrainRegistry()
    existing = registry.snapshot()
    for record in existing.objects:
        staged.register_object(record)
    for relation in existing.relationships:
        staged.register_relationship(relation)

    for record in bundle.objects:
        staged.register_object(record)
    for relation in bundle.relationships:
        staged.register_relationship(relation)

    for record in bundle.objects:
        registry.register_object(record)
    for relation in bundle.relationships:
        registry.register_relationship(relation)

    snapshot = registry.snapshot()
    return BrainCaptureResult(
        build_id=bundle.build_id,
        registered_object_ids=sorted(object_ids),
        registered_relationship_ids=sorted(relationship_ids),
        snapshot_checksum=snapshot.snapshot_checksum,
    )
