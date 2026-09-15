"""
Field observation SQLAlchemy models — Journey 5:
Field Observation Create/Manage with Epistemic Labelling + Photo Provenance.

DataPolicy:
- latitude/longitude are nullable; coordinates must NOT be stored without
  explicit DataPolicy consent from the observer.
- observer_id is an opaque auth subject (never an email address).
- photo photographer_id is an opaque identity token.
- storage_key is an opaque reference — no URL stored inline.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    JSON,
    String,
    Text,
)
from sqlalchemy import Enum as SAEnum

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class EpistemicCertaintyLabel(str, Enum):
    """
    Observer-asserted certainty label at the time of observation.

    CONFIRMED  — observer is certain of the identification
    PROBABLE   — observer is fairly confident but not certain
    POSSIBLE   — observer thinks this could be the correct ID
    UNCERTAIN  — observer has low confidence in any identification

    Downstream consumers must not treat CONFIRMED as scientifically
    verified evidence without independent source resolution and peer review.
    """
    CONFIRMED = "CONFIRMED"
    PROBABLE = "PROBABLE"
    POSSIBLE = "POSSIBLE"
    UNCERTAIN = "UNCERTAIN"


class ObservationCurationState(str, Enum):
    """
    Curation/moderation lifecycle state for a field observation.

    Flow: PENDING → CURATED | FLAGGED | REJECTED
    Only CURATED observations are eligible for scientific pipeline promotion.
    """
    PENDING = "PENDING"
    CURATED = "CURATED"
    FLAGGED = "FLAGGED"
    REJECTED = "REJECTED"


class FieldObservation(Base):
    """
    A single field observation submitted by an observer.

    Provenance contract:
    - observer_id: opaque auth subject from the auth layer; never an email.
    - latitude/longitude: nullable — must not be stored without DataPolicy
      consent. location_name is a free-text human descriptor only.
    - taxon_hint: what the observer guessed; not a verified determination.
    - ai_taxon_suggestion: governed stub under NO_API_MODE; wires to
      multimodal_intelligence when NOT in NO_API_MODE.
    """
    __tablename__ = "field_observations"

    id = Column(String, primary_key=True, default=_uuid)
    observer_id = Column(String, nullable=False)
    observed_at = Column(DateTime, nullable=False)
    # Nullable — coordinates require DataPolicy consent before storage.
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    location_name = Column(String, nullable=True)
    taxon_hint = Column(String, nullable=True)
    observation_text = Column(Text, nullable=True)
    epistemic_certainty = Column(
        SAEnum(EpistemicCertaintyLabel, name="epistemic_certainty_label"),
        nullable=False,
        default=EpistemicCertaintyLabel.POSSIBLE,
    )
    curation_state = Column(
        SAEnum(ObservationCurationState, name="observation_curation_state"),
        nullable=False,
        default=ObservationCurationState.PENDING,
    )
    ai_taxon_suggestion = Column(String, nullable=True)
    ai_suggestion_confidence = Column(Float, nullable=True)
    provenance_meta = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FieldObservationPhoto(Base):
    """
    Photographic evidence attached to a field observation.

    Provenance contract:
    - storage_key: opaque reference to the stored asset — no URL stored here.
    - content_hash: SHA-256 of the photo bytes at capture/upload time;
      used for de-duplication and integrity verification.
    - photographer_id: opaque identity token (never an email address).
    - license: SPDX identifier or equivalent; required for publication.
    """
    __tablename__ = "field_observation_photos"

    id = Column(String, primary_key=True, default=_uuid)
    observation_id = Column(
        String,
        ForeignKey("field_observations.id", ondelete="CASCADE"),
        nullable=False,
    )
    storage_key = Column(String, nullable=False)
    content_hash = Column(String, nullable=False)  # SHA-256
    photographer_id = Column(String, nullable=True)
    captured_at = Column(DateTime, nullable=True)
    license = Column(String, nullable=True)
    provenance = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
