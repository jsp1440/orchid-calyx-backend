import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class LabelType(StrEnum):
    PREFERRED = "PREFERRED"
    ALTERNATE = "ALTERNATE"
    HIDDEN = "HIDDEN"
    HISTORICAL = "HISTORICAL"
    ABBREVIATION = "ABBREVIATION"
    SCIENTIFIC_NAME = "SCIENTIFIC_NAME"
    COMMON_NAME = "COMMON_NAME"
    MISSPELLING = "MISSPELLING"


class DefinitionType(StrEnum):
    NORMATIVE_SCIENTIFIC = "NORMATIVE_SCIENTIFIC"
    GLOSSARY = "GLOSSARY"
    GROWER = "GROWER"
    LEARNER = "LEARNER"
    PLAIN_LANGUAGE = "PLAIN_LANGUAGE"
    HISTORICAL = "HISTORICAL"


@dataclass(frozen=True)
class ConceptLabel:
    label_id: UUID
    concept_id: UUID
    label_type: LabelType
    label: str
    normalized_label: str
    language: str
    script: str | None
    editorial_context: str
    provenance: dict[str, object]
    review_state: str
    created_at: datetime
    revised_at: datetime


@dataclass(frozen=True)
class ConceptDefinition:
    definition_id: UUID
    concept_id: UUID
    definition_type: DefinitionType
    text: str
    language: str
    script: str | None
    provenance: dict[str, object]
    review_state: str
    created_at: datetime
    revised_at: datetime


def normalize_lexical_value(value: str) -> str:
    """Deterministic search normalization without changing stored display text."""
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    normalized = re.sub(r"[\s_]+", " ", normalized)
    normalized = re.sub(r"\s*[-–—]\s*", "-", normalized)
    normalized = re.sub(r"[^\w\s×.-]", "", normalized)
    return re.sub(r"\s+", " ", normalized).strip()
