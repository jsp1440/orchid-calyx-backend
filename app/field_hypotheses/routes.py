"""HTTP surface for the field hypothesis loop (journey 6).

Two routers:

- ``/api/field-observations/{observation_id}/hypotheses`` composes with the
  journey-5 Field Observation router prefix without colliding with any of its
  paths; the observation snapshot travels in the request so this module never
  reads another module's store.
- ``/api/field-hypotheses/...`` addresses individual hypotheses: read, record
  evidence, and (authenticated) human review.

Generation and evidence recording are open to the observer flow, behind the
same per-client public-write brake as community observations (both write to
the store); the review transition, which is the only path that changes a
hypothesis' lifecycle by human decision, requires an owner session or API key.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from app.rate_limit import public_write_rate_limit
from app.security import verify_owner_or_api_key

from .schemas import (
    EvidenceRecordIn,
    HypothesisOut,
    HypothesisSetOut,
    LibraryOut,
    ObservationSnapshot,
    ReviewDecisionIn,
)
from .service import (
    FieldHypothesisService,
    HypothesisNotFound,
    HypothesisSetNotFound,
    get_store,
)

observation_router = APIRouter(
    prefix="/api/field-observations",
    tags=["field-hypotheses"],
)
hypothesis_router = APIRouter(
    prefix="/api/field-hypotheses",
    tags=["field-hypotheses"],
)


def get_service() -> FieldHypothesisService:
    return FieldHypothesisService(get_store())


@observation_router.post(
    "/{observation_id}/hypotheses",
    response_model=HypothesisSetOut,
    status_code=200,
    dependencies=[Depends(public_write_rate_limit("field-hypotheses"))],
)
def generate_hypotheses(
    observation_id: str,
    snapshot: ObservationSnapshot,
    service: Annotated[FieldHypothesisService, Depends(get_service)],
) -> HypothesisSetOut:
    """Produce (or return the existing) competing hypothesis set for an observation.

    Idempotent: the same observation snapshot yields the same set. A changed
    snapshot yields a new set and becomes the latest for the observation.
    """
    return service.generate(observation_id, snapshot)


@observation_router.get(
    "/{observation_id}/hypotheses",
    response_model=HypothesisSetOut,
    status_code=200,
)
def latest_hypotheses(
    observation_id: str,
    service: Annotated[FieldHypothesisService, Depends(get_service)],
) -> HypothesisSetOut:
    try:
        return service.latest_set(observation_id)
    except HypothesisSetNotFound as exc:
        raise HTTPException(status_code=404, detail="No hypothesis set for observation") from exc


@hypothesis_router.get("/library", response_model=LibraryOut, status_code=200)
def hypothesis_library() -> LibraryOut:
    """The rule library itself, so consumers can see exactly what can be proposed."""
    return FieldHypothesisService.library_listing()


@hypothesis_router.get("/{hypothesis_id}", response_model=HypothesisOut, status_code=200)
def get_hypothesis(
    hypothesis_id: str,
    service: Annotated[FieldHypothesisService, Depends(get_service)],
) -> HypothesisOut:
    try:
        return service.get_hypothesis(hypothesis_id)
    except HypothesisNotFound as exc:
        raise HTTPException(status_code=404, detail="Hypothesis not found") from exc


@hypothesis_router.post(
    "/{hypothesis_id}/evidence",
    response_model=HypothesisOut,
    status_code=200,
    dependencies=[Depends(public_write_rate_limit("field-hypotheses"))],
)
def record_evidence(
    hypothesis_id: str,
    payload: EvidenceRecordIn,
    service: Annotated[FieldHypothesisService, Depends(get_service)],
) -> HypothesisOut:
    """Attach one supporting, contradicting or unknown evidence item to a hypothesis.

    Idempotent on content: re-submitting the same item does not duplicate it.
    """
    try:
        return service.record_evidence(hypothesis_id, payload)
    except HypothesisNotFound as exc:
        raise HTTPException(status_code=404, detail="Hypothesis not found") from exc


@hypothesis_router.post(
    "/{hypothesis_id}/review",
    response_model=HypothesisOut,
    status_code=200,
)
def review_hypothesis(
    hypothesis_id: str,
    decision: ReviewDecisionIn,
    actor: Annotated[dict[str, Any], Depends(verify_owner_or_api_key)],
    service: Annotated[FieldHypothesisService, Depends(get_service)],
) -> HypothesisOut:
    """Record a human review decision. Requires an owner session or API key."""
    try:
        return service.review(hypothesis_id, decision, actor)
    except HypothesisNotFound as exc:
        raise HTTPException(status_code=404, detail="Hypothesis not found") from exc
