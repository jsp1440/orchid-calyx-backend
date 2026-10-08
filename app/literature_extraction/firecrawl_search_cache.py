"""Acquisition-ledger reuse for paid Firecrawl searches.

``FirecrawlProvider.search`` used to call the paid ``search`` endpoint on
every execution (two credits per call); the provider's ``_seen`` map is per
instance, so a repeat execution of the same acquisition gap -- a new lease, a
new process -- paid again. :class:`LedgerSearchCache` routes the call through
:class:`app.source_federation.acquisition_ledger.AcquisitionLedger`, keyed on
the normalized query and parameters:

* a completed row younger than the freshness window is returned with zero
  paid calls (and no budget reservation);
* concurrent executions coalesce on the ledger lease: one worker pays, the
  others wait (bounded by the lease) for its result;
* an older row is refreshed through the lease (``force_refresh``);
* a paid result that cannot be recorded, or an expired lease, is parked as
  ``review_required`` and never retried automatically.

The stored payload is the provider's search result list (URLs and
bibliographic metadata of candidate sources), not scientific evidence.
"""

from __future__ import annotations

import dataclasses
import json
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.source_federation.acquisition import AcquisitionRecord, AcquisitionRequest
from app.source_federation.acquisition_ledger import (
    REVIEW_REQUIRED,
    AcquisitionLedger,
    LedgerContentionError,
    PaidResultUnrecordedError,
    StaleLeaseError,
)
from app.source_federation.acquisition_ledger_schema import (
    LedgerSchemaUnavailableError,
)

from .firecrawl_provider import AcquisitionBlocked

SEARCH_ENDPOINT_URL = "https://api.firecrawl.dev/v2/search"
SEARCH_PROVIDER = "firecrawl_search"


def search_identity(payload: dict) -> str:
    """Normalized identity of one search request (whitespace-insensitive)."""
    if set(payload) != {"query", "limit"}:
        raise AcquisitionBlocked("UNBOUNDED_CREDIT_OPTIONS")
    return json.dumps(
        {
            "endpoint": "search/v2",
            "query": " ".join(str(payload["query"]).split()),
            "limit": payload["limit"],
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def search_request(payload: dict, *, consumer: str, force_refresh: bool = False):
    return AcquisitionRequest(
        url=SEARCH_ENDPOINT_URL,
        provider=SEARCH_PROVIDER,
        consumer_module=consumer,
        stable_identifier=search_identity(payload),
        force_refresh=force_refresh,
    )


class LedgerSearchCache:
    """Ledger-backed, freshness-bounded reuse of paid search results."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        *,
        freshness_seconds: int,
        worker_id: str = "firecrawl-search",
        consumer: str = "firecrawl-acquisition",
        poll_seconds: float = 0.5,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if type(freshness_seconds) is not int or freshness_seconds < 1:
            raise AcquisitionBlocked("INVALID_SEARCH_CACHE_WINDOW")
        self.session_factory = session_factory
        self.freshness = timedelta(seconds=freshness_seconds)
        self.worker_id = worker_id
        self.consumer = consumer
        self.poll_seconds = poll_seconds
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.sleep = sleep

    def fetch(
        self,
        payload: dict,
        perform: Callable[[], tuple[dict, int]],
        *,
        lease_seconds: int,
    ) -> tuple[str, dict]:
        """Return ``(status, data)``: ``cache_hit`` (0 paid) or ``fetched``.

        ``perform`` makes the paid call and returns ``(data, credits)``. It
        runs only on an acquired lease. Every refusal is
        :class:`AcquisitionBlocked` with no paid call.
        """
        session = self.session_factory()
        try:
            return self._fetch(
                AcquisitionLedger(session), payload, perform, lease_seconds
            )
        except LedgerSchemaUnavailableError:
            raise AcquisitionBlocked("ACQUISITION_LEDGER_UNAVAILABLE") from None
        except LedgerContentionError:
            raise AcquisitionBlocked("ACQUISITION_LEDGER_CONTENTION") from None
        finally:
            session.close()

    def _fresh(self, entry) -> bool:
        return (
            entry is not None
            and entry.status == "complete"
            and bool(entry.payload_json)
            and entry.retrieved_at is not None
            and entry.retrieved_at + self.freshness > self.clock()
        )

    def _fetch(self, ledger, payload, perform, lease_seconds):
        key = search_request(payload, consumer=self.consumer).key
        entry = ledger.lookup(key)
        if entry is not None and entry.status == REVIEW_REQUIRED:
            raise AcquisitionBlocked("SEARCH_REVIEW_REQUIRED")
        if self._fresh(entry):
            return "cache_hit", json.loads(entry.payload_json)
        stale = entry is not None and entry.status == "complete"
        request = search_request(payload, consumer=self.consumer, force_refresh=stale)
        claim = ledger.claim(
            request,
            worker_id=self.worker_id,
            lease_seconds=lease_seconds,
            now=self.clock(),
        )
        if claim.action == "cache_hit":
            cached = ledger.lookup(key)
            if cached is None or not cached.payload_json:
                raise AcquisitionBlocked("SEARCH_CACHE_PAYLOAD_MISSING")
            return "cache_hit", json.loads(cached.payload_json)
        if claim.action == "in_flight":
            return self._await_in_flight(ledger, key, lease_seconds)
        if claim.action == "retry_blocked":
            raise AcquisitionBlocked("SEARCH_RETRY_BLOCKED")
        if claim.action == REVIEW_REQUIRED:
            raise AcquisitionBlocked("SEARCH_REVIEW_REQUIRED")
        if claim.action != "acquired_lease":
            raise AcquisitionBlocked("SEARCH_LEDGER_REFUSED")

        try:
            ledger.assert_lease_live(claim, now=self.clock())
        except StaleLeaseError:
            # Lapsed before the call: nothing was paid; release it.
            self._fail_quietly(ledger, claim)
            raise AcquisitionBlocked("SEARCH_LEASE_SUPERSEDED") from None
        try:
            data, credits = perform()
        except Exception:
            self._fail_quietly(ledger, claim)
            raise

        def build():
            content = json.dumps(data, sort_keys=True)
            record = AcquisitionRecord.completed(
                request=request,
                content=content.encode("utf-8"),
                provenance={
                    "retrieval_method": "firecrawl_search",
                    "query": " ".join(str(payload["query"]).split()),
                    "limit": str(payload["limit"]),
                    "scientific_status": "candidate_source_discovery_only",
                },
                credits_spent=credits,
            )
            # Freshness is judged on this cache's clock, so stamp it with it.
            return dataclasses.replace(record, retrieved_at=self.clock()), content

        try:
            ledger.settle_paid_result(build, lease=claim, credits_spent=credits)
        except StaleLeaseError:
            raise AcquisitionBlocked("SEARCH_LEASE_SUPERSEDED") from None
        except PaidResultUnrecordedError:
            raise AcquisitionBlocked("SEARCH_RESULT_UNRECORDED") from None
        return "fetched", data

    def _fail_quietly(self, ledger, claim) -> None:
        try:
            ledger.fail(claim, now=self.clock())
        except StaleLeaseError:
            pass

    def _await_in_flight(self, ledger, key, lease_seconds):
        """Wait (bounded by the lease) for the paying worker's result."""
        give_up = time.monotonic() + lease_seconds
        while time.monotonic() < give_up:
            self.sleep(self.poll_seconds)
            entry = ledger.lookup(key)
            if entry is None:
                break
            if entry.status == "complete" and entry.payload_json:
                return "cache_hit", json.loads(entry.payload_json)
            if entry.status != "leased":
                break
        raise AcquisitionBlocked("SEARCH_IN_FLIGHT")
