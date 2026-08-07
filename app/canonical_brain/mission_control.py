from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict, Field

from .registry import CanonicalBrainRegistry


class BrainMissionControlStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str = "read-only-candidate"
    persistence_enabled: bool = False
    publication_enabled: bool = False
    object_count: int = Field(ge=0)
    relationship_count: int = Field(ge=0)
    object_type_counts: dict[str, int]
    lifecycle_counts: dict[str, int]
    architecture_without_intent: list[str]
    snapshot_checksum: str


def build_mission_control_status(registry: CanonicalBrainRegistry) -> BrainMissionControlStatus:
    snapshot = registry.snapshot()
    object_type_counts = Counter(item.object_type for item in snapshot.objects)
    lifecycle_counts = Counter(item.lifecycle for item in snapshot.objects)
    architectures = [item for item in snapshot.objects if item.object_type == "architecture"]
    missing_intent = sorted(item.object_id for item in architectures if not registry.aligned_intents(item.object_id))
    return BrainMissionControlStatus(
        object_count=len(snapshot.objects),
        relationship_count=len(snapshot.relationships),
        object_type_counts=dict(sorted(object_type_counts.items())),
        lifecycle_counts=dict(sorted(lifecycle_counts.items())),
        architecture_without_intent=missing_intent,
        snapshot_checksum=snapshot.snapshot_checksum,
    )
