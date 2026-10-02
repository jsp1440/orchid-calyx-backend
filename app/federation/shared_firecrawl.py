"""Cache-first wrapper for Firecrawl federation reconnaissance.

All module consumers should use this service instead of invoking
FirecrawlFederationMapper directly. The ledger coalesces duplicate requests,
blocks retry storms, and records Firecrawl credit usage/provenance.

Resource identity and coverage
------------------------------

The ledger key is the canonical RESOURCE: the canonical root URL, the
``search`` scope and ``include_subdomains``. ``limit`` and ``sitemap`` are
request parameters, not identity, so varying them cannot buy a second map of
a site that is already mapped. They are recorded on the completed row
(provenance ``map_limit`` / ``map_sitemap``) and a stored result is reused,
at zero cost, whenever it COVERS the request:

* same ``sitemap`` mode (``include``, ``only`` and ``skip`` return different
  URL sets, and a stored result cannot be split by origin), and
* stored ``limit`` >= requested ``limit``.

A request the stored result does not cover is answered
``coverage_insufficient`` with no paid call. Paying for it requires an
explicit ``operator_override`` (an operator identity, logged), and even then
the call goes through the ledger lease (``force_refresh``) and REPLACES the
stored result for the resource. Example, one resource, in order::

    limit=50                         -> fetched                (1 paid)
    limit=51                         -> coverage_insufficient  (0 paid)
    limit=50, sitemap=skip           -> coverage_insufficient  (0 paid)
    limit=50                         -> cache_hit              (0 paid)

    total without an override: 1 paid call. With an override on the second
    request only: 2 paid calls, and the final limit=50 request is a cache
    hit because the stored limit=51 result covers it.

Rows written before this keying (identity included ``limit``/``sitemap``) are
still read, for the exact parameters that wrote them, so an upgrade does not
re-pay for them.

Wall-clock bound
----------------

``FirecrawlFederationMapper`` bounds its whole HTTP exchange with
:func:`app.source_federation.deadline.call_with_deadline` at its declared
``total_timeout_seconds``; the lease here is derived from that value (or the
module default for a mapper that declares none) plus a margin, so the worker
settles the lease -- ``complete``, ``fail`` or ``hold_for_review`` -- while it
is still live. If a call nevertheless outlives the lease (a mapper without a
real deadline, a stalled process), the ledger's default expired-lease policy
answers ``review_required`` to every other worker instead of handing the
lease over, so the resource is still paid for at most once; the original
worker can still complete it.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.source_federation.acquisition import (
    AcquisitionRecord,
    AcquisitionRequest,
    canonicalize_url,
)
from app.source_federation.acquisition_ledger import (
    REVIEW_REQUIRED,
    AcquisitionLedger,
    LedgerEntry,
    PaidResultUnrecordedError,
    StaleLeaseError,
)
from app.source_federation.deadline import lease_seconds_for, validate_deadline

from .firecrawl_mapper import (
    DEFAULT_TOTAL_TIMEOUT_SECONDS,
    FederationSourceProfile,
    FirecrawlFederationMapper,
)

logger = logging.getLogger(__name__)

#: Statuses ``map_source`` can return with a profile.
PROFILE_STATUSES = frozenset({"fetched", "cache_hit"})
COVERAGE_INSUFFICIENT = "coverage_insufficient"


def profile_from_payload(payload_json: str) -> FederationSourceProfile:
    """Rebuild a profile from the ledger's cached ``payload_json``."""
    data = json.loads(payload_json)
    return FederationSourceProfile(
        **{
            **data,
            "urls": tuple(data["urls"]),
            "url_classes": {
                key: tuple(value) for key, value in data["url_classes"].items()
            },
            "candidate_identifiers": {
                key: tuple(value)
                for key, value in data["candidate_identifiers"].items()
            },
            "api_download_hints": tuple(data["api_download_hints"]),
            "terms_license_hints": tuple(data["terms_license_hints"]),
        }
    )


def covers(entry: LedgerEntry, *, limit: int, sitemap: str) -> bool:
    """Whether a COMPLETE row's stored map answers ``limit``/``sitemap``.

    Rows without recorded parameters (written before they were recorded)
    cover nothing: absence of a recorded limit is not evidence of coverage.
    """
    if entry.status != "complete" or not entry.payload_json:
        return False
    stored_sitemap = entry.provenance.get("map_sitemap")
    try:
        stored_limit = int(entry.provenance.get("map_limit", ""))
    except (TypeError, ValueError):
        return False
    return stored_sitemap == sitemap and stored_limit >= limit


def mapper_deadline(mapper: object) -> float:
    """The mapper's declared wall-clock bound, or the default (validated)."""
    declared = getattr(mapper, "total_timeout_seconds", None)
    if isinstance(declared, bool) or not isinstance(declared, (int, float)):
        declared = DEFAULT_TOTAL_TIMEOUT_SECONDS
    return validate_deadline(declared)


class SharedFirecrawlFederationService:
    def __init__(
        self,
        session: Session,
        *,
        mapper: FirecrawlFederationMapper | None = None,
        worker_id: str = "firecrawl-federation",
        lease_margin_seconds: int | None = None,
    ) -> None:
        self.ledger = AcquisitionLedger(session)
        self.mapper = mapper or FirecrawlFederationMapper()
        self.worker_id = worker_id
        self.call_deadline_seconds = mapper_deadline(self.mapper)
        self.lease_seconds = (
            lease_seconds_for(self.call_deadline_seconds)
            if lease_margin_seconds is None
            else lease_seconds_for(
                self.call_deadline_seconds, margin_seconds=lease_margin_seconds
            )
        )

    def cached_profile(
        self,
        *,
        root_url: str,
        search: str | None = None,
        limit: int = 100,
        sitemap: str = "include",
        include_subdomains: bool = False,
    ) -> tuple[str, FederationSourceProfile | None, str]:
        """Answer from the ledger alone: ``(status, profile, resource_key)``.

        ``status`` is ``cache_hit`` (a covering stored result, or a legacy
        row for these exact parameters), ``coverage_insufficient`` (a stored
        result that does not cover the request), ``review_required``, or
        ``miss`` (nothing stored). Never pays, never claims.
        """
        request = self.acquisition_request(
            consumer_module="lookup",
            root_url=root_url,
            search=search,
            include_subdomains=include_subdomains,
        )
        entry = self.ledger.lookup(request.key)
        if entry is not None:
            if entry.status == REVIEW_REQUIRED:
                return REVIEW_REQUIRED, None, request.key
            if entry.status == "complete":
                if covers(entry, limit=limit, sitemap=sitemap):
                    return (
                        "cache_hit",
                        profile_from_payload(entry.payload_json),
                        request.key,
                    )
                return COVERAGE_INSUFFICIENT, None, request.key
        legacy = self.ledger.cached_payload(
            self.legacy_acquisition_request(
                consumer_module="lookup",
                root_url=root_url,
                search=search,
                limit=limit,
                sitemap=sitemap,
                include_subdomains=include_subdomains,
            ).key
        )
        if legacy:
            return "cache_hit", profile_from_payload(legacy), request.key
        return "miss", None, request.key

    def map_source(
        self,
        *,
        consumer_module: str,
        source_id: str,
        root_url: str,
        search: str | None = None,
        limit: int = 100,
        sitemap: str = "include",
        include_subdomains: bool = False,
        force_refresh: bool = False,
        operator_override: str | None = None,
        before_paid_call: Callable[[], None] | None = None,
    ) -> tuple[str, FederationSourceProfile | None]:
        """Map ``root_url`` at most once per resource; see the module docstring.

        ``force_refresh`` re-maps a covered resource and, like any request
        the stored result does not cover, requires ``operator_override``.
        ``before_paid_call`` runs on the acquired lease immediately before
        the paid call (budget reservation); if it raises, no call is made.
        """
        override = (operator_override or "").strip() or None
        if force_refresh and override is None:
            return "override_required", None
        status, profile, _key = self.cached_profile(
            root_url=root_url,
            search=search,
            limit=limit,
            sitemap=sitemap,
            include_subdomains=include_subdomains,
        )
        if status == REVIEW_REQUIRED:
            return REVIEW_REQUIRED, None
        if status == "cache_hit" and not force_refresh:
            self._record_consumer(consumer_module, root_url, search, include_subdomains)
            return "cache_hit", profile
        refresh = status in {"cache_hit", COVERAGE_INSUFFICIENT}
        if status == COVERAGE_INSUFFICIENT and override is None:
            return COVERAGE_INSUFFICIENT, None
        if refresh:
            logger.warning(
                "firecrawl map operator override: operator=%s consumer=%s "
                "root_url=%s limit=%d sitemap=%s force_refresh=%s",
                override,
                consumer_module,
                root_url,
                limit,
                sitemap,
                force_refresh,
            )
        request = self.acquisition_request(
            consumer_module=consumer_module,
            root_url=root_url,
            search=search,
            include_subdomains=include_subdomains,
            force_refresh=refresh,
        )
        claim = self.ledger.claim(
            request, worker_id=self.worker_id, lease_seconds=self.lease_seconds
        )
        if claim.action == "cache_hit":
            # Completed by another worker between our read and our claim.
            entry = self.ledger.lookup(request.key)
            if entry is not None and covers(entry, limit=limit, sitemap=sitemap):
                return "cache_hit", profile_from_payload(entry.payload_json)
            return COVERAGE_INSUFFICIENT, None
        if claim.action != "acquired_lease":
            return claim.action, None

        try:
            self.ledger.assert_lease_live(claim)
            if before_paid_call is not None:
                before_paid_call()
        except StaleLeaseError:
            # The lease lapsed before the call: nothing was paid, so release
            # it (a no-op if it was superseded) rather than park it.
            self._fail_quietly(claim)
            return "stale_lease", None
        except Exception:
            # Nothing was paid: release the lease as an ordinary failure.
            self._fail_quietly(claim)
            raise

        try:
            profile = self.mapper.map_source(
                source_id=source_id,
                root_url=root_url,
                search=search,
                limit=limit,
                sitemap=sitemap,
                include_subdomains=include_subdomains,
            )
        except Exception:
            # Only a failed provider call is a failure (including a call that
            # hit its deadline, settled here while the lease is still live).
            # Nothing after a successful (paid) call may reach ``fail()``.
            self._fail_quietly(claim)
            raise
        # Firecrawl Map is one credit per successful call under the current
        # operational contract. Keep accounting explicit here.
        credits_spent = 1

        def build():
            payload = json.dumps(profile.to_dict(), sort_keys=True).encode("utf-8")
            record = AcquisitionRecord.completed(
                request=request,
                content=payload,
                provenance={
                    "retrieval_method": "firecrawl_map",
                    "source_id": source_id,
                    "root_url": root_url,
                    "scientific_status": "reconnaissance_only",
                    "map_limit": str(limit),
                    "map_sitemap": sitemap,
                    "operator_override": override or "",
                },
                credits_spent=credits_spent,
            )
            return record, payload.decode("utf-8")

        try:
            self.ledger.settle_paid_result(
                build, lease=claim, credits_spent=credits_spent
            )
        except StaleLeaseError as exc:
            # Fail closed: our lease was superseded while the call ran, so the
            # live holder's result owns the cache. This late result is not
            # persisted and is not handed on without ledger provenance, but
            # the credit it cost is reported rather than lost silently.
            logger.warning(
                "firecrawl acquisition superseded: resource_key=%s worker=%s "
                "consumer=%s unrecorded_credits=%d",
                exc.resource_key,
                exc.lease_holder,
                consumer_module,
                exc.unrecorded_credits,
            )
            return "stale_lease", None
        except PaidResultUnrecordedError as exc:
            logger.error(
                "firecrawl acquisition result not recorded: resource_key=%s "
                "worker=%s consumer=%s unrecorded_credits=%d held_for_review=%s",
                request.key,
                self.worker_id,
                consumer_module,
                credits_spent,
                exc.held_for_review,
            )
            raise
        return "fetched", profile

    def _fail_quietly(self, claim) -> None:
        try:
            self.ledger.fail(claim)
        except StaleLeaseError:
            # Superseded while the call ran: the row belongs to the live
            # holder and must not be touched. The original error is still
            # what the caller sees.
            pass

    def _record_consumer(self, consumer_module, root_url, search, subdomains):
        """Consumer bookkeeping on a zero-cost ledger read (best effort)."""
        request = self.acquisition_request(
            consumer_module=consumer_module,
            root_url=root_url,
            search=search,
            include_subdomains=subdomains,
        )
        try:
            self.ledger._merge_consumers(request.key, (consumer_module,))
        except Exception:  # noqa: BLE001 - bookkeeping only
            self.ledger.session.rollback()

    @classmethod
    def acquisition_request(
        cls,
        *,
        consumer_module: str,
        root_url: str,
        search: str | None = None,
        include_subdomains: bool = False,
        force_refresh: bool = False,
        **_request_parameters,
    ) -> AcquisitionRequest:
        """The ledger request (and so the ``resource_key``) ``map_source`` uses.

        Request parameters (``limit``, ``sitemap``) are accepted and ignored:
        they are not part of the resource identity.
        """
        return AcquisitionRequest(
            url=root_url,
            provider="firecrawl_map",
            consumer_module=consumer_module,
            stable_identifier=cls._resource_identity(
                root_url=root_url,
                search=search,
                include_subdomains=include_subdomains,
            ),
            force_refresh=force_refresh,
        )

    @staticmethod
    def _resource_identity(
        *, root_url: str, search: str | None, include_subdomains: bool
    ) -> str:
        return json.dumps(
            {
                "resource": "firecrawl_map/v2",
                "url": canonicalize_url(root_url),
                "search": search,
                "include_subdomains": include_subdomains,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @classmethod
    def legacy_acquisition_request(
        cls,
        *,
        consumer_module: str,
        root_url: str,
        search: str | None,
        limit: int,
        sitemap: str,
        include_subdomains: bool,
    ) -> AcquisitionRequest:
        """The pre-coverage key (identity included ``limit``/``sitemap``); read-only."""
        return AcquisitionRequest(
            url=root_url,
            provider="firecrawl_map",
            consumer_module=consumer_module,
            stable_identifier=cls._request_identity(
                root_url=root_url,
                search=search,
                limit=limit,
                sitemap=sitemap,
                include_subdomains=include_subdomains,
            ),
        )

    @staticmethod
    def _request_identity(
        *,
        root_url: str,
        search: str | None,
        limit: int,
        sitemap: str,
        include_subdomains: bool,
    ) -> str:
        """Legacy identity; used only to read rows written before coverage keying."""
        return json.dumps(
            {
                "url": canonicalize_url(root_url),
                "search": search,
                "limit": limit,
                "sitemap": sitemap,
                "include_subdomains": include_subdomains,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
