from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

CONCEPT_URI_PREFIX = "https://id.orchidcontinuum.org/concept/"


class ConceptStatus(StrEnum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"
    SUPERSEDED = "SUPERSEDED"


class ReviewState(StrEnum):
    PENDING = "PENDING"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


def concept_uri(concept_id: UUID) -> str:
    return f"{CONCEPT_URI_PREFIX}{concept_id}"


@dataclass(frozen=True)
class ConceptScheme:
    scheme_id: UUID
    scheme_key: str
    name: str
    authority: str
    steward: str
    review_state: ReviewState
    created_at: datetime
    revised_at: datetime


@dataclass(frozen=True)
class ConceptRelease:
    release_id: UUID
    scheme_id: UUID
    version: str
    status: str
    metadata: dict[str, object]
    created_at: datetime
    revised_at: datetime


@dataclass(frozen=True)
class Concept:
    concept_id: UUID
    concept_uri: str
    scheme_id: UUID
    release_id: UUID | None
    status: ConceptStatus
    review_state: ReviewState
    steward: str
    superseded_by_id: UUID | None
    created_at: datetime
    revised_at: datetime
