"""Canonical harvest domain models shared by every source plugin."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Mapping


@dataclass(slots=True, frozen=True)
class HarvestOccurrence:
    source: str
    source_record_id: str
    scientific_name: str
    accepted_name: str | None = None
    taxon_key: str | None = None
    occurrence_id: str | None = None
    basis_of_record: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    country_code: str | None = None
    locality: str | None = None
    event_date: datetime | None = None
    recorded_by: str | None = None
    license: str | None = None
    references: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class HarvestImage:
    source: str
    source_record_id: str
    url: str
    identifier: str | None = None
    thumbnail_url: str | None = None
    title: str | None = None
    description: str | None = None
    creator: str | None = None
    publisher: str | None = None
    license: str | None = None
    mime_type: str | None = None
    references: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class HarvestTrait:
    source: str
    source_record_id: str
    scientific_name: str
    predicate: str
    value: str
    unit: str | None = None
    evidence_url: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True, frozen=True)
class HarvestBatch:
    source: str
    raw_records: tuple[Mapping[str, Any], ...]
    normalized_records: tuple[Mapping[str, Any], ...]
    occurrences: tuple[HarvestOccurrence, ...] = ()
    images: tuple[HarvestImage, ...] = ()
    traits: tuple[HarvestTrait, ...] = ()
    checkpoint: Mapping[str, Any] = field(default_factory=dict)
