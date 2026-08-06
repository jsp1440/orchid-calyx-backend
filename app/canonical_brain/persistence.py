from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Protocol

from .models import BrainSnapshot
from .registry import CanonicalBrainRegistry


class BrainSnapshotRepository(Protocol):
    def save(self, registry: CanonicalBrainRegistry) -> BrainSnapshot: ...

    def load(self) -> CanonicalBrainRegistry: ...


class JsonBrainSnapshotRepository:
    """Deterministic, atomic file-backed persistence for candidate Brain snapshots."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def save(self, registry: CanonicalBrainRegistry) -> BrainSnapshot:
        snapshot = registry.snapshot()
        payload = snapshot.model_dump(mode="json")
        serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.tmp")
        temporary.write_text(serialized, encoding="utf-8")
        os.replace(temporary, self.path)
        return snapshot

    def load(self) -> CanonicalBrainRegistry:
        if not self.path.exists():
            raise FileNotFoundError(self.path)
        snapshot = BrainSnapshot.model_validate_json(self.path.read_text(encoding="utf-8"))
        registry = CanonicalBrainRegistry()
        for record in snapshot.objects:
            registry.register_object(record)
        for relation in snapshot.relationships:
            registry.register_relationship(relation)
        if registry.snapshot().snapshot_checksum != snapshot.snapshot_checksum:
            raise ValueError("Brain snapshot checksum mismatch")
        return registry
