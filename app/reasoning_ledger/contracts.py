"""Abstract service contracts for the reasoning ledger."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from .models import LedgerEntry, ReasoningLedger, ReviewDecision


class ReasoningLedgerService(ABC):
    """Contract for reasoning-ledger lifecycle operations."""

    @abstractmethod
    def create(
        self,
        *,
        tenant_id: str,
        project_id: str,
        title: str,
        description: str,
        created_by: str,
    ) -> ReasoningLedger:
        """Create and persist a new ledger in DRAFT status.

        Uses a deterministic ledger ID derived from (tenant_id, project_id,
        title).  Repeated calls with identical arguments return the existing
        ledger rather than creating a duplicate.
        """
        raise NotImplementedError

    @abstractmethod
    def append(
        self,
        ledger_id: str,
        entry: LedgerEntry,
        *,
        actor: str,
        tenant_id: str,
    ) -> ReasoningLedger:
        """Append a new entry and return the updated ledger.

        The service assigns the entry's sequence number (strictly increasing)
        regardless of the value supplied by the caller.

        Raises :exc:`LedgerNotFoundError` if the ledger does not exist.
        Raises :exc:`LedgerTenantError` if the actor's tenant does not match.
        """
        raise NotImplementedError

    @abstractmethod
    def current(self, ledger_id: str, *, tenant_id: str) -> ReasoningLedger:
        """Return the current state of a ledger.

        Raises :exc:`LedgerNotFoundError` if not found or tenant mismatch.
        """
        raise NotImplementedError

    @abstractmethod
    def history(self, ledger_id: str, *, tenant_id: str) -> list[ReasoningLedger]:
        """Return all historical versions of a ledger, oldest first."""
        raise NotImplementedError

    @abstractmethod
    def validate(self, ledger_id: str, *, tenant_id: str) -> list[str]:
        """Return a list of validation issues for the ledger.

        An empty list means the ledger passes all checks.
        """
        raise NotImplementedError

    @abstractmethod
    def review(
        self,
        ledger_id: str,
        decision: ReviewDecision,
        *,
        tenant_id: str,
    ) -> ReasoningLedger:
        """Attach a human review decision and advance ledger status.

        The decision is automatically bound to the current ledger version so
        that an approval cannot survive a later append.
        """
        raise NotImplementedError

    @abstractmethod
    def resolve_conflict(
        self,
        ledger_id: str,
        conflict_entry_id: UUID,
        *,
        tenant_id: str,
        resolution_state: str = "resolved",
        rationale: str = "Conflict substantively addressed.",
        actor: str | None = None,
    ) -> ReasoningLedger:
        """Apply a resolved or superseded disposition without mutating the entry.

        Returns the updated ledger.  Raises :exc:`LedgerValidationError` if
        the entry is not a CONFLICT entry or is already resolved.
        """
        raise NotImplementedError

    @abstractmethod
    def list_for_project(
        self,
        tenant_id: str,
        project_id: str,
    ) -> list[ReasoningLedger]:
        """Return all current ledgers for a tenant/project pair."""
        raise NotImplementedError
