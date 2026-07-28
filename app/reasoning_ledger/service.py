"""In-memory reasoning-ledger service with append-only semantics.

Each write produces a new immutable :class:`ReasoningLedger` version that is
stored alongside all previous versions, providing a complete audit history.
Tenant/project isolation is enforced on every read and write.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, timezone
from uuid import UUID

from . import gate as publication_gate
from .contracts import ReasoningLedgerService
from .models import (
    LedgerEntry,
    LedgerError,
    LedgerPublicationError,
    LedgerStatus,
    LedgerValidationError,
    ReasoningLedger,
    ReviewDecision,
    ReviewOutcome,
)


class LedgerNotFoundError(LedgerError, KeyError):
    """Raised when the requested ledger cannot be found."""


class LedgerTenantError(LedgerError, PermissionError):
    """Raised when the actor's tenant does not match the ledger's tenant."""


class InMemoryReasoningLedgerService(ReasoningLedgerService):
    """Thread-safe, append-only in-memory reasoning-ledger store.

    Stores every historical version to support full audit retrieval.
    """

    def __init__(self) -> None:
        # ledger_id -> list[ReasoningLedger] (all versions, oldest first)
        self._history: dict[UUID, list[ReasoningLedger]] = defaultdict(list)
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require(self, ledger_id_str: str, tenant_id: str) -> ReasoningLedger:
        try:
            lid = UUID(ledger_id_str)
        except ValueError as exc:
            raise LedgerNotFoundError(f"invalid ledger_id: {ledger_id_str!r}") from exc
        with self._lock:
            versions = self._history.get(lid)
        if not versions:
            raise LedgerNotFoundError(f"ledger not found: {ledger_id_str!r}")
        current = versions[-1]
        if current.tenant_id != tenant_id:
            raise LedgerTenantError(
                f"tenant mismatch for ledger {ledger_id_str!r}"
            )
        return current

    def _push(self, ledger: ReasoningLedger) -> None:
        with self._lock:
            self._history[ledger.ledger_id].append(ledger)

    # ------------------------------------------------------------------
    # Service operations
    # ------------------------------------------------------------------

    def create(
        self,
        *,
        tenant_id: str,
        project_id: str,
        title: str,
        description: str = "",
        created_by: str,
    ) -> ReasoningLedger:
        ledger = ReasoningLedger(
            tenant_id=tenant_id,
            project_id=project_id,
            title=title,
            description=description,
            created_by=created_by,
        )
        self._push(ledger)
        return ledger

    def append(
        self,
        ledger_id: str,
        entry: LedgerEntry,
        *,
        actor: str,
        tenant_id: str,
    ) -> ReasoningLedger:
        current = self._require(ledger_id, tenant_id)
        if current.status in {LedgerStatus.PUBLISHED, LedgerStatus.BLOCKED}:
            raise LedgerValidationError(
                f"cannot append entries to a {current.status.value} ledger"
            )
        if entry.tenant_id != tenant_id or entry.project_id != current.project_id:
            raise LedgerValidationError(
                "appended entry must share the ledger's tenant_id and project_id"
            )
        next_ledger = current.append(entry)
        self._push(next_ledger)
        return next_ledger

    def current(self, ledger_id: str, *, tenant_id: str) -> ReasoningLedger:
        return self._require(ledger_id, tenant_id)

    def history(
        self, ledger_id: str, *, tenant_id: str
    ) -> list[ReasoningLedger]:
        self._require(ledger_id, tenant_id)  # validates existence + tenant
        try:
            lid = UUID(ledger_id)
        except ValueError as exc:
            raise LedgerNotFoundError(f"invalid ledger_id: {ledger_id!r}") from exc
        with self._lock:
            return list(self._history[lid])

    def validate(self, ledger_id: str, *, tenant_id: str) -> list[str]:
        ledger = self._require(ledger_id, tenant_id)
        violations = publication_gate.evaluate(ledger)
        return [v.message for v in violations]

    def review(
        self,
        ledger_id: str,
        decision: ReviewDecision,
        *,
        tenant_id: str,
    ) -> ReasoningLedger:
        current = self._require(ledger_id, tenant_id)
        if current.status is LedgerStatus.PUBLISHED:
            raise LedgerValidationError("cannot review a published ledger")
        next_ledger = current.with_review(decision)
        self._push(next_ledger)
        return next_ledger

    def publish(self, ledger_id: str, *, tenant_id: str) -> ReasoningLedger:
        """Publish the ledger after passing all gate checks.

        Raises :exc:`LedgerPublicationError` if the gate rejects the ledger.
        """
        current = self._require(ledger_id, tenant_id)
        publication_gate.assert_publishable(current)
        now = datetime.now(timezone.utc)
        published = ReasoningLedger(
            ledger_id=current.ledger_id,
            tenant_id=current.tenant_id,
            project_id=current.project_id,
            title=current.title,
            description=current.description,
            status=LedgerStatus.PUBLISHED,
            version=current.version + 1,
            entries=current.entries,
            review_decisions=current.review_decisions,
            created_by=current.created_by,
            created_at=current.created_at,
            updated_at=now,
        )
        self._push(published)
        return published

    def list_for_project(
        self,
        tenant_id: str,
        project_id: str,
    ) -> list[ReasoningLedger]:
        with self._lock:
            all_histories = list(self._history.values())
        result = []
        for versions in all_histories:
            if not versions:
                continue
            current = versions[-1]
            if current.tenant_id == tenant_id and current.project_id == project_id:
                result.append(current)
        return result
