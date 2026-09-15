"""
Field observation API routes — Journey 5:
Field Observation Create/Manage with Epistemic Labelling + Photo Provenance.

Storage: in-memory dict stub for MVP (DB migration is a follow-up task).

Epistemic contract:
- curation_state starts as PENDING; curator/reviewer promotes to CURATED.
- epistemic_certainty is observer-asserted, not a scientific determination.
- AI taxon suggestion is governed under NO_API_MODE — stub returns a
  placeholder; wires to multimodal_intelligence when NOT in NO_API_MODE.

# Wires to multimodal_intelligence when NO_API_MODE is not active
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query

from .models import ObservationCurationState
from .schemas import (
    FieldObservationCreate,
    FieldObservationOut,
    PhotoAttachRequest,
    PhotoAttachResponse,
    TaxonSuggestionResponse,
)

router = APIRouter(
    prefix="/api/field-observations",
    tags=["field-observation"],
)

# ---------------------------------------------------------------------------
# In-memory stub store for MVP (DB integration is follow-up)
# ---------------------------------------------------------------------------
_observations: dict[str, dict[str, Any]] = {}
_photos: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("", response_model=FieldObservationOut, status_code=200)
def create_observation(payload: FieldObservationCreate) -> FieldObservationOut:
    """
    Create a new field observation.

    The observation starts with curation_state=PENDING and
    epistemic_certainty as supplied (defaults to POSSIBLE).

    DataPolicy: latitude/longitude are stored only when explicitly provided
    by the caller and only after consent has been verified upstream.
    """
    obs_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc)
    record: dict[str, Any] = {
        "id": obs_id,
        "observer_id": payload.observer_id,
        "observed_at": payload.observed_at,
        "latitude": payload.latitude,
        "longitude": payload.longitude,
        "location_name": payload.location_name,
        "taxon_hint": payload.taxon_hint,
        "observation_text": payload.observation_text,
        "epistemic_certainty": payload.epistemic_certainty,
        "curation_state": ObservationCurationState.PENDING,
        "ai_taxon_suggestion": None,
        "ai_suggestion_confidence": None,
        "provenance_meta": None,
        "created_at": now,
        "updated_at": now,
    }
    _observations[obs_id] = record
    return _to_out(record)


@router.get("", response_model=dict[str, Any], status_code=200)
def list_observations(
    observer_id: Annotated[str | None, Query()] = None,
    curation_state: Annotated[ObservationCurationState | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict[str, Any]:
    """
    List field observations, optionally filtered by observer_id and/or
    curation_state.  Results are ordered by created_at descending.
    """
    items = list(_observations.values())
    if observer_id is not None:
        items = [o for o in items if o["observer_id"] == observer_id]
    if curation_state is not None:
        items = [o for o in items if o["curation_state"] == curation_state]
    items.sort(key=lambda o: o["created_at"], reverse=True)
    total = len(items)
    page = items[offset: offset + limit]
    return {
        "items": [_to_out(o).model_dump() for o in page],
        "total": total,
    }


@router.get("/{observation_id}", response_model=FieldObservationOut, status_code=200)
def get_observation(observation_id: str) -> FieldObservationOut:
    """Retrieve a single field observation by ID."""
    record = _observations.get(observation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Observation not found")
    return _to_out(record)


@router.post(
    "/{observation_id}/photos",
    response_model=PhotoAttachResponse,
    status_code=200,
)
def attach_photo(
    observation_id: str,
    payload: PhotoAttachRequest,
) -> PhotoAttachResponse:
    """
    Attach a photo to an existing observation.

    storage_key is an opaque reference to the asset; no URL is stored.
    content_hash must be the SHA-256 hex digest of the photo bytes.
    photographer_id is an opaque identity token (never an email address).
    """
    if observation_id not in _observations:
        raise HTTPException(status_code=404, detail="Observation not found")
    photo_id = str(uuid.uuid4())
    now = datetime.now(tz=timezone.utc)
    photo: dict[str, Any] = {
        "id": photo_id,
        "observation_id": observation_id,
        "storage_key": payload.storage_key,
        "content_hash": payload.content_hash,
        "photographer_id": payload.photographer_id,
        "captured_at": payload.captured_at,
        "license": payload.license,
        "provenance": payload.provenance,
        "created_at": now,
    }
    _photos[photo_id] = photo
    return PhotoAttachResponse(
        id=photo_id,
        observation_id=observation_id,
        storage_key=payload.storage_key,
        created_at=now,
    )


@router.post(
    "/{observation_id}/taxon-suggestion",
    response_model=TaxonSuggestionResponse,
    status_code=200,
)
def request_taxon_suggestion(observation_id: str) -> TaxonSuggestionResponse:
    """
    Trigger an AI taxon suggestion for an observation.

    Under NO_API_MODE this returns a governed stub.
    # Wires to multimodal_intelligence when NO_API_MODE is not active
    """
    if observation_id not in _observations:
        raise HTTPException(status_code=404, detail="Observation not found")

    # NO_API_MODE stub — never fabricates a real taxon determination.
    # Wires to multimodal_intelligence when NO_API_MODE is not active.
    suggestion = "[AI suggestion pending — NO_API_MODE]"
    confidence = None
    model_id = "NO_API_MODE_STUB"

    now = datetime.now(tz=timezone.utc)
    # Persist suggestion back to the observation record.
    _observations[observation_id]["ai_taxon_suggestion"] = suggestion
    _observations[observation_id]["ai_suggestion_confidence"] = confidence
    _observations[observation_id]["updated_at"] = now

    return TaxonSuggestionResponse(
        observation_id=observation_id,
        ai_taxon_suggestion=suggestion,
        ai_suggestion_confidence=confidence,
        suggestion_model=model_id,
        requested_at=now,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _photo_count(observation_id: str) -> int:
    return sum(1 for p in _photos.values() if p["observation_id"] == observation_id)


def _to_out(record: dict[str, Any]) -> FieldObservationOut:
    return FieldObservationOut(
        id=record["id"],
        observer_id=record["observer_id"],
        observed_at=record["observed_at"],
        taxon_hint=record.get("taxon_hint"),
        observation_text=record.get("observation_text"),
        epistemic_certainty=record["epistemic_certainty"],
        curation_state=record["curation_state"],
        ai_taxon_suggestion=record.get("ai_taxon_suggestion"),
        ai_suggestion_confidence=record.get("ai_suggestion_confidence"),
        created_at=record["created_at"],
        photo_count=_photo_count(record["id"]),
    )
