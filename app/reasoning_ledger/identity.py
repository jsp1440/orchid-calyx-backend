"""Deterministic identity helpers for reasoning-ledger objects."""

from __future__ import annotations

import hashlib
from uuid import UUID, uuid5, NAMESPACE_URL

# A fixed private namespace UUID used to derive deterministic ledger IDs.
_LEDGER_NS = UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # NAMESPACE_URL
_ENTRY_NS = uuid5(NAMESPACE_URL, "orchid-calyx:reasoning-ledger:entry")


def deterministic_ledger_id(tenant_id: str, project_id: str, title: str) -> UUID:
    """Return a stable UUID for a ledger from its canonical identifying fields.

    Repeated calls with the same inputs always produce the same UUID so that
    re-creation of an identical ledger is idempotent.
    """
    seed = f"{tenant_id}:{project_id}:{title}"
    return uuid5(_LEDGER_NS, seed)


def deterministic_entry_id(
    ledger_id: UUID,
    sequence: int,
    text: str,
    author: str,
) -> UUID:
    """Return a stable UUID for an entry from its canonical position and content."""
    seed = f"{ledger_id}:{sequence}:{author}:{hashlib.sha256(text.encode()).hexdigest()}"
    return uuid5(_ENTRY_NS, seed)
