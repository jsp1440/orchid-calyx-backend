"""Smallest durable-shaped append-only observation store.

Mirrors the canonical in-memory repository pattern
(``app.review_tasks.repository.MemoryReviewTaskRepository``). ``event_id`` is
the idempotency key: re-appending an event with an existing id is a no-op that
returns the already-stored event, so replays never duplicate.

A draft (un-applied) Postgres migration in
``migrations/SCI-OBS-001-observation-store.sql`` specifies the same shape for a
durable backend; the in-memory store is the reference implementation used by
the vertical proof and tests. No production migration is applied by this code.
"""

from __future__ import annotations

from copy import deepcopy
from threading import RLock
from typing import Any, Iterable

from .redaction import RedactionReport, redact_event_dict


class ObservationStore:
    """Append-only, idempotent, queryable store for serialized events."""

    def __init__(self) -> None:
        self._events: dict[str, dict[str, Any]] = {}
        self._order: list[str] = []
        self._lock = RLock()

    def append(self, event: dict[str, Any]) -> tuple[dict[str, Any], bool, RedactionReport]:
        """Append a serialized event.

        Returns ``(stored_event, created, redaction_report)``. ``created`` is
        ``False`` when an event with the same ``event_id`` already existed
        (idempotent replay). The stored event is always the redacted copy.
        """

        event_id = event.get("event_id")
        if not event_id:
            raise ValueError("event requires an event_id")
        clean, report = redact_event_dict(event)
        with self._lock:
            existing = self._events.get(event_id)
            if existing is not None:
                # Idempotent replay: never overwrite, never duplicate.
                return deepcopy(existing), False, report
            stored = deepcopy(clean)
            self._events[event_id] = stored
            self._order.append(event_id)
            return deepcopy(stored), True, report

    def get(self, event_id: str) -> dict[str, Any] | None:
        with self._lock:
            found = self._events.get(event_id)
            return deepcopy(found) if found is not None else None

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [deepcopy(self._events[eid]) for eid in self._order]

    def by_correlation(self, correlation_id: str) -> list[dict[str, Any]]:
        """Reconstruct a trace: all events sharing a correlation id, ordered.

        Ordering: ``sequence``, then ``recorded_at``, then ``event_id`` — the
        canonical tie-break defined in the blueprint.
        """

        events = [e for e in self.all() if e.get("correlation_id") == correlation_id]
        events.sort(
            key=lambda e: (
                e.get("sequence") or 0,
                e.get("recorded_at") or "",
                e.get("event_id") or "",
            )
        )
        return events

    def query(
        self,
        *,
        correlation_id: str | None = None,
        event_type: str | None = None,
        accepted_name: str | None = None,
        safe_status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Read-only query boundary over stable identifiers/enums only."""

        results: Iterable[dict[str, Any]] = self.all()
        if correlation_id is not None:
            results = [e for e in results if e.get("correlation_id") == correlation_id]
        if event_type is not None:
            results = [e for e in results if e.get("event_type") == event_type]
        if safe_status is not None:
            results = [e for e in results if (e.get("safe_status") or {}).get("status") == safe_status]
        if accepted_name is not None:
            results = [e for e in results if (e.get("taxon") or {}).get("accepted_name") == accepted_name]
        return list(results)

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)


# Process-local default store for the reference/proof path. Durable backends
# implement the same interface; nothing here writes to a production database.
_default_store = ObservationStore()


def get_default_store() -> ObservationStore:
    return _default_store
