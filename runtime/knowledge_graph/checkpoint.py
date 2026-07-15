"""Per-domain checkpointing so a build can resume without redoing work.

A checkpoint records, for one domain, its terminal status, the aggregated
publish statistics, the validation summary and the number of source rows
processed.  ``Resume`` consults completed checkpoints and skips those domains.

Two stores are provided: an in-memory store (tests) and a JSON-file store
(operators).  Both share the same interface.  Neither touches the graph
database — checkpoints are build-run metadata, not graph data.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass, field
from typing import Any

STATUS_COMPLETED = "completed"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"


@dataclass
class Checkpoint:
    domain: str
    status: str
    rows_processed: int = 0
    stats: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.time)

    def is_complete(self) -> bool:
        return self.status in (STATUS_COMPLETED, STATUS_SKIPPED)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class InMemoryCheckpointStore:
    def __init__(self) -> None:
        self._data: dict[str, Checkpoint] = {}

    def save(self, checkpoint: Checkpoint) -> None:
        checkpoint.updated_at = time.time()
        self._data[checkpoint.domain] = checkpoint

    def load(self, domain: str) -> Checkpoint | None:
        return self._data.get(domain)

    def all(self) -> list[Checkpoint]:
        return list(self._data.values())

    def completed_domains(self) -> set[str]:
        return {c.domain for c in self._data.values() if c.is_complete()}

    def clear(self) -> None:
        self._data.clear()


class JsonFileCheckpointStore:
    """File-backed checkpoints; safe to resume across process restarts."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._data: dict[str, Checkpoint] = {}
        self._load_file()

    def _load_file(self) -> None:
        if not os.path.exists(self._path):
            return
        with open(self._path, encoding="utf-8") as fh:
            raw = json.load(fh)
        for domain, payload in raw.items():
            self._data[domain] = Checkpoint(**payload)

    def _flush(self) -> None:
        os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self._path) or ".", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump({d: c.to_dict() for d, c in self._data.items()}, fh, indent=2)
            os.replace(tmp, self._path)  # atomic
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)

    def save(self, checkpoint: Checkpoint) -> None:
        checkpoint.updated_at = time.time()
        self._data[checkpoint.domain] = checkpoint
        self._flush()

    def load(self, domain: str) -> Checkpoint | None:
        return self._data.get(domain)

    def all(self) -> list[Checkpoint]:
        return list(self._data.values())

    def completed_domains(self) -> set[str]:
        return {c.domain for c in self._data.values() if c.is_complete()}

    def clear(self) -> None:
        self._data.clear()
        if os.path.exists(self._path):
            os.remove(self._path)
