from __future__ import annotations

from typing import Any
from uuid import UUID

from app.archive.registry import ArchiveRegistry


def generate_manifest(run_id: UUID, registry: ArchiveRegistry | None = None) -> dict[str, Any]:
    """Return the deterministic run manifest ordered by relative path."""
    return (registry or ArchiveRegistry()).manifest(run_id)
