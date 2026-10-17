"""Research Station junction subscriber adapter (oc-junction-profile-v1).

Research Station is the Continuum's private, reproducible research workspace
(``runtime/research_station.py`` / ``runtime/research_station_store.py``). This
adapter is its junction inlet: it applies delivered signals into the existing
project record store as ``evidence`` records — one of the store's declared
DURABLE_KINDS — keyed by the signal's ``dedupe_key`` so application is
idempotent by construction (a replayed signal maps to the same record id and
is never applied twice).

The applied record preserves, unchanged, everything the contract requires a
consumer to keep: taxon identity (including the explicit ``unresolved``
marker), provenance by reference, uncertainty (``confidence: null`` stays
null, never 0), conflicting evidence as a separate record, and the causation
chain (``correlation_id`` / ``parent_event_id``).

The subscriber mutates only its own workspace records. It gains no
publication, Knowledge Graph, or taxonomy authority from delivery.
"""

from __future__ import annotations

from typing import Any

from runtime.research_station_store import MemoryProjectRecordStore, ProjectRecordStore

MODULE_ID = "research-station"
INBOX_PROJECT_ID = "junction-inbox"
RECORD_KIND = "evidence"  # a declared DURABLE_KIND of the research station store


class ResearchStationSubscriber:
    """Apply junction signals into the Research Station record store."""

    def __init__(
        self,
        record_store: ProjectRecordStore | None = None,
        *,
        owner_key: str = "junction",
        project_id: str = INBOX_PROJECT_ID,
    ) -> None:
        # The injected store is authoritative in production (Postgres-backed
        # ProjectRecordStore); the memory store mirrors it for local runs.
        self._records: ProjectRecordStore = (
            record_store if record_store is not None else MemoryProjectRecordStore()
        )
        self._owner_key = owner_key
        self._project_id = project_id

    def __call__(self, event: dict[str, Any]) -> None:
        """Apply one delivered signal. Idempotent: keyed by dedupe_key."""

        junction = (event.get("extensions") or {}).get("junction") or {}
        record_id = junction.get("dedupe_key") or event["event_id"]
        existing = self._records.get(
            owner_key=self._owner_key,
            project_id=self._project_id,
            kind=RECORD_KIND,
            record_id=record_id,
        )
        if existing is not None:
            return  # replay-safe: never applied twice

        record: dict[str, Any] = {
            "schema": "oc-junction-inbox-v1",
            "event_id": event["event_id"],
            "event_type": event["event_type"],
            "correlation_id": event["correlation_id"],
            "parent_event_id": event.get("parent_event_id"),
            "sequence": event.get("sequence"),
            "occurred_at": event.get("occurred_at"),
            "source_module": (event.get("pipeline") or {}).get("component"),
            # Scientific context preserved unchanged:
            "taxon": event.get("taxon"),
            "source": event.get("source"),
            "evidence": event.get("evidence"),
            "conflict": event.get("conflict"),
            "safe_status": event.get("safe_status"),
            "payload": event.get("payload"),
            "junction": junction,
        }
        self._records.put(
            owner_key=self._owner_key,
            project_id=self._project_id,
            kind=RECORD_KIND,
            record_id=record_id,
            record=record,
        )

    def inbox(self) -> list[dict[str, Any]]:
        """Read-only view of applied junction evidence records."""

        return self._records.list(
            owner_key=self._owner_key, project_id=self._project_id, kind=RECORD_KIND
        )
