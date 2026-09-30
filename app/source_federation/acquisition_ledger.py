"""Durable cache/lease service for shared external acquisitions.

Lease fencing
-------------

A lease authorises exactly one worker to perform one paid external call for a
``resource_key``. Every successful :meth:`AcquisitionLedger.claim` that hands
out a lease mints a fresh random ``lease_token`` and returns it in the
:class:`ClaimResult`. :meth:`~AcquisitionLedger.complete` and
:meth:`~AcquisitionLedger.fail` take that ``ClaimResult`` back and write only
through a conditional ``UPDATE ... WHERE lease_holder = :me AND lease_token =
:token AND status = 'leased'``. The ``WHERE`` clause, not a prior Python-side
read, is the fence, so the check is atomic on SQLite and PostgreSQL alike.

The token matters, not just the holder: every
``SharedFirecrawlFederationService`` defaults to the same ``worker_id``, so a
holder-only fence would let a stale worker overwrite a live lease held under
the same name.

A worker whose lease was superseded (it expired and another worker claimed the
key) gets :class:`StaleLeaseError` and the ledger row is left untouched: the
live holder's lease, status, payload, counters and retry window survive. The
stale worker's result is deliberately NOT persisted anywhere -- the live
holder's own result is what populates the cache, and a result that bypassed
the fence carries no ledger provenance. The exception reports the credits the
stale worker says it spent so the caller can log them.

The fenced ``complete`` write depends on the fence alone. The consumer list
(bookkeeping, not lease state) is merged in the same statement only if it is
unchanged since the read, and otherwise in a best-effort follow-up; a
concurrent consumer joining an in-flight lease can never cause a paid result
to be discarded.

A lease that expired but was never re-claimed still carries the holder's token
and may still be completed or failed: nobody else was authorised in the
meantime, so accepting it costs nothing and wastes nothing.

``lease_token`` doubles as the row's version. Releasing a lease (complete or
fail) rotates it to a fresh random value that no worker holds, rather than
clearing it, so every lease transition changes it. Claim takeovers (a failed
row past its retry window, an expired lease, or a forced refresh) are then a
compare-and-swap on the token that was read: a worker that read a ``failed``
row cannot take it over after another worker has meanwhile claimed and
completed it (the ABA case a cleared token would allow). The claim loop,
including the retry after a unique-key insert race, is bounded; exhausting it
raises :class:`LedgerContentionError` rather than recursing or handing out a
lease.

Schema
------

The table is created only by ``migrations/20260930_acquisition_ledger.sql``,
never at request time. Before its first claim on an engine the ledger runs a
read-only schema check (:mod:`.acquisition_ledger_schema`); a missing table,
a missing ``lease_token`` or other column, an incompatible type or a missing
unique key raises :class:`LedgerSchemaUnavailableError` before any lease is
handed out, so the caller makes zero provider calls.
"""

from __future__ import annotations

import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import case
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from .acquisition import AcquisitionRecord, AcquisitionRequest
from .acquisition_ledger_schema import (
    LedgerSchemaUnavailableError,
    require_ledger_schema,
)
from .acquisition_models import AcquisitionLedgerRow

__all__ = [
    "MAX_LEDGER_ATTEMPTS",
    "AcquisitionLedger",
    "ClaimResult",
    "LedgerContentionError",
    "LedgerSchemaUnavailableError",
    "StaleLeaseError",
]

logger = logging.getLogger(__name__)

#: Upper bound on optimistic retries inside one ledger call. Each retry means
#: another writer changed the row between our read and our conditional write;
#: three consecutive losses is contention, not a normal race, and fails closed.
MAX_LEDGER_ATTEMPTS = 3


class StaleLeaseError(RuntimeError):
    """``complete``/``fail`` was called with a lease that is no longer live.

    Raised instead of mutating the ledger row, which now belongs to another
    lease (or to no lease). Nothing was written.
    """

    def __init__(
        self,
        *,
        resource_key: str,
        lease_holder: str | None,
        operation: str,
        unrecorded_credits: int = 0,
    ) -> None:
        self.resource_key = resource_key
        self.lease_holder = lease_holder
        self.operation = operation
        self.unrecorded_credits = unrecorded_credits
        super().__init__(
            f"stale acquisition lease: {operation} by {lease_holder!r} for "
            f"{resource_key} refused; the lease was superseded or released "
            f"and the ledger row was not modified"
        )


class LedgerContentionError(RuntimeError):
    """A ledger call could not make progress in ``MAX_LEDGER_ATTEMPTS`` attempts.

    ``claim`` raises it after losing its insert/compare-and-swap that often
    (no lease is handed out). ``complete`` raises it only after repeated
    transient database errors, with nothing committed.
    """

    def __init__(self, *, resource_key: str, operation: str, attempts: int) -> None:
        self.resource_key = resource_key
        self.operation = operation
        self.attempts = attempts
        super().__init__(
            f"acquisition ledger contention: {operation} for {resource_key} "
            f"gave up after {attempts} attempts"
        )


def _as_utc(value: datetime | None) -> datetime | None:
    """Return ``value`` as a timezone-aware UTC datetime.

    The ledger columns are ``DateTime(timezone=True)``. PostgreSQL returns
    aware values, but SQLite (and any backend without a timezone-aware
    column type) returns NAIVE values with the offset discarded. This ledger
    only ever writes UTC (see :func:`_utc_now`), so a naive value read back
    from the store is interpreted as UTC. A naive caller-supplied ``now`` is
    likewise treated as UTC.

    Normalising every operand before a comparison matters for fail-closed
    behaviour, not just for avoiding ``TypeError``: a naive/aware mismatch
    must never make an expired lease look valid, or an active lease or retry
    window look expired and admit a second credit-burning fetch.
    """
    if value is None:
        return None
    return _to_utc(value)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc_now(now: datetime | None) -> datetime:
    """Resolve the comparison instant as aware UTC.

    Values written to the store are derived from this, so they are always
    UTC. That keeps a naive read-back correct on SQLite, which drops the
    offset without converting: a ``+05:00`` instant stored as-is would read
    back five hours off.
    """
    return _to_utc(now) if now is not None else datetime.now(timezone.utc)


def _new_lease_token() -> str:
    return secrets.token_hex(16)


@dataclass(frozen=True, slots=True)
class ClaimResult:
    action: str  # cache_hit | acquired_lease | in_flight | retry_blocked
    row_id: int
    resource_key: str
    # Set only when ``action == "acquired_lease"``; pass this ClaimResult back
    # to ``complete``/``fail`` so the write is fenced on this exact lease.
    lease_holder: str | None = None
    lease_token: str | None = None


def _require_lease(lease: object, operation: str) -> ClaimResult:
    if not isinstance(lease, ClaimResult):
        raise TypeError(
            f"{operation} requires the ClaimResult returned by claim(); "
            f"got {type(lease).__name__}"
        )
    return lease


class AcquisitionLedger:
    def __init__(self, session: Session) -> None:
        self.session = session

    def claim(
        self,
        request: AcquisitionRequest,
        *,
        worker_id: str,
        lease_seconds: int = 120,
        now: datetime | None = None,
    ) -> ClaimResult:
        """Coalesce ``request`` onto the ledger; only ``acquired_lease`` may fetch.

        Raises :class:`LedgerSchemaUnavailableError` (no lease, nothing
        written) when the ledger table is missing or incompatible.
        """
        require_ledger_schema(self.session)
        now = _utc_now(now)
        for _attempt in range(MAX_LEDGER_ATTEMPTS):
            result = self._try_claim(
                request, worker_id=worker_id, lease_seconds=lease_seconds, now=now
            )
            if result is not None:
                return result
        raise LedgerContentionError(
            resource_key=request.key,
            operation="claim",
            attempts=MAX_LEDGER_ATTEMPTS,
        )

    def _try_claim(
        self,
        request: AcquisitionRequest,
        *,
        worker_id: str,
        lease_seconds: int,
        now: datetime,
    ) -> ClaimResult | None:
        """One claim attempt; ``None`` means a concurrent writer won the race."""
        self.session.expire_all()
        row = (
            self.session.query(AcquisitionLedgerRow)
            .filter(AcquisitionLedgerRow.resource_key == request.key)
            .with_for_update()
            .first()
        )
        if row is None:
            token = _new_lease_token()
            row = AcquisitionLedgerRow(
                resource_key=request.key,
                provider=request.provider,
                canonical_url=request.canonical_url,
                status="leased",
                lease_holder=worker_id,
                lease_token=token,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                consumers_json=json.dumps([request.consumer_module]),
            )
            self.session.add(row)
            try:
                self.session.commit()
            except IntegrityError:
                # Another worker inserted the same key first; re-read it.
                self.session.rollback()
                return None
            return ClaimResult("acquired_lease", row.id, request.key, worker_id, token)

        consumers = set(json.loads(row.consumers_json or "[]"))
        consumers.add(request.consumer_module)
        consumers_json = json.dumps(sorted(consumers))

        if row.status == "complete" and not request.force_refresh:
            row.consumers_json = consumers_json
            self.session.commit()
            return ClaimResult("cache_hit", row.id, request.key)
        next_retry_at = _as_utc(row.next_retry_at)
        if next_retry_at is not None and next_retry_at > now:
            row.consumers_json = consumers_json
            self.session.commit()
            return ClaimResult("retry_blocked", row.id, request.key)
        lease_expires_at = _as_utc(row.lease_expires_at)
        if (
            row.status == "leased"
            and lease_expires_at is not None
            and lease_expires_at > now
        ):
            row.consumers_json = consumers_json
            self.session.commit()
            return ClaimResult("in_flight", row.id, request.key)

        # Takeover: compare-and-swap on the token we just read (it changes on
        # every lease transition, see module docstring), so two workers that
        # both saw an expired/failed row cannot both win, and a row that went
        # through a whole claim/complete cycle since our read is re-read. On
        # PostgreSQL the row lock above already serialises them; on SQLite
        # (no row locks) this conditional UPDATE is what does. ``None`` is a
        # row written before the token column existed.
        row_id = row.id
        observed_token = row.lease_token
        token = _new_lease_token()
        swapped = (
            self.session.query(AcquisitionLedgerRow)
            .filter(
                AcquisitionLedgerRow.id == row_id,
                (
                    AcquisitionLedgerRow.lease_token.is_(None)
                    if observed_token is None
                    else AcquisitionLedgerRow.lease_token == observed_token
                ),
            )
            .update(
                {
                    AcquisitionLedgerRow.status: "leased",
                    AcquisitionLedgerRow.lease_holder: worker_id,
                    AcquisitionLedgerRow.lease_token: token,
                    AcquisitionLedgerRow.lease_expires_at: now
                    + timedelta(seconds=lease_seconds),
                    AcquisitionLedgerRow.consumers_json: consumers_json,
                },
                synchronize_session=False,
            )
        )
        if swapped != 1:
            self.session.rollback()
            return None
        self.session.commit()
        return ClaimResult("acquired_lease", row_id, request.key, worker_id, token)

    def cached_payload(self, resource_key: str) -> str | None:
        row = (
            self.session.query(AcquisitionLedgerRow)
            .filter(AcquisitionLedgerRow.resource_key == resource_key)
            .first()
        )
        return row.payload_json if row and row.status == "complete" else None

    def _fenced(self, lease: ClaimResult):
        """Query restricted to the row while ``lease`` is still the live lease."""
        return self.session.query(AcquisitionLedgerRow).filter(
            AcquisitionLedgerRow.resource_key == lease.resource_key,
            AcquisitionLedgerRow.status == "leased",
            AcquisitionLedgerRow.lease_holder == lease.lease_holder,
            AcquisitionLedgerRow.lease_token == lease.lease_token,
        )

    def complete(
        self,
        record: AcquisitionRecord,
        *,
        lease: ClaimResult,
        payload_json: str | None = None,
    ) -> None:
        """Record ``record`` as the result of ``lease``.

        Raises :class:`StaleLeaseError` (writing nothing) when ``lease`` is no
        longer the live lease for ``record.key``. Once the fence matches, the
        result write does not depend on anything else: concurrent consumer
        claims cannot veto it, and consumer bookkeeping afterwards is
        best-effort and never raises. Only repeated transient database errors
        (nothing committed) raise :class:`LedgerContentionError`.
        """
        lease = _require_lease(lease, "complete")
        if lease.resource_key != record.key:
            raise ValueError(
                "complete(): lease is for a different resource_key than the record"
            )
        stale = StaleLeaseError(
            resource_key=record.key,
            lease_holder=lease.lease_holder,
            operation="complete",
            unrecorded_credits=record.credits_spent,
        )
        if lease.action != "acquired_lease" or lease.lease_token is None:
            raise stale
        values = {
            AcquisitionLedgerRow.status: "complete",
            AcquisitionLedgerRow.content_hash: record.content_hash,
            AcquisitionLedgerRow.durable_object_ref: record.durable_object_ref,
            AcquisitionLedgerRow.payload_json: payload_json,
            AcquisitionLedgerRow.etag: record.etag,
            AcquisitionLedgerRow.last_modified: record.last_modified,
            AcquisitionLedgerRow.provenance_json: json.dumps(
                dict(record.provenance), sort_keys=True
            ),
            AcquisitionLedgerRow.credits_spent: (
                AcquisitionLedgerRow.credits_spent + record.credits_spent
            ),
            AcquisitionLedgerRow.retrieved_at: _as_utc(record.retrieved_at),
            AcquisitionLedgerRow.lease_holder: None,
            AcquisitionLedgerRow.lease_token: _new_lease_token(),
            AcquisitionLedgerRow.lease_expires_at: None,
            AcquisitionLedgerRow.next_retry_at: None,
        }
        last_error: OperationalError | None = None
        for _attempt in range(MAX_LEDGER_ATTEMPTS):
            try:
                self.session.expire_all()
                row = self._fenced(lease).with_for_update().first()
                if row is None:
                    self.session.rollback()
                    raise stale
                observed = row.consumers_json
                merged = json.dumps(
                    sorted(set(json.loads(observed or "[]")) | set(record.consumers))
                )
                # The result write depends ONLY on the fence. The consumer
                # merge rides along as a CASE, so a concurrent ``claim`` that
                # changed the list since our read keeps its value instead of
                # vetoing the paid result; ``_merge_consumers`` then adds ours.
                written = self._fenced(lease).update(
                    {
                        **values,
                        AcquisitionLedgerRow.consumers_json: case(
                            (AcquisitionLedgerRow.consumers_json == observed, merged),
                            else_=AcquisitionLedgerRow.consumers_json,
                        ),
                    },
                    synchronize_session=False,
                )
                if written != 1:
                    self.session.rollback()
                    raise stale
                self.session.commit()
                break
            except OperationalError as exc:
                # A transient lock timeout (SQLite ``database is locked``).
                # Nothing was committed; the fence is re-checked on retry.
                self.session.rollback()
                last_error = exc
        else:
            raise LedgerContentionError(
                resource_key=record.key,
                operation="complete",
                attempts=MAX_LEDGER_ATTEMPTS,
            ) from last_error
        self._merge_consumers(record.key, record.consumers)

    def _merge_consumers(self, resource_key: str, consumers: tuple[str, ...]) -> None:
        """Best-effort consumer bookkeeping after a committed result.

        Never raises: the paid result is already durable, and a lost race on
        this list must not surface as a failure of the acquisition.
        """
        wanted = set(consumers)
        if not wanted:
            return
        for _attempt in range(MAX_LEDGER_ATTEMPTS):
            try:
                self.session.expire_all()
                row = (
                    self.session.query(AcquisitionLedgerRow)
                    .filter(AcquisitionLedgerRow.resource_key == resource_key)
                    .first()
                )
                if row is None:
                    return
                observed = row.consumers_json
                current = set(json.loads(observed or "[]"))
                if wanted <= current:
                    self.session.rollback()
                    return
                swapped = (
                    self.session.query(AcquisitionLedgerRow)
                    .filter(
                        AcquisitionLedgerRow.resource_key == resource_key,
                        AcquisitionLedgerRow.consumers_json == observed,
                    )
                    .update(
                        {
                            AcquisitionLedgerRow.consumers_json: json.dumps(
                                sorted(current | wanted)
                            )
                        },
                        synchronize_session=False,
                    )
                )
                if swapped == 1:
                    self.session.commit()
                    return
                self.session.rollback()
            except Exception:  # noqa: BLE001 - bookkeeping must not fail the result
                self.session.rollback()
        logger.warning(
            "acquisition ledger: consumer list for %s not merged after %d attempts; "
            "the committed result is unaffected",
            resource_key,
            MAX_LEDGER_ATTEMPTS,
        )

    def fail(
        self,
        lease: ClaimResult,
        *,
        retry_after_seconds: int = 300,
        now: datetime | None = None,
    ) -> None:
        """Release ``lease`` as failed and open a retry window.

        Raises :class:`StaleLeaseError` (writing nothing) when ``lease`` is no
        longer the live lease: a stale worker's failure must not clear a live
        holder's lease or push back its retry window.
        """
        lease = _require_lease(lease, "fail")
        now = _utc_now(now)
        stale = StaleLeaseError(
            resource_key=lease.resource_key,
            lease_holder=lease.lease_holder,
            operation="fail",
        )
        if lease.action != "acquired_lease" or lease.lease_token is None:
            raise stale
        written = self._fenced(lease).update(
            {
                AcquisitionLedgerRow.status: "failed",
                AcquisitionLedgerRow.failure_count: (
                    AcquisitionLedgerRow.failure_count + 1
                ),
                AcquisitionLedgerRow.next_retry_at: now
                + timedelta(seconds=retry_after_seconds),
                AcquisitionLedgerRow.lease_holder: None,
                AcquisitionLedgerRow.lease_token: _new_lease_token(),
                AcquisitionLedgerRow.lease_expires_at: None,
            },
            synchronize_session=False,
        )
        if written != 1:
            self.session.rollback()
            raise stale
        self.session.commit()

    def metrics(self) -> dict[str, int]:
        rows = self.session.query(AcquisitionLedgerRow).all()
        return {
            "resources": len(rows),
            "completed": sum(r.status == "complete" for r in rows),
            "credits_spent": sum(r.credits_spent for r in rows),
            "failures": sum(r.failure_count for r in rows),
        }
