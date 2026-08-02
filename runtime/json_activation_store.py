"""Small JSON-backed activation-state store for deployed Mission Control.

The store fails closed when the file is absent or unreadable. It is intended for
single-process deployments; a database-backed store can replace it later without
changing the controller contract.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any


class JsonActivationStateStore:
    """Persist activation state atomically in a local JSON file."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._lock = Lock()

    def load(self) -> dict[str, Any] | None:
        with self._lock:
            if not self._path.exists():
                return None
            try:
                payload = json.loads(self._path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            return payload if isinstance(payload, dict) else None

    def save(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._path.with_suffix(f"{self._path.suffix}.tmp")
            temporary.write_text(
                json.dumps(payload, sort_keys=True, indent=2),
                encoding="utf-8",
            )
            temporary.replace(self._path)
