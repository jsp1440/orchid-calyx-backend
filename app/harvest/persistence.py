"""Persistence contracts and in-memory implementation for Harvester V2."""

from __future__ import annotations

from threading import RLock
from typing import Any, Mapping, Protocol


class HarvestPersistence(Protocol):
    def save_batch(self, *, source: str, records: list[Mapping[str, Any]]) -> int:
        ...


class InMemoryHarvestPersistence:
    """Deterministic persistence adapter for tests and local dry-runs."""

    def __init__(self) -> None:
        self._records: dict[tuple[str, str], dict[str, Any]] = {}
        self._lock = RLock()

    def save_batch(self, *, source: str, records: list[Mapping[str, Any]]) -> int:
        saved = 0
        with self._lock:
            for record in records:
                source_record_id = str(record.get("source_record_id") or record.get("key") or "")
                if not source_record_id:
                    raise ValueError("record is missing source_record_id")
                self._records[(source, source_record_id)] = dict(record)
                saved += 1
        return saved

    def all(self, source: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            values = [
                dict(record)
                for (record_source, _), record in self._records.items()
                if source is None or source == record_source
            ]
        return values
