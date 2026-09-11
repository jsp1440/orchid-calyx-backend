"""Immutable provenance hashing for CALYX-EVOLVE-001 experiment records.

Every durable record in the evolve loop carries a content hash computed over a
canonical JSON projection.  Hashing is stable across processes and Python
versions: keys are sorted, separators are fixed, and non-ASCII characters are
escaped.  Floats are rounded to a fixed precision so that a replay key does not
change because of platform float formatting.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

HASH_PREFIX = "sha256:"

#: Float precision used when canonicalising payloads for hashing.
FLOAT_PRECISION = 9


class ProvenanceError(RuntimeError):
    """Raised when a record cannot produce a trustworthy provenance hash."""


def _canonicalise(value: Any) -> Any:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ProvenanceError(f"non-finite float is not hashable: {value!r}")
        return round(value, FLOAT_PRECISION)
    if isinstance(value, dict):
        return {str(key): _canonicalise(item) for key, item in sorted(value.items(), key=lambda kv: str(kv[0]))}
    if isinstance(value, (list, tuple)):
        return [_canonicalise(item) for item in value]
    if isinstance(value, (str, int, bool)) or value is None:
        return value
    raise ProvenanceError(f"unhashable payload member of type {type(value).__name__}")


def canonical_json(payload: Any) -> str:
    """Return the canonical JSON text used as hash input."""

    return json.dumps(
        _canonicalise(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def content_hash(payload: Any) -> str:
    """Return a stable ``sha256:`` content hash for ``payload``."""

    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"{HASH_PREFIX}{digest}"


def combine_hashes(*hashes: str) -> str:
    """Combine ordered component hashes into one composite hash."""

    for value in hashes:
        if not value or not value.startswith(HASH_PREFIX):
            raise ProvenanceError(f"not a content hash: {value!r}")
    return content_hash({"components": list(hashes)})
