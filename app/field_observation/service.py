"""Journey 5 — durable field observation records.

Reuses the Research Station record store (``oc_admin.research_station_records``
on a database, in-process memory otherwise) exactly as the Journey 6
hypothesis loop does, so no migration is needed and the same
:func:`persistence_mode` tells the truth about durability.

Layout inside the store (owner_key ``field-observations``):

* ``field_observation`` — project_id = observer subject, record_id = observation id
* ``field_observation_index`` — project_id ``index``, record_id = observation id,
  payload names the observer so a bare id can be resolved
* ``field_observation_photo`` — project_id = observation id, record_id = photo id
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from runtime.research_station_store import (
    MemoryProjectRecordStore,
    ProjectRecordStore,
    build_record_store,
)

from .schemas import (
    HYPOTHESES_PATH_TEMPLATE,
    CurationDecisionIn,
    FieldObservationCreate,
    FieldObservationListOut,
    FieldObservationOut,
    ObservationCurationState,
    PhotoAttachRequest,
    PhotoOut,
)

OWNER_KEY = "field-observations"
KIND_OBSERVATION = "field_observation"
KIND_INDEX = "field_observation_index"
KIND_PHOTO = "field_observation_photo"
INDEX_PROJECT = "index"


class ObservationNotFound(LookupError):
    pass


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def observation_id_for(observer_subject: str, client_draft_id: str | None) -> str:
    if client_draft_id:
        digest = hashlib.sha256(f"{observer_subject}\n{client_draft_id}".encode()).hexdigest()
        return f"fo-{digest[:24]}"
    return f"fo-{uuid.uuid4().hex[:24]}"


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


class FieldObservationService:
    def __init__(self, store: ProjectRecordStore) -> None:
        self._store = store

    # -- observations -----------------------------------------------------------------

    def create(
        self, observer_subject: str, payload: FieldObservationCreate
    ) -> tuple[FieldObservationOut, bool]:
        observation_id = observation_id_for(observer_subject, payload.client_draft_id)
        existing = self._store.get(
            owner_key=OWNER_KEY,
            project_id=observer_subject,
            kind=KIND_OBSERVATION,
            record_id=observation_id,
        )
        if existing is not None:
            return self._assemble(existing), False

        now = _iso(_now())
        record: dict[str, Any] = {
            "id": observation_id,
            "observer_subject": observer_subject,
            "observed_at": _iso(payload.observed_at),
            "note": payload.note,
            "taxon_hint": payload.taxon_hint,
            "epistemic_certainty": payload.epistemic_certainty.value,
            "curation_state": ObservationCurationState.PENDING.value,
            "curation_reason": None,
            "curated_by": None,
            "curated_at": None,
            "locality_visibility": payload.locality_visibility,
            "media": [item.model_dump() for item in payload.media],
            "client_draft_id": payload.client_draft_id,
            "created_at": now,
            "updated_at": now,
        }
        self._store.put(
            owner_key=OWNER_KEY,
            project_id=observer_subject,
            kind=KIND_OBSERVATION,
            record_id=observation_id,
            record=record,
        )
        self._store.put(
            owner_key=OWNER_KEY,
            project_id=INDEX_PROJECT,
            kind=KIND_INDEX,
            record_id=observation_id,
            record={"observation_id": observation_id, "observer_subject": observer_subject},
        )
        return self._assemble(record), True

    def get(self, observation_id: str) -> FieldObservationOut:
        return self._assemble(self._load(observation_id))

    def list_for(
        self,
        observer_subject: str,
        *,
        curation_state: ObservationCurationState | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> FieldObservationListOut:
        rows = self._store.list(owner_key=OWNER_KEY, project_id=observer_subject, kind=KIND_OBSERVATION)
        if curation_state is not None:
            rows = [row for row in rows if row.get("curation_state") == curation_state.value]
        rows.sort(key=lambda row: str(row.get("created_at", "")), reverse=True)
        page = rows[offset : offset + limit]
        return FieldObservationListOut(
            observer_subject=observer_subject,
            items=[self._assemble(row) for row in page],
            total=len(rows),
            offset=offset,
            limit=limit,
        )

    def curate(
        self, observation_id: str, decision: CurationDecisionIn, actor: dict[str, Any]
    ) -> FieldObservationOut:
        record = self._load(observation_id)
        now = _iso(_now())
        record["curation_state"] = decision.state.value
        record["curation_reason"] = decision.reason
        record["curated_by"] = str(actor.get("actor") or "unknown")
        record["curated_at"] = now
        record["updated_at"] = now
        self._store.put(
            owner_key=OWNER_KEY,
            project_id=record["observer_subject"],
            kind=KIND_OBSERVATION,
            record_id=observation_id,
            record=record,
        )
        return self._assemble(record)

    # -- photos -------------------------------------------------------------------------

    def attach_photo(self, observation_id: str, payload: PhotoAttachRequest) -> PhotoOut:
        record = self._load(observation_id)
        photo_seed = f"{observation_id}\n{payload.content_hash}".encode()
        photo_id = f"fp-{hashlib.sha256(photo_seed).hexdigest()[:24]}"
        existing = self._store.get(
            owner_key=OWNER_KEY, project_id=observation_id, kind=KIND_PHOTO, record_id=photo_id
        )
        if existing is not None:
            return PhotoOut(**existing)
        photo: dict[str, Any] = {
            "id": photo_id,
            "observation_id": observation_id,
            "storage_key": payload.storage_key,
            "content_hash": payload.content_hash,
            "photographer_subject": payload.photographer_subject,
            "captured_at": _iso(payload.captured_at) if payload.captured_at else None,
            "license": payload.license,
            "provenance": payload.provenance,
            "created_at": _iso(_now()),
        }
        self._store.put(
            owner_key=OWNER_KEY,
            project_id=observation_id,
            kind=KIND_PHOTO,
            record_id=photo_id,
            record=photo,
        )
        record["updated_at"] = photo["created_at"]
        self._store.put(
            owner_key=OWNER_KEY,
            project_id=record["observer_subject"],
            kind=KIND_OBSERVATION,
            record_id=observation_id,
            record=record,
        )
        return PhotoOut(**photo)

    def list_photos(self, observation_id: str) -> list[PhotoOut]:
        self._load(observation_id)
        rows = self._store.list(owner_key=OWNER_KEY, project_id=observation_id, kind=KIND_PHOTO)
        rows.sort(key=lambda row: str(row.get("created_at", "")))
        return [PhotoOut(**row) for row in rows]

    # -- internals ----------------------------------------------------------------------

    def _load(self, observation_id: str) -> dict[str, Any]:
        pointer = self._store.get(
            owner_key=OWNER_KEY, project_id=INDEX_PROJECT, kind=KIND_INDEX, record_id=observation_id
        )
        if pointer is None:
            raise ObservationNotFound(observation_id)
        record = self._store.get(
            owner_key=OWNER_KEY,
            project_id=str(pointer["observer_subject"]),
            kind=KIND_OBSERVATION,
            record_id=observation_id,
        )
        if record is None:
            raise ObservationNotFound(observation_id)
        return record

    def _photo_count(self, observation_id: str) -> int:
        return len(self._store.list(owner_key=OWNER_KEY, project_id=observation_id, kind=KIND_PHOTO))

    def _assemble(self, record: dict[str, Any]) -> FieldObservationOut:
        return FieldObservationOut(
            id=record["id"],
            observer_subject=record["observer_subject"],
            observed_at=record["observed_at"],
            note=record["note"],
            taxon_hint=record.get("taxon_hint"),
            epistemic_certainty=record["epistemic_certainty"],
            curation_state=record["curation_state"],
            curation_reason=record.get("curation_reason"),
            curated_by=record.get("curated_by"),
            curated_at=record.get("curated_at"),
            locality_visibility=record["locality_visibility"],
            media=record.get("media") or [],
            photo_count=self._photo_count(record["id"]),
            client_draft_id=record.get("client_draft_id"),
            hypotheses_path=HYPOTHESES_PATH_TEMPLATE.format(observation_id=record["id"]),
            created_at=record["created_at"],
            updated_at=record["updated_at"],
        )
