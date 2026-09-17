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

from .models import CommunityObservation, ModerationState

OWNER_KEY = "community-observations"
PROJECT_ID = "all"
KIND_OBSERVATION = "community_observation"

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
