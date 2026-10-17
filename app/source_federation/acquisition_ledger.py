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

Expired leases and operator review
----------------------------------

A lease is sized to outlive its paid call (see
:mod:`app.source_federation.deadline`): a live worker always settles it --
``complete``, ``fail`` or :meth:`~AcquisitionLedger.hold_for_review` -- before
it expires. An expired lease therefore means the holder died or could not
reach the ledger, and whether the provider billed the call is unknown. By
default (``on_expired_lease="review"``) ``claim`` does NOT hand such a lease
to another worker: it answers ``review_required`` (no lease, no provider
call) and leaves the row untouched, so the original holder can still
complete it. The same answer is given for a row in status
``review_required``, which :meth:`~AcquisitionLedger.hold_for_review` writes
when a paid call succeeded but its result could not be recorded. Neither is
ever retried automatically, and ``force_refresh`` does not override them.
Only :meth:`~AcquisitionLedger.release_for_retry`, an explicit and logged
operator action, re-opens the resource. ``on_expired_lease="takeover"``
restores automatic crash recovery for callers whose call is not paid.

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
never at request time. ``claim`` fails closed with
:class:`LedgerSchemaUnavailableError` -- no lease, so the caller makes zero
provider calls -- when:

* the read-only schema check (:mod:`.acquisition_ledger_schema`) finds a
  missing table or column, an incompatible type, or no valid NON-partial
  unique key on ``resource_key``. A PASS is cached per engine for
  ``SCHEMA_PASS_TTL_SECONDS``;
* inserting a new key, the unique key is re-checked inside the inserting
  transaction, so a key dropped after a cached PASS cannot admit a second
  paid lease;
* any other SQL error during the claim coincides with a failing uncached
  schema check (a column or table dropped after the PASS).
"""

from __future__ import annotations

import json
import logging
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import case
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session

from .acquisition import AcquisitionRecord, AcquisitionRequest
from .acquisition_ledger_schema import (
    MISSING_UNIQUE,
    LedgerSchemaUnavailableError,
    forget_verified_schema,
    require_ledger_schema,
    unique_key_present,
)
from .acquisition_models import AcquisitionLedgerRow

__all__ = [
    "EXPIRED_LEASE_REVIEW",
    "EXPIRED_LEASE_TAKEOVER",
    "MAX_LEDGER_ATTEMPTS",
    "REVIEW_REQUIRED",
    "AcquisitionLedger",
    "ClaimResult",
    "LedgerContentionError",
    "LedgerEntry",
    "LedgerSchemaUnavailableError",
    "PaidResultUnrecordedError",
    "StaleLeaseError",
]

logger = logging.getLogger(__name__)

#: Upper bound on optimistic retries inside one ledger call. Each retry means
#: another writer changed the row between our read and our conditional write;
#: three consecutive losses is contention, not a normal race, and fails closed.
MAX_LEDGER_ATTEMPTS = 3

#: Row status for a resource whose paid outcome is unknown or unrecorded.
REVIEW_REQUIRED = "review_required"
#: ``claim(on_expired_lease=...)`` policies; see the module docstring.
EXPIRED_LEASE_REVIEW = "review"
EXPIRED_LEASE_TAKEOVER = "takeover"
_EXPIRED_LEASE_POLICIES = frozenset({EXPIRED_LEASE_REVIEW, EXPIRED_LEASE_TAKEOVER})


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


class PaidResultUnrecordedError(RuntimeError):
    """A paid call succeeded but its result could not be recorded as complete.

    ``held_for_review`` says whether the row was durably moved to
    ``review_required``. When it was not (the ledger itself was unreachable)
    the lease is left to expire, and an expired lease also answers
    ``review_required``: either way no worker re-pays automatically.
    """

    def __init__(
        self, *, resource_key: str, credits_spent: int, held_for_review: bool
    ) -> None:
        self.resource_key = resource_key
        self.credits_spent = credits_spent
        self.held_for_review = held_for_review
        super().__init__(
            f"paid acquisition result for {resource_key} was not recorded "
            f"({credits_spent} credit(s)); held_for_review={held_for_review}; "
            "operator review required before any retry"
        )


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """Read-only view of one ledger row (see :meth:`AcquisitionLedger.lookup`)."""

    resource_key: str
    status: str
    payload_json: str | None
    provenance: dict
    retrieved_at: datetime | None
    lease_expires_at: datetime | None
    credits_spent: int


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
    # cache_hit | acquired_lease | in_flight | retry_blocked | review_required
    action: str
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
        on_expired_lease: str = EXPIRED_LEASE_REVIEW,
    ) -> ClaimResult:
        """Coalesce ``request`` onto the ledger; only ``acquired_lease`` may fetch.

        Raises :class:`LedgerSchemaUnavailableError` (no lease, nothing
        written) when the ledger table is missing or incompatible. An
        expired lease answers ``review_required`` unless ``on_expired_lease``
        is ``"takeover"`` (see the module docstring).
        """
        if on_expired_lease not in _EXPIRED_LEASE_POLICIES:
            raise ValueError(f"unknown on_expired_lease policy {on_expired_lease!r}")
        require_ledger_schema(self.session)
        now = _utc_now(now)
        for _attempt in range(MAX_LEDGER_ATTEMPTS):
            try:
                result = self._try_claim(
                    request,
                    worker_id=worker_id,
                    lease_seconds=lease_seconds,
                    now=now,
                    on_expired_lease=on_expired_lease,
                )
            except LedgerSchemaUnavailableError:
                raise
            except SQLAlchemyError as exc:
                self._raise_if_schema_unavailable(exc)
                raise
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
        on_expired_lease: str = EXPIRED_LEASE_REVIEW,
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
            # Coalescing a new key rests entirely on the unique key: without it
            # a concurrent worker's insert also succeeds and both pay. So it is
            # re-checked here, in the inserting transaction, not only through
            # the (time-bounded) cached schema PASS. On PostgreSQL the SELECT
            # above already holds a lock on the table, so the key cannot be
            # dropped between this check and our commit.
            if not unique_key_present(self.session.connection()):
                self.session.rollback()
                forget_verified_schema(self.session)
                raise LedgerSchemaUnavailableError((MISSING_UNIQUE,))
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

        if row.status == REVIEW_REQUIRED:
            # Paid outcome unrecorded: never retried automatically, and not
            # overridable by force_refresh (see release_for_retry).
            row.consumers_json = consumers_json
            self.session.commit()
            return ClaimResult(REVIEW_REQUIRED, row.id, request.key)
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
        if row.status == "leased" and on_expired_lease == EXPIRED_LEASE_REVIEW:
            # Expired without being settled: the holder died or lost the
            # ledger mid-call, so the call may have been billed. Read-only
            # verdict; the row (and the holder's token) stay as they are.
            row.consumers_json = consumers_json
            self.session.commit()
            return ClaimResult(REVIEW_REQUIRED, row.id, request.key)

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

    def _raise_if_schema_unavailable(self, exc: SQLAlchemyError) -> None:
        """Re-raise a claim-time SQL error as typed when the schema is the cause.

        A column or table dropped after the cached PASS surfaces as an
        untyped ``ProgrammingError``/``OperationalError``. Re-run the full
        check uncached; if it finds a problem, raise
        :class:`LedgerSchemaUnavailableError` (no lease, no provider call).
        Otherwise return and let the caller re-raise the original error.
        """
        self.session.rollback()
        forget_verified_schema(self.session)
        try:
            require_ledger_schema(self.session, use_cache=False)
        except LedgerSchemaUnavailableError as schema_error:
            raise schema_error from exc

    def lookup(self, resource_key: str) -> LedgerEntry | None:
        """Read-only view of the row for ``resource_key`` (``None`` if absent).

        Fails closed like ``claim``: :class:`LedgerSchemaUnavailableError`
        when the table is missing or incompatible.
        """
        require_ledger_schema(self.session)
        self.session.expire_all()
        try:
            row = (
                self.session.query(AcquisitionLedgerRow)
                .filter(AcquisitionLedgerRow.resource_key == resource_key)
                .first()
            )
        except SQLAlchemyError as exc:
            self._raise_if_schema_unavailable(exc)
            raise
        if row is None:
            self.session.rollback()
            return None
        try:
            provenance = json.loads(row.provenance_json or "{}")
        except ValueError:
            provenance = {}
        entry = LedgerEntry(
            resource_key=row.resource_key,
            status=row.status,
            payload_json=row.payload_json,
            provenance=provenance if isinstance(provenance, dict) else {},
            retrieved_at=_as_utc(row.retrieved_at),
            lease_expires_at=_as_utc(row.lease_expires_at),
            credits_spent=row.credits_spent,
        )
        self.session.rollback()
        return entry

    def assert_lease_live(self, lease: ClaimResult, *, now: datetime | None = None):
        """Raise :class:`StaleLeaseError` unless ``lease`` is live and unexpired.

        Called immediately before a paid call: a lease that expired while
        the worker was preparing must not be spent.
        """
        lease = _require_lease(lease, "assert_lease_live")
        now = _utc_now(now)
        stale = StaleLeaseError(
            resource_key=lease.resource_key,
            lease_holder=lease.lease_holder,
            operation="assert_lease_live",
        )
        if lease.action != "acquired_lease" or lease.lease_token is None:
            raise stale
        self.session.expire_all()
        row = self._fenced(lease).first()
        expires = _as_utc(row.lease_expires_at) if row is not None else None
        self.session.rollback()
        if row is None or expires is None or expires <= now:
            raise stale

    def hold_for_review(
        self,
        lease: ClaimResult,
        *,
        credits_spent: int,
        reason: str,
        now: datetime | None = None,
    ) -> None:
        """Park ``lease``'s resource as ``review_required`` after a paid call.

        For a paid call whose result cannot be recorded: the credit is
        counted, the lease is released, and no worker (including a
        ``force_refresh`` one) re-pays until an operator calls
        :meth:`release_for_retry`. Raises :class:`StaleLeaseError` (writing
        nothing) when ``lease`` is no longer live.
        """
        lease = _require_lease(lease, "hold_for_review")
        now = _utc_now(now)
        stale = StaleLeaseError(
            resource_key=lease.resource_key,
            lease_holder=lease.lease_holder,
            operation="hold_for_review",
            unrecorded_credits=credits_spent,
        )
        if lease.action != "acquired_lease" or lease.lease_token is None:
            raise stale
        self.session.expire_all()
        row = self._fenced(lease).first()
        if row is None:
            self.session.rollback()
            raise stale
        provenance = _provenance_dict(row.provenance_json)
        provenance.update(
            review_reason=str(reason)[:200],
            review_held_at=now.isoformat(),
            review_unrecorded_credits=str(credits_spent),
            review_lease_holder=str(lease.lease_holder),
        )
        written = self._fenced(lease).update(
            {
                AcquisitionLedgerRow.status: REVIEW_REQUIRED,
                AcquisitionLedgerRow.credits_spent: (
                    AcquisitionLedgerRow.credits_spent + credits_spent
                ),
                AcquisitionLedgerRow.provenance_json: json.dumps(
                    provenance, sort_keys=True
                ),
                AcquisitionLedgerRow.lease_holder: None,
                AcquisitionLedgerRow.lease_token: _new_lease_token(),
                AcquisitionLedgerRow.lease_expires_at: None,
                AcquisitionLedgerRow.next_retry_at: None,
            },
            synchronize_session=False,
        )
        if written != 1:
            self.session.rollback()
            raise stale
        self.session.commit()
        logger.error(
            "acquisition ledger: %s held for operator review after a paid call "
            "(credits=%d, reason=%s); it will not be retried automatically",
            lease.resource_key,
            credits_spent,
            reason,
        )

    def settle_paid_result(
        self,
        build: Callable[[], tuple[AcquisitionRecord, str | None]],
        *,
        lease: ClaimResult,
        credits_spent: int,
    ) -> AcquisitionRecord:
        """Record a SUCCESSFUL paid call's result on ``lease``, failing closed.

        ``build`` returns ``(record, payload_json)``. :class:`StaleLeaseError`
        propagates (the live holder owns the row). Any other failure -- the
        record cannot be built, or the ledger write fails -- never reaches
        ``fail()`` (which would invite a re-pay after the retry window): the
        row is moved to ``review_required`` if the ledger is reachable, and
        :class:`PaidResultUnrecordedError` is raised either way.
        """
        try:
            record, payload_json = build()
            self.complete(record, lease=lease, payload_json=payload_json)
            return record
        except StaleLeaseError:
            raise
        except Exception as exc:
            self.session.rollback()
            held = False
            try:
                self.hold_for_review(
                    lease,
                    credits_spent=credits_spent,
                    reason="result_not_recorded:" + type(exc).__name__,
                )
                held = True
            except Exception:  # noqa: BLE001 - lease left to expire -> review
                self.session.rollback()
            raise PaidResultUnrecordedError(
                resource_key=lease.resource_key,
                credits_spent=credits_spent,
                held_for_review=held,
            ) from exc

    def release_for_retry(
        self,
        resource_key: str,
        *,
        operator_id: str,
        reason: str,
        now: datetime | None = None,
    ) -> bool:
        """Operator action: re-open a ``review_required`` or expired-lease row.

        Explicit and logged. The row becomes ``failed`` with an immediate
        retry window, so the next claim (and only one: the takeover is a
        compare-and-swap) may pay again. Returns ``False`` when the row is
        not in a reviewable state (absent, complete, failed, or a live
        lease). The credits already counted are kept.
        """
        operator_id = (operator_id or "").strip()
        reason = (reason or "").strip()
        if not operator_id or not reason:
            raise ValueError("release_for_retry requires operator_id and reason")
        now = _utc_now(now)
        self.session.expire_all()
        row = (
            self.session.query(AcquisitionLedgerRow)
            .filter(AcquisitionLedgerRow.resource_key == resource_key)
            .with_for_update()
            .first()
        )
        if row is None:
            self.session.rollback()
            return False
        expires = _as_utc(row.lease_expires_at)
        reviewable = row.status == REVIEW_REQUIRED or (
            row.status == "leased" and (expires is None or expires <= now)
        )
        if not reviewable:
            self.session.rollback()
            return False
        observed_token = row.lease_token
        provenance = _provenance_dict(row.provenance_json)
        provenance.update(
            released_by=operator_id[:160],
            release_reason=reason[:200],
            released_at=now.isoformat(),
            released_from=row.status,
        )
        written = (
            self.session.query(AcquisitionLedgerRow)
            .filter(
                AcquisitionLedgerRow.id == row.id,
                (
                    AcquisitionLedgerRow.lease_token.is_(None)
                    if observed_token is None
                    else AcquisitionLedgerRow.lease_token == observed_token
                ),
            )
            .update(
                {
                    AcquisitionLedgerRow.status: "failed",
                    AcquisitionLedgerRow.next_retry_at: now,
                    AcquisitionLedgerRow.lease_holder: None,
                    AcquisitionLedgerRow.lease_token: _new_lease_token(),
                    AcquisitionLedgerRow.lease_expires_at: None,
                    AcquisitionLedgerRow.provenance_json: json.dumps(
                        provenance, sort_keys=True
                    ),
                },
                synchronize_session=False,
            )
        )
        if written != 1:
            self.session.rollback()
            return False
        self.session.commit()
        logger.warning(
            "acquisition ledger: operator %s released %s for retry (reason=%s)",
            operator_id,
            resource_key,
            reason,
        )
        return True

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

    def metrics(self, *, now: datetime | None = None) -> dict[str, int]:
        now = _utc_now(now)
        rows = self.session.query(AcquisitionLedgerRow).all()

        def needs_review(row) -> bool:
            if row.status == REVIEW_REQUIRED:
                return True
            expires = _as_utc(row.lease_expires_at)
            return row.status == "leased" and (expires is None or expires <= now)

        return {
            "resources": len(rows),
            "completed": sum(r.status == "complete" for r in rows),
            "credits_spent": sum(r.credits_spent for r in rows),
            "failures": sum(r.failure_count for r in rows),
            "review_required": sum(needs_review(r) for r in rows),
        }


def _provenance_dict(raw: str | None) -> dict:
    try:
        value = json.loads(raw or "{}")
    except ValueError:
        return {}
    return dict(value) if isinstance(value, dict) else {}
