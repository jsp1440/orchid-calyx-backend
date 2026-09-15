"""
Community observation domain models for Journey 10:
Human Observation + Epistemic State/Provenance + Moderation Path.

DataPolicy: no raw lat/long stored without explicit DataPolicy approval.
location_verbatim is free text entered by the submitter only.
submitter_auth_subject is an opaque auth token — never an email address.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, Field


class ObservationEpistemicLabel(str, Enum):
    """
    Certainty label asserted by the submitter at time of observation.
    This is a submitter self-assessment, not a scientific determination.
    Downstream consumers must not treat this as verified evidence without
    independent source resolution.
    """
    CERTAIN = "CERTAIN"
    PROBABLE = "PROBABLE"
    POSSIBLE = "POSSIBLE"
    UNCERTAIN = "UNCERTAIN"


class ModerationState(str, Enum):
    """
    Moderation lifecycle state for a community observation.
    Flow: SUBMITTED → SCREENED → QUARANTINED | APPROVED | REJECTED
    Only APPROVED observations are eligible for intake pipeline promotion.
    """
    SUBMITTED = "SUBMITTED"
    SCREENED = "SCREENED"
    QUARANTINED = "QUARANTINED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# In-memory record (MVP — full DB integration is a follow-up)
# ---------------------------------------------------------------------------

class CommunityObservation(BaseModel):
    """
    A single human field observation submitted by a community member.

    Provenance contract:
    - submitter_auth_subject: opaque identity token from the auth layer; never
      store an email address or PII directly in this field.
    - location_verbatim: free-text string entered by the submitter. No lat/long
      is derived or stored here without explicit DataPolicy authorization.
    - evidence_media_ids: references to media assets stored separately; UUIDs only.
    """
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    submitter_auth_subject: str
    taxon_name_verbatim: str
    location_verbatim: str
    observation_date: date
    epistemic_label: ObservationEpistemicLabel
    moderation_state: ModerationState = ModerationState.SUBMITTED
    notes: str | None = None
    evidence_media_ids: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    moderated_at: datetime | None = None
    moderation_reason: str | None = None

    model_config = {"use_enum_values": False}


# ---------------------------------------------------------------------------
# Pydantic request / response models
# ---------------------------------------------------------------------------

class ObservationSubmitRequest(BaseModel):
    """Fields supplied by the submitter when creating a new observation."""
    taxon_name_verbatim: str = Field(..., min_length=1, max_length=500)
    location_verbatim: str = Field(..., min_length=1, max_length=1000)
    observation_date: date
    epistemic_label: ObservationEpistemicLabel
    notes: str | None = Field(default=None, max_length=5000)
    evidence_media_ids: list[str] = Field(default_factory=list)


class ObservationSubmitResponse(BaseModel):
    """Minimal confirmation returned to the submitter."""
    id: uuid.UUID
    moderation_state: ModerationState
    created_at: datetime


class ObservationModerationDecision(BaseModel):
    """
    Decision record applied by a moderator.
    new_state must be one of SCREENED, QUARANTINED, APPROVED, or REJECTED.
    """
    observation_id: uuid.UUID
    new_state: ModerationState
    reason: str | None = Field(default=None, max_length=2000)


class ObservationListResponse(BaseModel):
    """Paginated observation list."""
    items: list[ObservationSubmitResponse]
    total: int
