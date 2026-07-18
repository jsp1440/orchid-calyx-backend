from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class OntologyStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    RETIRED = "RETIRED"


class TermStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"


class OntologyType(StrEnum):
    TAXONOMY = "TAXONOMY"
    GLOSSARY = "GLOSSARY"
    TRAIT = "TRAIT"
    HABITAT = "HABITAT"
    POLLINATOR = "POLLINATOR"
    MYCORRHIZA = "MYCORRHIZA"
    GEOGRAPHY = "GEOGRAPHY"
    ORGANIZATION = "ORGANIZATION"
    PERSON = "PERSON"
    LITERATURE = "LITERATURE"
    MEDIA = "MEDIA"
    CONSERVATION = "CONSERVATION"


class SynonymType(StrEnum):
    EXACT = "EXACT"
    ALTERNATE = "ALTERNATE"
    HISTORICAL = "HISTORICAL"
    ABBREVIATION = "ABBREVIATION"
    MISSPELLING = "MISSPELLING"
    SCIENTIFIC_NAME = "SCIENTIFIC_NAME"
    COMMON_NAME = "COMMON_NAME"


class ResolutionMethod(StrEnum):
    EXACT = "EXACT"
    NORMALIZED = "NORMALIZED"
    SYNONYM = "SYNONYM"
    FUZZY = "FUZZY"
    MANUAL = "MANUAL"
    UNRESOLVED = "UNRESOLVED"


class ResolutionStatus(StrEnum):
    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class EvidenceValidationStatus(StrEnum):
    PENDING = "PENDING"
    VALID = "VALID"
    INVALID = "INVALID"
    SUPERSEDED = "SUPERSEDED"


@dataclass(frozen=True)
class ResolutionSuggestion:
    ontology_term_id: int | None
    method: ResolutionMethod
    confidence: float
    normalized_input: str
    matched_label: str | None
    ontology_namespace: str | None
    ontology_version: str | None
    explanation: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReadinessResult:
    candidate_id: int
    evidence_complete: bool
    ontology_resolved: bool
    review_complete: bool
    provenance_complete: bool
    ready_for_publication: bool
    blockers: tuple[str, ...]
