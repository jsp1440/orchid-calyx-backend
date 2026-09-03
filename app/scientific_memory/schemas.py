from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SourceReference(StrictModel):
    document_id: str | None = Field(default=None, max_length=300)
    revision_id: str | None = Field(default=None, max_length=300)
    identifier: str | None = Field(default=None, max_length=500)
    locator: dict[str, Any] = Field(default_factory=dict)
    authorized_excerpt: str | None = Field(default=None, max_length=4_000)
    rights_basis: Literal["OPEN_ACCESS", "AUTHORIZED", "USER_PROVIDED", "METADATA_ONLY"]

    @field_validator("locator")
    @classmethod
    def bounded_locator(cls, value: dict[str, Any]):
        if len(json.dumps(value, separators=(",", ":"), default=str)) > 4_000:
            raise ValueError("source locator is too large")
        return value


class MemoryItemCreate(StrictModel):
    item_type: Literal[
        "EVIDENCE",
        "CLAIM",
        "RELATIONSHIP",
        "TRAIT",
        "METHOD",
        "MATERIAL",
        "PROTOCOL",
        "MEASUREMENT",
        "TAXON_MAPPING",
        "CONTRADICTION",
        "UNCERTAINTY",
        "ANALYSIS",
    ]
    authority: Literal[
        "SOURCE_EVIDENCE",
        "CANDIDATE_KNOWLEDGE",
        "CALYX_INFERENCE",
        "RESEARCH_CONTEXT",
    ]
    statement: str = Field(min_length=1, max_length=12_000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: SourceReference
    structured_payload: dict[str, Any] = Field(default_factory=dict)
    correction_of_item_id: str | None = None

    @field_validator("structured_payload")
    @classmethod
    def bounded_payload(cls, value: dict[str, Any]):
        if len(json.dumps(value, separators=(",", ":"), default=str)) > 20_000:
            raise ValueError("structured payload is too large")
        return value

    @model_validator(mode="after")
    def exact_source_for_evidence(self):
        if self.authority == "SOURCE_EVIDENCE":
            if not self.source.document_id or not self.source.revision_id:
                raise ValueError("source evidence requires document_id and revision_id")
            if not self.source.locator:
                raise ValueError("source evidence requires an exact locator")
            if self.source.rights_basis == "METADATA_ONLY":
                raise ValueError("metadata-only records cannot become source evidence")
            if not self.source.authorized_excerpt:
                raise ValueError("source evidence requires an authorized excerpt")
        return self


class CaptureCreate(StrictModel):
    origin: Literal["OASIS", "CALYX", "RESEARCH_STATION"]
    name: str = Field(min_length=1, max_length=160)
    query: str = Field(min_length=1, max_length=8_000)
    result_count_snapshot: int | None = Field(default=None, ge=0)
    conversation_id: str | None = Field(default=None, max_length=300)
    filters: dict[str, Any] = Field(default_factory=dict)
    items: list[MemoryItemCreate] = Field(min_length=1, max_length=100)

    @field_validator("filters")
    @classmethod
    def bounded_filters(cls, value: dict[str, Any]):
        if len(json.dumps(value, separators=(",", ":"), default=str)) > 8_000:
            raise ValueError("search filters are too large")
        return value


class DecisionCreate(StrictModel):
    action: Literal["ACCEPT_REVIEW", "REJECT", "INVALIDATE", "CORRECT"]
    reason: str = Field(min_length=1, max_length=4_000)
    replacement_item_id: str | None = None

    @model_validator(mode="after")
    def correction_requires_replacement(self):
        if self.action == "CORRECT" and not self.replacement_item_id:
            raise ValueError("CORRECT requires replacement_item_id")
        if self.action != "CORRECT" and self.replacement_item_id:
            raise ValueError("replacement_item_id is only valid for CORRECT")
        return self
