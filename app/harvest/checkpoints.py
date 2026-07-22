"""Checkpoint storage contracts for Harvester V2."""

from __future__ import annotations

from dataclasses import asdict
from threading import RLock
from typing import Protocol

from .models import HarvestCheckpoint


class CheckpointStore(Protocol):
    """Persistence contract for resumable harvest state."""

    def load(self, source: str, job_key: str) -> HarvestCheckpoint | None:
        ...

    def save(self, checkpoint: HarvestCheckpoint) -> None:
        ...

    def clear(self, source: str, job_key: str) -> None:
        ...


class InMemoryCheckpointStore:
    """Thread-safe checkpoint store for tests and local execution."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], HarvestCheckpoint] = {}
        self._lock = RLock()

    def load(self, source: str, job_key: str) -> HarvestCheckpoint | None:
        with self._lock:
            checkpoint = self._items.get((source, job_key))
            if checkpoint is None:
                return None
            return HarvestCheckpoint(**asdict(checkpoint))

    def save(self, checkpoint: HarvestCheckpoint) -> None:
        with self._lock:
            self._items[(checkpoint.source, checkpoint.job_key)] = HarvestCheckpoint(
                **asdict(checkpoint)
            )

    def clear(self, source: str, job_key: str) -> None:
        with self._lock:
            self._items.pop((source, job_key), None)
