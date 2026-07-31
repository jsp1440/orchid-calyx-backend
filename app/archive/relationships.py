from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ExtractedRelationship:
    subject: str
    predicate: str
    object: str
    confidence: float | None = None
    evidence_text: str | None = None


class RelationshipExtractor(Protocol):
    def extract(
        self, text: str, entities: list[object]
    ) -> list[ExtractedRelationship]: ...


class NullRelationshipExtractor:
    def extract(
        self, text: str, entities: list[object]
    ) -> list[ExtractedRelationship]:
        return []
