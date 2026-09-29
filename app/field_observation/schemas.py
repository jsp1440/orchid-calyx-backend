"""Journey 5 — field observation contract (``field-observations/v1``).

A field observation is an observer's report with provenance. It is never a
scientific determination: ``epistemic_certainty`` is what the observer
asserted, ``curation_state`` is where a human curator has taken the record,
and nothing here publishes to the Knowledge Graph.

Locality is fail-closed. The contract carries only a governed
``locality_visibility`` class (the same three classes the Field Journal client
offers) and rejects any payload key that names a coordinate, locality, or
site, at any nesting depth, through the shared guard in
``app.calyx_flywheel.locality``. Coordinate upload needs a DataPolicy consent
path that does not exist yet, so the backend refuses to store coordinates
rather than storing them "for later".
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.calyx_flywheel.locality import (
    SensitiveLocalityError,
    assert_no_sensitive_locality,
)

CONTRACT_VERSION = "field-observations/v1"
SCIENTIFIC_STATUS = "observer_report"
KNOWLEDGE_GRAPH_PUBLICATION = "blocked_pending_human_scientific_review"
HYPOTHESES_PATH_TEMPLATE = "/api/field-observations/{observation_id}/hypotheses"

LocalityVisibility = Literal["private", "research_restricted", "public"]


class EpistemicCertaintyLabel(str, Enum):
    """Observer-asserted certainty. Not a verified identification."""

    CONFIRMED = "CONFIRMED"
    PROBABLE = "PROBABLE"
    POSSIBLE = "POSSIBLE"
    UNCERTAIN = "UNCERTAIN"


class ObservationCurationState(str, Enum):
    """Human curation lifecycle: PENDING -> CURATED | FLAGGED | REJECTED."""

    PENDING = "PENDING"
    CURATED = "CURATED"
    FLAGGED = "FLAGGED"
    REJECTED = "REJECTED"


def _reject_protected_locality(values: Any) -> Any:
    try:
        assert_no_sensitive_locality(values)
    except SensitiveLocalityError as exc:
        raise ValueError(str(exc)) from exc
    return values


def _reject_email_like(value: str | None, *, field: str) -> str | None:
    if value is not None and "@" in value:
        raise ValueError(f"{field} must be an opaque subject token, never an email address")
    return value


class MediaDescriptor(BaseModel):
    """Metadata the Field Journal client keeps for an attachment. No bytes, no URL."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=180)
    size: int = Field(ge=0)
    type: str = Field(min_length=1, max_length=100)


class FieldObservationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_at: datetime
    note: str = Field(min_length=1, max_length=5000)
    taxon_hint: str | None = Field(
        default=None,
        max_length=240,
        description="The observer's proposed taxon. Not a determination.",
    )
    epistemic_certainty: EpistemicCertaintyLabel = EpistemicCertaintyLabel.POSSIBLE
    locality_visibility: LocalityVisibility = "private"
    media: list[MediaDescriptor] = Field(default_factory=list, max_length=20)
    client_draft_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=120,
        description="The Field Journal's local draft id; makes upload idempotent per observer.",
    )

    @model_validator(mode="before")
    @classmethod
    def _no_protected_locality(cls, values: Any) -> Any:
        return _reject_protected_locality(values)


class PhotoAttachRequest(BaseModel):
    """Provenance for a photo already held by the storage layer."""

    model_config = ConfigDict(extra="forbid")

    storage_key: str = Field(min_length=1, max_length=2000)
    content_hash: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 hex digest of the original bytes.",
    )
    photographer_subject: str | None = Field(default=None, min_length=1, max_length=120)
    captured_at: datetime | None = None
    license: str | None = Field(default=None, max_length=200)
    provenance: dict[str, Any] | None = None

    @field_validator("storage_key")
    @classmethod
    def _opaque_storage_key(cls, value: str) -> str:
        if "://" in value:
            raise ValueError("storage_key is an opaque reference, not a URL")
        return value

    @field_validator("photographer_subject")
    @classmethod
    def _photographer_not_email(cls, value: str | None) -> str | None:
        return _reject_email_like(value, field="photographer_subject")

    @model_validator(mode="before")
    @classmethod
    def _no_protected_locality(cls, values: Any) -> Any:
        return _reject_protected_locality(values)


class CurationDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: ObservationCurationState
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("state")
    @classmethod
    def _not_pending(cls, value: ObservationCurationState) -> ObservationCurationState:
        if value is ObservationCurationState.PENDING:
            raise ValueError("PENDING is the system's initial state, not a curation target")
        return value


class PhotoOut(BaseModel):
    id: str
    observation_id: str
    storage_key: str
    content_hash: str
    photographer_subject: str | None
    captured_at: datetime | None
    license: str | None
    created_at: datetime


class FieldObservationOut(BaseModel):
    contract_version: str = CONTRACT_VERSION
    id: str
    observer_subject: str
    observed_at: datetime
    note: str
    taxon_hint: str | None
    epistemic_certainty: EpistemicCertaintyLabel
    curation_state: ObservationCurationState
    curation_reason: str | None = None
    curated_by: str | None = None
    curated_at: datetime | None = None
    locality_visibility: LocalityVisibility
    media: list[MediaDescriptor]
    photo_count: int
    client_draft_id: str | None
    scientific_status: str = SCIENTIFIC_STATUS
    knowledge_graph_publication: str = KNOWLEDGE_GRAPH_PUBLICATION
    hypotheses_path: str
    created_at: datetime
    updated_at: datetime


class FieldObservationListOut(BaseModel):
    contract_version: str = CONTRACT_VERSION
    observer_subject: str
    items: list[FieldObservationOut]
    total: int
    offset: int
    limit: int
