from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class TaxonomicRank(str, Enum):
    FAMILY = "FAMILY"
    GENUS = "GENUS"
    SPECIES = "SPECIES"
    HYBRID = "HYBRID"
    VARIETY = "VARIETY"


class CollectionEntryStatus(str, Enum):
    CANONICAL_RECORD = "CANONICAL_RECORD"


class CollectionEntryProvenance(BaseModel):
    source_table: str
    source_record_id: str
    identity_state: str


class CollectionEntry(BaseModel):
    taxon_id: str
    taxon_name: str
    common_names: list[str]
    taxonomic_rank: TaxonomicRank
    family: str | None = None
    genus: str | None = None
    status: CollectionEntryStatus
    description: str | None = None
    habitat_notes: str | None = None
    distribution_notes: str | None = None
    image_count: int = Field(default=0, ge=0)
    provenance: CollectionEntryProvenance


class SearchResult(BaseModel):
    query: str
    entries: list[CollectionEntry]
    total: int
    offset: int
    limit: int


class BrowseResult(BaseModel):
    family: str | None
    genus: str | None
    entries: list[CollectionEntry]
    total: int
    offset: int
    limit: int
