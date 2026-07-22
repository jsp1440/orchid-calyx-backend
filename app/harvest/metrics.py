"""Lightweight harvest metrics collection."""

from __future__ import annotations

from collections import defaultdict
from threading import RLock
from typing import Mapping


class HarvestMetrics:
    """Thread-safe counters keyed by source."""

    def __init__(self) -> None:
        self._values: dict[str, dict[str, int]] = defaultdict(dict)
        self._lock = RLock()

    def increment(self, source: str, metric: str, amount: int = 1) -> None:
        with self._lock:
            current = self._values[source].get(metric, 0)
            self._values[source][metric] = current + amount

    def set(self, source: str, metric: str, value: int) -> None:
        with self._lock:
            self._values[source][metric] = value

    def snapshot(self, source: str) -> Mapping[str, int]:
        with self._lock:
            return dict(self._values.get(source, {}))

    def reset(self, source: str) -> None:
        with self._lock:
            self._values.pop(source, None)
