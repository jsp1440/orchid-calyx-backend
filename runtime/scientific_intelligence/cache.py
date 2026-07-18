"""BUILD-062 in-memory TTL cache for scientific intelligence payloads.

Each subsystem adapter uses this cache to avoid hitting the database on
every request.  The TTL is intentionally short (60 s by default) so that
live data is surfaced within one polling cycle while still protecting the
database from high-frequency reads.

Cache keys are plain strings; values are arbitrary dicts with a recorded
timestamp.  No external dependency is required.
"""

from __future__ import annotations

import time
from typing import Any

_STORE: dict[str, tuple[float, dict[str, Any]]] = {}
DEFAULT_TTL: int = 60  # seconds


def get_cached(key: str, ttl: int = DEFAULT_TTL) -> dict[str, Any] | None:
    """Return a cached payload if it exists and has not expired."""
    entry = _STORE.get(key)
    if entry is None:
        return None
    stored_at, payload = entry
    if ttl <= 0 or time.monotonic() - stored_at > ttl:
        del _STORE[key]
        return None
    return payload


def set_cached(key: str, payload: dict[str, Any]) -> None:
    """Store a payload under *key* with the current timestamp."""
    _STORE[key] = (time.monotonic(), payload)


def invalidate(key: str) -> None:
    """Remove a single cache entry."""
    _STORE.pop(key, None)


def invalidate_all() -> None:
    """Clear the entire scientific intelligence cache."""
    _STORE.clear()


def cache_stats() -> dict[str, Any]:
    """Return diagnostic information about the current cache state."""
    now = time.monotonic()
    return {
        "entries": len(_STORE),
        "keys": sorted(_STORE.keys()),
        "ages_seconds": {key: round(now - stored_at, 1) for key, (stored_at, _) in _STORE.items()},
    }
