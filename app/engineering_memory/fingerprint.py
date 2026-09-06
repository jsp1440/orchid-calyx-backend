"""Deterministic fingerprints for lesson invalidation.

A lesson is only trustworthy while the environment it was learned in still
holds.  We fingerprint three axes:

* ``dependency_fingerprint`` — hash of a normalized dependency/version map.
* ``schema_fingerprint`` — hash of a schema/version marker.
* ``file_fingerprints`` — per-file content hashes.

When any recorded fingerprint no longer matches the current environment, the
lesson is deterministically invalidated.  The hashing is stable and
order-independent so identical inputs always yield identical fingerprints.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping


def _stable_hash(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def dependency_fingerprint(dependencies: Mapping[str, str] | None) -> str | None:
    """Fingerprint a dependency name -> version map (order-independent)."""

    if not dependencies:
        return None
    normalized = {
        str(k).strip().lower(): str(v).strip() for k, v in dependencies.items()
    }
    return _stable_hash(normalized)


def schema_fingerprint(marker: str | Mapping[str, str] | None) -> str | None:
    """Fingerprint a schema/version marker."""

    if not marker:
        return None
    return _stable_hash(marker)


def file_fingerprints(files: Mapping[str, str] | None) -> dict[str, str]:
    """Fingerprint a path -> content map into a path -> sha256 map."""

    if not files:
        return {}
    return {
        str(path): hashlib.sha256(str(content).encode("utf-8")).hexdigest()
        for path, content in files.items()
    }


def fingerprints_diverged(
    *,
    stored_dependency: str | None,
    stored_schema: str | None,
    stored_files: Mapping[str, str] | None,
    current_dependency: str | None,
    current_schema: str | None,
    current_files: Mapping[str, str] | None,
) -> tuple[bool, list[str]]:
    """Return whether the current environment diverged from stored fingerprints.

    A missing (``None``) *current* fingerprint on a given axis is treated as
    "not evaluated" for that axis and does not trigger invalidation, so callers
    can check only the axes they can observe.  Divergence reasons are returned
    for auditability.
    """

    reasons: list[str] = []

    if (
        current_dependency is not None
        and stored_dependency is not None
        and current_dependency != stored_dependency
    ):
        reasons.append("dependency_fingerprint_changed")

    if (
        current_schema is not None
        and stored_schema is not None
        and current_schema != stored_schema
    ):
        reasons.append("schema_fingerprint_changed")

    if current_files:
        stored = dict(stored_files or {})
        for path, digest in current_files.items():
            if path in stored and stored[path] != digest:
                reasons.append(f"file_fingerprint_changed:{path}")

    return (bool(reasons), reasons)
