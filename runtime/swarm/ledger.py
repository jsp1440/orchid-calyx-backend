"""ExecutionLedger — in-memory store for governed execution entries."""

from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal
from typing import Any

from .models import LedgerEntry


class ExecutionLedger:
    """Append-friendly store for LedgerEntry records.

    Thread safety: mutations (_add_locked, _update_locked) are called only
    while the governor's own lock is held. The public read methods (all, get)
    return snapshots and are safe to call from test code after all mutations
    are complete.
    """

    def __init__(self) -> None:
        self._entries: dict[str, LedgerEntry] = {}

    # ------------------------------------------------------------------
    # Governor-internal write helpers (called with governor lock held)
    # ------------------------------------------------------------------

    def _add_locked(self, entry: LedgerEntry) -> None:
        self._entries[entry.entry_id] = entry

    def _update_locked(self, entry_id: str, **updates: Any) -> LedgerEntry:
        old = self._entries[entry_id]
        # Only apply non-None updates that differ from sentinel
        filtered = {
            k: v for k, v in updates.items() if v is not None or k in _NULLABLE_FIELDS
        }
        new = dataclasses.replace(old, **filtered)
        self._entries[entry_id] = new
        return new

    # ------------------------------------------------------------------
    # Public read API
    # ------------------------------------------------------------------

    def all(self) -> list[LedgerEntry]:
        return list(self._entries.values())

    def get(self, entry_id: str) -> LedgerEntry:
        return self._entries[entry_id]

    def daily_spent(self, reference_date: date) -> Decimal:
        total = Decimal(0)
        for e in self._entries.values():
            if (
                e.started_at.date() == reference_date
                and e.estimated_cost_usd is not None
            ):
                total += e.estimated_cost_usd
        return total

    def monthly_spent(self, year: int, month: int) -> Decimal:
        total = Decimal(0)
        for e in self._entries.values():
            if (
                e.started_at.year == year
                and e.started_at.month == month
                and e.estimated_cost_usd is not None
            ):
                total += e.estimated_cost_usd
        return total


# Fields that are explicitly nullable (None is a valid update value)
_NULLABLE_FIELDS = frozenset(
    {
        "ended_at",
        "estimated_tokens",
        "estimated_cost_usd",
        "termination_reason",
        "succeeded",
    }
)
