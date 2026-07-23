"""Core interfaces for the Orchid Continuum harvesting framework."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Iterable, Mapping

from .models import HarvestPage


class BaseHarvester(ABC):
    """Abstract contract implemented by every source harvester plugin."""

    source: str

    def __init__(self, *, persistence: Any, checkpoints: Any, metrics: Any) -> None:
        self.persistence = persistence
        self.checkpoints = checkpoints
        self.metrics = metrics

    def authenticate(self) -> None:
        """Authenticate with the upstream source when required."""

    @abstractmethod
    def fetch_page(self, checkpoint: Mapping[str, Any] | None = None) -> HarvestPage:
        """Fetch one page or batch from the upstream source."""

    @abstractmethod
    def normalize(self, record: Mapping[str, Any]) -> Mapping[str, Any]:
        """Convert one raw source record to the canonical harvest shape."""

    @abstractmethod
    def validate(self, record: Mapping[str, Any]) -> bool:
        """Return True when a normalized record is acceptable."""

    def extract_images(self, record: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
        return ()

    def extract_traits(self, record: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
        return ()

    def extract_occurrences(self, record: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
        return ()

    def persist(self, batch: Iterable[Mapping[str, Any]]) -> int:
        """Persist a normalized batch using the injected persistence adapter."""
        return int(self.persistence.save_batch(source=self.source, records=list(batch)))

    def checkpoint(self, job_key: str, state: Mapping[str, Any]) -> None:
        """Persist resumable state for this source and job."""
        self.checkpoints.save_from_state(self.source, job_key, dict(state))

    def resume(self, job_key: str) -> Mapping[str, Any] | None:
        """Load resumable state for this source and job."""
        checkpoint = self.checkpoints.load(self.source, job_key)
        return None if checkpoint is None else {
            "cursor": checkpoint.cursor,
            "offset": checkpoint.offset,
            "processed": checkpoint.processed,
            "completed": checkpoint.completed,
            **dict(checkpoint.state),
        }

    def statistics(self) -> Mapping[str, Any]:
        """Return the current metric snapshot for this source."""
        return self.metrics.snapshot(self.source)
