from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class ExtractedEntity:
    label: str
    entity_type: str
    start_offset: int | None = None
    end_offset: int | None = None
    confidence: float | None = None

class EntityExtractor(Protocol):
    def extract(self, text: str) -> list[ExtractedEntity]: ...

class NullEntityExtractor:
    def extract(self, text: str) -> list[ExtractedEntity]:
        return []
