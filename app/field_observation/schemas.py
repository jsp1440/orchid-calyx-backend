"""
Pydantic request/response schemas for Journey 5: Field Observation Create/Manage.

Schema separation from SQLAlchemy models is intentional:
- Schemas are the API contract (versioned independently).
- SQLAlchemy models are the persistence contract.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from .models import EpistemicCertaintyLabel, ObservationCurationState

# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class FieldObservationCreate(BaseModel):
    """Fields supplied by the observer when creating a new field observation."""
    observer_id: str = Field(..., min_length=1, max_length=500,
                             description="Opaque auth subject — never an email address.")
    observed_at: datetime
    latitude: float | None = Field(
        default=None,
        description="Nullable — requires DataPolicy consent before storage.",
    )
    longitude: float | None = Field(
        default=None,
        description="Nullable — requires DataPolicy consent before storage.",
    )
    location_name: str | None = Field(default=None, max_length=1000)
    taxon_hint: str | None = Field(
        default=None, max_length=500,
        description="Observer's proposed taxon — not a scientific determination.",
    )
    observation_text: str | None = Field(default=None, max_length=10000)
    epistemic_certainty: EpistemicCertaintyLabel = EpistemicCertaintyLabel.POSSIBLE


class PhotoAttachRequest(BaseModel):
    """
    Attach a photo to an observation.

    storage_key is an opaque reference to the asset in the storage layer.
    No URL may be stored here — URLs are derived at serving time from storage_key.
    content_hash must be the SHA-256 hex digest of the original file bytes.
    """
    storage_key: str = Field(..., min_length=1, max_length=2000)
    content_hash: str = Field(..., min_length=64, max_length=64,
                              description="SHA-256 hex digest of the photo bytes.")
    photographer_id: str | None = Field(
        default=None,
        description="Opaque identity token — never an email address.",
    )
    captured_at: datetime | None = None
    license: str | None = Field(default=None, max_length=200)
    provenance: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------

class FieldObservationOut(BaseModel):
    """Observation summary returned to API callers."""
    id: str
    observer_id: str
    observed_at: datetime
    taxon_hint: str | None
    observation_text: str | None
    epistemic_certainty: EpistemicCertaintyLabel
    curation_state: ObservationCurationState
    ai_taxon_suggestion: str | None
    ai_suggestion_confidence: float | None
    created_at: datetime
    photo_count: int = 0

    model_config = {"use_enum_values": False}


class PhotoAttachResponse(BaseModel):
    """Confirmation returned after attaching a photo."""
    id: str
    observation_id: str
    storage_key: str
    created_at: datetime


class TaxonSuggestionResponse(BaseModel):
    """AI taxon suggestion result (NO_API_MODE stub or live engine result)."""
    observation_id: str
    ai_taxon_suggestion: str | None
    ai_suggestion_confidence: float | None
    suggestion_model: str
    requested_at: datetime
