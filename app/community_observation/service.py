"""Durable storage for Journey 10 community observations.

Records live in the shared Research Station record store
(``oc_admin.research_station_records`` when ``DATABASE_URL`` is set, an
in-process map otherwise), so a moderation decision survives a restart and a
redeploy. No new table or migration is introduced; the store's
:func:`persistence_mode` states which mode is active rather than assuming it.

Layout in the record store:

* owner_key ``community-observations``, project_id ``all``,
  kind ``community_observation``, record_id = observation UUID.

The full record (verbatim locality text, opaque submitter subject) is only
ever read back through the owner-gated routes; this module does not decide
who may see what, the routes do.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from runtime.research_station_store import (
    MemoryProjectRecordStore,
    ProjectRecordStore,
    build_record_store,
)

from .models import (
    CANDIDATE_SCHEMA,
    CandidateState,
    CommunityObservation,
    CommunityObservationCandidate,
    ModerationState,
)

OWNER_KEY = "community-observations"
PROJECT_ID = "all"
KIND_OBSERVATION = "community_observation"
KIND_CANDIDATE = "community_observation_candidate"

_store: ProjectRecordStore | None = None


def configure_store(store: ProjectRecordStore | None) -> None:
    """Inject a store (tests pass a :class:`MemoryProjectRecordStore`); ``None`` resets."""
    global _store
    _store = store


def get_store() -> ProjectRecordStore:
    global _store
    if _store is None:
        _store = build_record_store()
    return _store


def memory_store() -> MemoryProjectRecordStore:
    return MemoryProjectRecordStore()


class ObservationNotFound(LookupError):
    pass


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class CommunityObservationRepository:
    """Reads and writes :class:`CommunityObservation` records through a record store."""

    def __init__(self, store: ProjectRecordStore) -> None:
        self._store = store

    def save(self, observation: CommunityObservation) -> CommunityObservation:
        self._store.put(
            owner_key=OWNER_KEY,
            project_id=PROJECT_ID,
            kind=KIND_OBSERVATION,
            record_id=str(observation.id),
            record=observation.model_dump(mode="json"),
        )
        return observation

    def get(self, observation_id: uuid.UUID) -> CommunityObservation:
        record = self._store.get(
            owner_key=OWNER_KEY,
            project_id=PROJECT_ID,
            kind=KIND_OBSERVATION,
            record_id=str(observation_id),
        )
        if record is None:
            raise ObservationNotFound(str(observation_id))
        return CommunityObservation.model_validate(record)

    def list(
        self, *, moderation_state: ModerationState | None = None
    ) -> list[CommunityObservation]:
        """Newest first; the store returns records in key order, so sort here."""
        rows: Iterable[dict[str, Any]] = self._store.list(
            owner_key=OWNER_KEY, project_id=PROJECT_ID, kind=KIND_OBSERVATION
        )
        items = [CommunityObservation.model_validate(row) for row in rows]
        if moderation_state is not None:
            items = [item for item in items if item.moderation_state == moderation_state]
        items.sort(key=lambda item: (item.created_at.isoformat(), str(item.id)), reverse=True)
        return items

    def moderate(
        self,
        observation_id: uuid.UUID,
        *,
        new_state: ModerationState,
        reason: str | None,
        moderated_by: str | None,
    ) -> CommunityObservation:
        observation = self.get(observation_id)
        updated = observation.model_copy(
            update={
                "moderation_state": new_state,
                "moderated_at": _utcnow(),
                "moderation_reason": reason,
                "moderated_by": moderated_by,
            }
        )
        return self.save(updated)


class CandidateRepository:
    """Reads and writes review-bound candidates through the same record store.

    A candidate is keyed by its observation's id, so approving the same
    observation twice refreshes one record rather than queueing the same sighting
    for review again.
    """

    def __init__(self, store: ProjectRecordStore) -> None:
        self._store = store

    def save(self, candidate: CommunityObservationCandidate) -> CommunityObservationCandidate:
        self._store.put(
            owner_key=OWNER_KEY,
            project_id=PROJECT_ID,
            kind=KIND_CANDIDATE,
            record_id=str(candidate.observation_id),
            record=candidate.model_dump(mode="json", by_alias=True),
        )
        return candidate

    def get(self, observation_id: uuid.UUID) -> CommunityObservationCandidate | None:
        record = self._store.get(
            owner_key=OWNER_KEY,
            project_id=PROJECT_ID,
            kind=KIND_CANDIDATE,
            record_id=str(observation_id),
        )
        if record is None:
            return None
        return CommunityObservationCandidate.model_validate(record)

    def list(
        self, *, candidate_state: CandidateState | None = None
    ) -> list[CommunityObservationCandidate]:
        """Newest approval first."""
        rows: Iterable[dict[str, Any]] = self._store.list(
            owner_key=OWNER_KEY, project_id=PROJECT_ID, kind=KIND_CANDIDATE
        )
        items = [CommunityObservationCandidate.model_validate(row) for row in rows]
        if candidate_state is not None:
            items = [item for item in items if item.candidate_state == candidate_state]
        items.sort(
            key=lambda item: (item.approved_at.isoformat(), str(item.observation_id)),
            reverse=True,
        )
        return items


def build_candidate(
    observation: CommunityObservation,
) -> CommunityObservationCandidate:
    """Derive the review-bound candidate for an approved observation.

    Raises if the observation is not APPROVED: approval by a human moderator is
    the only thing that may put a sighting in front of a reviewer, so an
    unapproved or retracted observation must not be able to produce one.

    Deliberately omitted from the result: ``location_verbatim`` and
    ``submitter_auth_subject``. The candidate is the record that travels toward
    scientific review, and neither the submitter's identity nor an orchid
    locality belongs in that queue by default.
    """
    if observation.moderation_state is not ModerationState.APPROVED:
        raise ValueError(
            "CANDIDATE_REQUIRES_APPROVAL: only an APPROVED observation may become a "
            f"review candidate; this one is {observation.moderation_state.value}"
        )
    return CommunityObservationCandidate(
        schema=CANDIDATE_SCHEMA,
        observation_id=observation.id,
        taxon_name_verbatim=observation.taxon_name_verbatim,
        observation_date=observation.observation_date,
        submitter_epistemic_label=observation.epistemic_label,
        evidence_media_ids=list(observation.evidence_media_ids),
        provenance_chain=[
            f"community_observation:{observation.id}",
            f"submitted_at:{observation.created_at.isoformat()}",
            (
                f"moderation_decision:{ModerationState.APPROVED.value}"
                f"@{(observation.moderated_at or _utcnow()).isoformat()}"
            ),
            f"moderated_by:{observation.moderated_by or 'unattributed'}",
        ],
        approved_by=observation.moderated_by,
        approved_at=observation.moderated_at or _utcnow(),
    )


def reconcile_candidate(
    observation: CommunityObservation,
    *,
    candidates: CandidateRepository,
) -> CommunityObservationCandidate | None:
    """Bring the candidate queue in line with an observation's current state.

    APPROVED offers the observation for review. Any other state means a human has
    since decided it should not be in front of a reviewer, so an existing
    candidate is **withdrawn rather than deleted** — a retraction is itself part
    of the record. Returns the candidate now on file, or ``None`` when there is
    nothing to record.
    """
    if observation.moderation_state is ModerationState.APPROVED:
        return candidates.save(build_candidate(observation))

    existing = candidates.get(observation.id)
    if existing is None or existing.candidate_state is CandidateState.WITHDRAWN:
        return existing
    withdrawn = existing.model_copy(
        update={
            "candidate_state": CandidateState.WITHDRAWN,
            "withdrawn_at": observation.moderated_at or _utcnow(),
            "withdrawn_reason": (
                f"moderation decision changed to {observation.moderation_state.value}"
            ),
        }
    )
    return candidates.save(withdrawn)
