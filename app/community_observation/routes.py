"""
Community observation API routes — Journey 10:
Human Observation + Epistemic State/Provenance + Moderation Path.

Storage: the shared durable record store (see ``service.py``), so submissions
and moderation decisions survive restarts and redeploys when ``DATABASE_URL``
is configured, and the in-process fallback is stated, never assumed.

Moderation lifecycle:
  SUBMITTED → SCREENED → QUARANTINED | APPROVED | REJECTED

# Integration hook: approved observations eligible for intake.propose_task()
"""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.rate_limit import public_write_rate_limit
from app.security import verify_owner_or_api_key

from .models import (
    CommunityObservation,
    ModerationState,
    ObservationListResponse,
    ObservationModerationDecision,
    ObservationSubmitRequest,
    ObservationSubmitResponse,
)
from .service import CommunityObservationRepository, ObservationNotFound, get_store

router = APIRouter(
    prefix="/api/community",
    tags=["community-observation"],
)

def get_repository() -> CommunityObservationRepository:
    return CommunityObservationRepository(get_store())


Repository = Annotated[CommunityObservationRepository, Depends(get_repository)]

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

@router.post(
    "/observations",
    response_model=ObservationSubmitResponse,
    status_code=200,
    dependencies=[Depends(public_write_rate_limit("community"))],
)
def submit_observation(
    payload: ObservationSubmitRequest,
    repository: Repository,
    x_auth_subject: str | None = Header(default="anonymous"),
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
    repository.save(obs)
    return ObservationSubmitResponse(
        id=obs.id,
        moderation_state=obs.moderation_state,
        created_at=obs.created_at,
    )


@router.get("/observations", response_model=ObservationListResponse)
def list_observations(
    repository: Repository,
    moderation_state: Annotated[ModerationState | None, Query()] = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ObservationListResponse:
    """
    List observations, optionally filtered by moderation_state.
    Results are ordered by created_at descending (newest first).
    """
    items = repository.list(moderation_state=moderation_state)
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
def get_observation(
    observation_id: uuid.UUID,
    repository: Repository,
    _reviewer: Annotated[dict[str, object], Depends(verify_owner_or_api_key)],
) -> CommunityObservation:
    """Retrieve the full record of a single observation by UUID.

    The full record carries the submitter's verbatim locality text and opaque
    identity, so it is a moderation view: only the owner session or the
    backend API key may read it.  Anonymous callers see observations only
    through the list endpoint, which returns id, state, and timestamp.
    """
    try:
        return repository.get(observation_id)
    except ObservationNotFound as exc:
        raise HTTPException(status_code=404, detail="Observation not found") from exc


@router.patch(
    "/observations/{observation_id}/moderate",
    response_model=ObservationSubmitResponse,
)
def moderate_observation(
    observation_id: uuid.UUID,
    decision: ObservationModerationDecision,
    repository: Repository,
    moderator: Annotated[dict[str, object], Depends(verify_owner_or_api_key)],
) -> ObservationSubmitResponse:
    """
    Apply a moderation decision to an observation.

    Moderator-only endpoint, guarded by the repository's owner-session /
    backend API-key dependency so the human-review boundary cannot be crossed
    by an anonymous caller.  The new_state must be one of:
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
    actor = moderator.get("actor")
    try:
        obs = repository.moderate(
            observation_id,
            new_state=decision.new_state,
            reason=decision.reason,
            moderated_by=str(actor) if actor is not None else None,
        )
    except ObservationNotFound as exc:
        raise HTTPException(status_code=404, detail="Observation not found") from exc

    # Integration hook: approved observations eligible for intake.propose_task()
    # When obs.moderation_state == ModerationState.APPROVED:
    #   intake.propose_task(source="community_observation", ref_id=str(obs.id))

    return ObservationSubmitResponse(
        id=obs.id,
        moderation_state=obs.moderation_state,
        created_at=obs.created_at,
    )
