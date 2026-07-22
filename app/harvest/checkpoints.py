"""Checkpoint storage contracts for Harvester V2."""

from __future__ import annotations

from dataclasses import asdict, replace
from datetime import datetime, timezone
from threading import RLock
from typing import Mapping, Protocol, Any

from .models import HarvestCheckpoint


class CheckpointStore(Protocol):
    """Persistence contract for resumable harvest state."""

    def load(self, source: str, job_key: str) -> HarvestCheckpoint | None:
        ...

    def save(self, checkpoint: HarvestCheckpoint) -> None:
        ...

    def save_from_state(self, source: str, job_key: str, state: Mapping[str, Any]) -> None:
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
            self._items[(checkpoint.source, checkpoint.job_key)] = replace(
                checkpoint,
                updated_at=datetime.now(timezone.utc),
            )

    def save_from_state(self, source: str, job_key: str, state: Mapping[str, Any]) -> None:
        checkpoint = HarvestCheckpoint(
            source=source,
            job_key=job_key,
            cursor=state.get("cursor"),
            offset=int(state.get("offset", 0)),
            processed=int(state.get("processed", 0)),
            completed=bool(state.get("completed", False)),
            state={
                key: value
                for key, value in state.items()
                if key not in {"cursor", "offset", "processed", "completed"}
            },
        )
        self.save(checkpoint)

    def clear(self, source: str, job_key: str) -> None:
        with self._lock:
            self._items.pop((source, job_key), None)
