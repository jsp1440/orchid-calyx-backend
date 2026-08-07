from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


ObjectType = Literal[
    "architecture", "decision", "intent", "build", "dataset", "api",
    "engineer", "dependency", "validation", "reproducibility", "risk",
]
Lifecycle = Literal["proposed", "approved", "implemented", "superseded", "deprecated", "archived"]
RelationshipType = Literal[
    "contains", "depends_on", "supports", "implements", "documents",
    "validates", "owned_by", "supersedes", "aligned_to", "related_to",
]


class BrainObject(StrictModel):
    object_id: str = Field(min_length=3)
    object_type: ObjectType
    title: str = Field(min_length=3)
    summary: str = Field(min_length=3)
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    lifecycle: Lifecycle
    source_uri: str = Field(min_length=3)
    version: int = Field(default=1, ge=1)
    content_checksum: str = Field(min_length=16)
    created_at: datetime
    supersedes_id: str | None = None

    @model_validator(mode="after")
    def validate_supersession(self) -> BrainObject:
        if self.lifecycle == "superseded" and not self.supersedes_id:
            raise ValueError("superseded objects require supersedes_id")
        normalized = [value.strip().casefold() for value in self.aliases]
        if len(normalized) != len(set(normalized)):
            raise ValueError("duplicate aliases are not allowed")
        return self


class BrainRelationship(StrictModel):
    relationship_id: str = Field(min_length=3)
    subject_id: str = Field(min_length=3)
    relationship_type: RelationshipType
    object_id: str = Field(min_length=3)
    rationale: str = Field(min_length=3)
    source_uri: str = Field(min_length=3)


class SearchHit(StrictModel):
    object_id: str
    title: str
    object_type: ObjectType
    lifecycle: Lifecycle
    score: int = Field(ge=0)
    matched_fields: list[str] = Field(default_factory=list)


class BrainSnapshot(StrictModel):
    objects: list[BrainObject]
    relationships: list[BrainRelationship]
    snapshot_checksum: str = Field(min_length=16)
