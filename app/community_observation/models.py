"""
Community observation domain models for Journey 10:
Human Observation + Epistemic State/Provenance + Moderation Path.

DataPolicy: no raw lat/long stored without explicit DataPolicy approval.
location_verbatim is free text entered by the submitter only.
submitter_auth_subject is an opaque auth token — never an email address.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, model_validator


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
    created_at: datetime = Field(default_factory=lambda: datetime.now(tz=timezone.utc))
    moderated_at: datetime | None = None
    moderation_reason: str | None = None
    moderated_by: str | None = Field(
        default=None,
        description="Opaque actor label of the human moderator who applied the last decision.",
    )

    model_config = {"use_enum_values": False}


# ---------------------------------------------------------------------------
# Review-bound candidate produced when a moderator approves an observation
# ---------------------------------------------------------------------------

CANDIDATE_SCHEMA = "oc.community-observation-candidate.v1"

#: The only evidence state a human field report may carry. A person saying they
#: saw something is evidence with provenance; it is not a verified occurrence and
#: it is not a canonical fact. Nothing in this module may widen it.
EVIDENCE_STATE_HUMAN_REPORTED = "HUMAN_OBSERVATION_REPORTED"


class CandidateState(str, Enum):
    """Lifecycle of the review-bound candidate, not of the observation."""

    PENDING_REVIEW = "PENDING_REVIEW"
    WITHDRAWN = "WITHDRAWN"


class CommunityObservationCandidate(BaseModel):
    """An approved observation offered to scientific review — never promoted by itself.

    Approving an observation says a moderator found it worth a reviewer's time.
    It does not say the taxon is right, the record is verified, or the sighting
    is a fact. This object is what crosses that boundary, so it is deliberately
    narrower than the observation behind it:

    * ``taxon_name_verbatim`` is the submitter's wording and ``taxon_resolved``
      is ``False``. Resolution against the canonical taxonomy is a separate,
      reviewed act; this record must never be read as a resolved identity.
    * ``submitter_epistemic_label`` is the submitter's own confidence. It is
      carried so a reviewer can weigh it, and it is never read as a scientific
      determination.
    * ``evidence_state`` is pinned to ``HUMAN_OBSERVATION_REPORTED``.
    * The verbatim locality text and the submitter's opaque subject are **not
      copied here**. The candidate is the record that travels toward review, and
      orchid locality is protected by default: ``locality_withheld`` is ``True``
      and disclosure is a separate reviewed decision.
    * ``media_locality_review_required`` is ``True`` because submitted photographs
      can carry embedded coordinates, which no approval decision has inspected.

    The four authority flags are invariants, not defaults: constructing this
    object with any of them relaxed raises rather than producing a record that
    could be promoted automatically.
    """

    schema_name: str = Field(default=CANDIDATE_SCHEMA, alias="schema")
    observation_id: uuid.UUID
    taxon_name_verbatim: str
    taxon_resolved: bool = False
    observation_date: date
    submitter_epistemic_label: ObservationEpistemicLabel
    evidence_state: str = EVIDENCE_STATE_HUMAN_REPORTED
    locality_withheld: bool = True
    locality_disclosure_state: str = "WITHHELD_PENDING_REVIEW"
    evidence_media_ids: list[str] = Field(default_factory=list)
    media_locality_review_required: bool = True
    review_required: bool = True
    auto_promotion_blocked: bool = True
    graph_mutation: bool = False
    candidate_state: CandidateState = CandidateState.PENDING_REVIEW
    provenance_chain: list[str] = Field(default_factory=list)
    approved_by: str | None = None
    approved_at: datetime
    withdrawn_at: datetime | None = None
    withdrawn_reason: str | None = None

    model_config = {"use_enum_values": False, "populate_by_name": True}

    @model_validator(mode="after")
    def _enforce_invariants(self) -> CommunityObservationCandidate:
        if self.schema_name != CANDIDATE_SCHEMA:
            raise ValueError(f"CANDIDATE_SCHEMA_INVARIANT: schema must be {CANDIDATE_SCHEMA}")
        if self.evidence_state != EVIDENCE_STATE_HUMAN_REPORTED:
            raise ValueError(
                "CANDIDATE_EVIDENCE_STATE_INVARIANT: a human field report is "
                f"{EVIDENCE_STATE_HUMAN_REPORTED}, never a verified occurrence"
            )
        if self.taxon_resolved:
            raise ValueError(
                "CANDIDATE_TAXON_RESOLVED_INVARIANT: the submitter's wording is not "
                "a resolved taxon; resolution is a separate reviewed act"
            )
        if not self.review_required:
            raise ValueError("CANDIDATE_REVIEW_REQUIRED_INVARIANT: review_required must be True")
        if not self.auto_promotion_blocked:
            raise ValueError(
                "CANDIDATE_AUTO_PROMOTION_INVARIANT: auto_promotion_blocked must be True"
            )
        if self.graph_mutation:
            raise ValueError("CANDIDATE_GRAPH_MUTATION_INVARIANT: graph_mutation must be False")
        if not self.locality_withheld:
            raise ValueError(
                "CANDIDATE_LOCALITY_INVARIANT: locality_withheld must be True; "
                "disclosure is a separate reviewed decision"
            )
        if not self.media_locality_review_required:
            raise ValueError(
                "CANDIDATE_MEDIA_LOCALITY_INVARIANT: submitted media may carry embedded "
                "coordinates, so media_locality_review_required must be True"
            )
        return self


class CandidateListResponse(BaseModel):
    """Review queue of candidates awaiting scientific review."""

    items: list[CommunityObservationCandidate]
    total: int


class CandidateReconcileResponse(BaseModel):
    """How many candidates a reconciliation pass filed or withdrew."""

    filed: int
    withdrawn: int


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
