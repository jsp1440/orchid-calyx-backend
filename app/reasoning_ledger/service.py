"""In-memory reasoning-ledger service with append-only semantics.

Each write produces a new immutable :class:`ReasoningLedger` version that is
stored alongside all previous versions, providing a complete audit history.
Tenant/project isolation is enforced on every read and write.

All mutating operations (create, append, review, resolve_conflict, publish) hold
the instance lock for the full read-validate-write cycle so that concurrent
callers cannot overwrite each other's updates.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from datetime import datetime, timezone
from uuid import UUID

from . import gate as publication_gate
from .contracts import ReasoningLedgerService
from .identity import deterministic_ledger_id
from .models import (
    LedgerEntry,
    LedgerError,
    LedgerStatus,
    LedgerValidationError,
    ReasoningLedger,
    ReviewDecision,
)


class LedgerNotFoundError(LedgerError, KeyError):
    """Raised when the requested ledger cannot be found."""


class LedgerTenantError(LedgerError, PermissionError):
    """Raised when the actor's tenant does not match the ledger's tenant."""


def _parse_uuid(value: str) -> UUID:
    try:
        return UUID(value)
    except (ValueError, AttributeError) as exc:
        raise LedgerNotFoundError(f"invalid ledger_id: {value!r}") from exc


def _assign_sequence(entry: LedgerEntry, sequence: int) -> LedgerEntry:
    """Return a new :class:`LedgerEntry` with the service-assigned *sequence*.

    Because :class:`LedgerEntry` is a frozen dataclass with an ``init=False``
    ``fingerprint`` field we must reconstruct the object rather than use
    ``dataclasses.replace``.  The fingerprint is recomputed in ``__post_init__``
    from the new sequence value, so the resulting entry is fully self-consistent.
    """
    return LedgerEntry(
        entry_id=entry.entry_id,
        kind=entry.kind,
        version=entry.version,
        sequence=sequence,
        text=entry.text,
        author=entry.author,
        tenant_id=entry.tenant_id,
        project_id=entry.project_id,
        provenance=entry.provenance,
        uncertainty=entry.uncertainty,
        conflict_state=entry.conflict_state,
        references_entry_ids=entry.references_entry_ids,
        tags=entry.tags,
        attributes=entry.attributes,
        created_at=entry.created_at,
        is_private_cot=entry.is_private_cot,
    )


class InMemoryReasoningLedgerService(ReasoningLedgerService):
    """Thread-safe, append-only in-memory reasoning-ledger store.

    Stores every historical version to support full audit retrieval.

    All mutating paths acquire ``_lock`` for the entire read-validate-write
    cycle so that concurrent callers cannot produce lost updates or split-brain
    versions.
    """

    def __init__(self) -> None:
        # ledger_id -> list[ReasoningLedger] (all versions, oldest first)
        self._history: dict[UUID, list[ReasoningLedger]] = defaultdict(list)
        # (tenant_id, project_id, title) -> ledger_id for idempotent creation
        self._logical_keys: dict[tuple[str, str, str], UUID] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Internal helpers (must be called with _lock held unless noted)
    # ------------------------------------------------------------------

    def _get_current_locked(self, lid: UUID, tenant_id: str) -> ReasoningLedger:
        """Return the current ledger version; caller must hold _lock."""
        versions = self._history.get(lid)
        if not versions:
            raise LedgerNotFoundError(f"ledger not found: {lid!s}")
        current = versions[-1]
        if current.tenant_id != tenant_id:
            raise LedgerTenantError(f"tenant mismatch for ledger {lid!s}")
        return current

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
        """Create a new ledger using a deterministic ID; idempotent on retry.

        If a ledger with the same (tenant_id, project_id, title) already
        exists, the current version of that ledger is returned unchanged.
        """
        lid = deterministic_ledger_id(tenant_id, project_id, title)
        logical_key = (tenant_id.strip(), project_id.strip(), title.strip())
        with self._lock:
            existing_lid = self._logical_keys.get(logical_key)
            if existing_lid is not None:
                # Idempotent: return the existing current ledger.
                return self._history[existing_lid][-1]
            ledger = ReasoningLedger(
                ledger_id=lid,
                tenant_id=tenant_id,
                project_id=project_id,
                title=title,
                description=description,
                created_by=created_by,
            )
            self._history[lid].append(ledger)
            self._logical_keys[logical_key] = lid
        return ledger

    def append(
        self,
        ledger_id: str,
        entry: LedgerEntry,
        *,
        actor: str,
        tenant_id: str,
    ) -> ReasoningLedger:
        lid = _parse_uuid(ledger_id)
        with self._lock:
            current = self._get_current_locked(lid, tenant_id)
            if current.status in {LedgerStatus.PUBLISHED, LedgerStatus.BLOCKED}:
                raise LedgerValidationError(
                    f"cannot append entries to a {current.status.value} ledger"
                )
            if entry.tenant_id != tenant_id or entry.project_id != current.project_id:
                raise LedgerValidationError(
                    "appended entry must share the ledger's tenant_id and project_id"
                )
            # Service assigns strictly monotonic sequence; caller-supplied value
            # is replaced so the ledger is the sole authority on position.
            sequence = len(current.entries)
            sequenced_entry = _assign_sequence(entry, sequence)
            next_ledger = current.append(sequenced_entry)
            self._history[lid].append(next_ledger)
        return next_ledger

    def current(self, ledger_id: str, *, tenant_id: str) -> ReasoningLedger:
        lid = _parse_uuid(ledger_id)
        with self._lock:
            return self._get_current_locked(lid, tenant_id)

    def history(self, ledger_id: str, *, tenant_id: str) -> list[ReasoningLedger]:
        lid = _parse_uuid(ledger_id)
        with self._lock:
            self._get_current_locked(lid, tenant_id)  # validates existence + tenant
            return list(self._history[lid])

    def validate(self, ledger_id: str, *, tenant_id: str) -> list[str]:
        lid = _parse_uuid(ledger_id)
        with self._lock:
            ledger = self._get_current_locked(lid, tenant_id)
        violations = publication_gate.evaluate(ledger)
        return [v.message for v in violations]

    def review(
        self,
        ledger_id: str,
        decision: ReviewDecision,
        *,
        tenant_id: str,
    ) -> ReasoningLedger:
        lid = _parse_uuid(ledger_id)
        with self._lock:
            current = self._get_current_locked(lid, tenant_id)
            if current.status is LedgerStatus.PUBLISHED:
                raise LedgerValidationError("cannot review a published ledger")
            # with_review binds decision.ledger_version to the current version.
            next_ledger = current.with_review(decision)
            self._history[lid].append(next_ledger)
        return next_ledger

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
        """Atomically apply one explicit terminal conflict disposition."""
        lid = _parse_uuid(ledger_id)
        with self._lock:
            current = self._get_current_locked(lid, tenant_id)
            if current.status is LedgerStatus.PUBLISHED:
                raise LedgerValidationError("cannot modify a published ledger")
            authenticated_actor = actor or tenant_id
            if resolution_state == "resolved":
                next_ledger = current.resolve_conflict(
                    conflict_entry_id,
                    rationale=rationale,
                    actor=authenticated_actor,
                )
            elif resolution_state == "superseded":
                next_ledger = current.supersede_conflict(
                    conflict_entry_id,
                    rationale=rationale,
                    actor=authenticated_actor,
                )
            else:
                raise LedgerValidationError("UNSUPPORTED_CONFLICT_DISPOSITION")
            self._history[lid].append(next_ledger)
        return next_ledger

    def publish(self, ledger_id: str, *, tenant_id: str) -> ReasoningLedger:
        """Publish the ledger after passing all gate checks.

        Raises :exc:`LedgerPublicationError` if the gate rejects the ledger.
        All gate checks and the state write are performed atomically under the
        instance lock.
        """
        lid = _parse_uuid(ledger_id)
        with self._lock:
            current = self._get_current_locked(lid, tenant_id)
            # assert_publishable checks version-bound approval, unresolved
            # conflicts, and conclusion confidence inside the locked region so
            # no concurrent append can slip through between the check and write.
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
                conflict_dispositions=current.conflict_dispositions,
                resolved_conflict_ids=current.resolved_conflict_ids,
                created_by=current.created_by,
                created_at=current.created_at,
                updated_at=now,
            )
            self._history[lid].append(published)
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

    def list_for_tenant(self, tenant_id: str) -> list[ReasoningLedger]:
        with self._lock:
            all_histories = list(self._history.values())
        result = []
        for versions in all_histories:
            if not versions:
                continue
            current = versions[-1]
            if current.tenant_id == tenant_id:
                result.append(current)
        return result
