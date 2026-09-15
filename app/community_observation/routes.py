"""
Community observation API routes — Journey 10:
Human Observation + Epistemic State/Provenance + Moderation Path.

Storage: in-memory dict stub (MVP — full DB integration is a follow-up).

Moderation lifecycle:
  SUBMITTED → SCREENED → QUARANTINED | APPROVED | REJECTED

# Integration hook: approved observations eligible for intake.propose_task()
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Query

from .models import (
    CommunityObservation,
    ModerationState,
    ObservationListResponse,
    ObservationModerationDecision,
    ObservationSubmitRequest,
    ObservationSubmitResponse,
)

router = APIRouter(
    prefix="/api/community",
    tags=["community-observation"],
)

# ---------------------------------------------------------------------------
# In-memory store (MVP stub — replace with DB session in follow-up)
# ---------------------------------------------------------------------------
_store: Dict[uuid.UUID, CommunityObservation] = {}

# Moderation states that may NOT be set as the initial state via the moderate
# endpoint — only valid transition targets.
_MODERATABLE_STATES = {
    ModerationState.SCREENED,
    ModerationState.QUARANTINED,
    ModerationState.APPROVED,
    ModerationState.REJECTED,
}

# SUBMITTED is set by the system; it is not a valid moderation target.
_INVALID_MODERATION_TARGETS = {ModerationState.SUBMITTED}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("/observations", response_model=ObservationSubmitResponse, status_code=200)
def submit_observation(
    payload: ObservationSubmitRequest,
    x_auth_subject: Optional[str] = Header(default="anonymous"),
) -> ObservationSubmitResponse:
    """
    Submit a new human field observation.

    The caller identity is taken from the X-Auth-Subject header (opaque token
    from the auth layer).  Email addresses must never appear in this header.

    The returned observation starts in SUBMITTED moderation state.
    """
    obs = CommunityObservation(
        submitter_auth_subject=x_auth_subject or "anonymous",
        taxon_name_verbatim=payload.taxon_name_verbatim,
        location_verbatim=payload.location_verbatim,
        observation_date=payload.observation_date,
        epistemic_label=payload.epistemic_label,
        notes=payload.notes,
        evidence_media_ids=payload.evidence_media_ids,
    )
    _store[obs.id] = obs
    return ObservationSubmitResponse(
        id=obs.id,
        moderation_state=obs.moderation_state,
        created_at=obs.created_at,
    )


@router.get("/observations", response_model=ObservationListResponse)
def list_observations(
    moderation_state: Optional[ModerationState] = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
) -> ObservationListResponse:
    """
    List observations, optionally filtered by moderation_state.
    Results are ordered by created_at descending (newest first).
    """
    items = list(_store.values())
    if moderation_state is not None:
        items = [o for o in items if o.moderation_state == moderation_state]
    items.sort(key=lambda o: o.created_at, reverse=True)
    total = len(items)
    page = items[offset : offset + limit]
    return ObservationListResponse(
        items=[
            ObservationSubmitResponse(
                id=o.id,
                moderation_state=o.moderation_state,
                created_at=o.created_at,
            )
            for o in page
        ],
        total=total,
    )


@router.get("/observations/{observation_id}", response_model=CommunityObservation)
def get_observation(observation_id: uuid.UUID) -> CommunityObservation:
    """Retrieve a single observation by UUID."""
    obs = _store.get(observation_id)
    if obs is None:
        raise HTTPException(status_code=404, detail="Observation not found")
    return obs


@router.patch(
    "/observations/{observation_id}/moderate",
    response_model=ObservationSubmitResponse,
)
def moderate_observation(
    observation_id: uuid.UUID,
    decision: ObservationModerationDecision,
) -> ObservationSubmitResponse:
    """
    Apply a moderation decision to an observation.

    Moderator-only endpoint.  The new_state must be one of:
      SCREENED, QUARANTINED, APPROVED, REJECTED.

    SUBMITTED is not a valid moderation target (it is set by the system).

    # Integration hook: approved observations eligible for intake.propose_task()
    When new_state == APPROVED, the observation is eligible to be promoted to
    the intake pipeline via intake.propose_task() (implementation pending DB
    integration follow-up).
    """
    if decision.new_state in _INVALID_MODERATION_TARGETS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"'{decision.new_state.value}' is not a valid moderation target. "
                f"Valid targets: {[s.value for s in _MODERATABLE_STATES]}"
            ),
        )
    obs = _store.get(observation_id)
    if obs is None:
        raise HTTPException(status_code=404, detail="Observation not found")

    obs.moderation_state = decision.new_state
    obs.moderated_at = datetime.utcnow()
    obs.moderation_reason = decision.reason

    # Integration hook: approved observations eligible for intake.propose_task()
    # When obs.moderation_state == ModerationState.APPROVED:
    #   intake.propose_task(source="community_observation", ref_id=str(obs.id))

    return ObservationSubmitResponse(
        id=obs.id,
        moderation_state=obs.moderation_state,
        created_at=obs.created_at,
    )
