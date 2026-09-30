"""Ledger-routed Firecrawl federation reconnaissance pilot.

The owner rule this module enforces: never spend Firecrawl (or any paid)
credits on material Orchid Continuum already holds. For every pilot source, in
this order and before any paid call:

1. **Ledger schema** -- :func:`require_ledger_schema`. A missing or
   incompatible ``acquisition_ledger`` aborts the whole run with zero provider
   calls. There is no fallback to a direct mapper call and no bypass flag.
2. **Prior acquisition records** -- a completed ledger row for the same
   canonical resource is returned read-only when it covers the requested
   ``limit``/``sitemap`` (no claim, no paid call); one that does not cover
   it is ``coverage_insufficient`` (no paid call) unless an explicit, logged
   ``operator_override`` is given. A resource parked for operator review is
   ``review_required``.
3. **Provider gate** -- :func:`app.literature_extraction.firecrawl_provider.live_gate`,
   the SAME function ``FirecrawlProvider._gate`` calls (not a copy):
   ``FIRECRAWL_ENABLED=true``, ``FIRECRAWL_DRY_RUN=false``, the kill switch
   exactly ``false``, ``PROVIDER_AUTHORIZED=true``, ``NO_API_MODE`` exactly
   ``false``, ``FIRECRAWL_API_KEY``, and the durable budget authority
   (governor, USD + daily-credit reservation, usage observation, positive
   budgets). A blocked gate takes no lease.
4. **Existing holdings** -- the corpus and the source registry's document
   inventory, through the existing read-only corpus audit and the existing
   DOI/URL/content-hash/bibliography matcher. Holdings that cannot be verified
   block the source (no lease); a held match is reused (no lease).
5. **Ledger claim** -- :class:`SharedFirecrawlFederationService`: the mapper
   runs only for ``acquired_lease``; ``in_flight``/``retry_blocked`` make no
   paid call; the result is completed (or failed) on the fenced lease.
6. **Budget reservation** -- on the acquired lease, immediately before the
   paid call, :func:`~app.literature_extraction.firecrawl_provider.reserve_live_attempt`
   (the provider's own reservation) durably reserves the call's credit and
   USD cost. A refused reservation makes no call.

Output is reconnaissance only; nothing here writes scientific stores.
"""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.literature_extraction.firecrawl_provider import (
    AcquisitionBlocked,
    FirecrawlConfig,
    live_gate,
    reserve_live_attempt,
)
from app.source_federation.acquisition_ledger import (
    REVIEW_REQUIRED,
    LedgerContentionError,
    PaidResultUnrecordedError,
)
from app.source_federation.acquisition_ledger_schema import (
    LedgerSchemaUnavailableError,
    require_ledger_schema,
)

from .shared_firecrawl import COVERAGE_INSUFFICIENT, SharedFirecrawlFederationService

logger = logging.getLogger(__name__)

PILOT_ID = "firecrawl-federation-phragmipedium-v1"
PILOT_CONSUMER = "federation-pilot"
PILOT_WORKER = "firecrawl-federation-pilot"

#: Statuses in which the source is answered without any further paid call.
RESOLVED = frozenset({"fetched", "cache_hit", "already_held"})

#: Firecrawl Map: one credit per successful call (the operational contract
#: ``SharedFirecrawlFederationService`` records).
MAP_CREDIT_COST = 1

_GENUS = re.compile(r"[A-Z][a-z]{2,40}")


@dataclass(frozen=True)
class SpendAuthority:
    """The durable budget authority a live call needs (as for the provider).

    Production composition: ``SwarmExecutionGovernor`` plus
    ``PostgresFirecrawlReservation`` (``reserve``, ``reserve_credits``,
    ``observe_credits``).
    """

    governor: Any
    reserve: Callable
    reserve_credits: Callable
    observe_credits: Callable


def load_config(env: Mapping[str, str]) -> FirecrawlConfig:
    """``FirecrawlConfig.from_env``; an unparsable value blocks (fail closed)."""
    try:
        return FirecrawlConfig.from_env(env)
    except AcquisitionBlocked:
        raise
    except (ArithmeticError, TypeError, ValueError):
        raise AcquisitionBlocked("INVALID_CONFIG") from None


def provider_gate(
    env: Mapping[str, str],
    *,
    authority: SpendAuthority | None = None,
    lease_check: Callable | None = None,
) -> str | None:
    """Return why a paid Firecrawl call is not allowed, or ``None``.

    Delegates to :func:`live_gate` -- the function ``FirecrawlProvider._gate``
    calls -- with no fixture transport, so the pilot is admitted exactly
    when a live provider call would be. ``lease_check`` is the ledger's own
    pre-call lease check.
    """
    try:
        live_gate(
            load_config(env),
            env,
            fixture_transport=None,
            governor=authority.governor if authority else None,
            reserve=authority.reserve if authority else None,
            reserve_credits=authority.reserve_credits if authority else None,
            observe_credits=authority.observe_credits if authority else None,
            lease_check=lease_check,
        )
    except AcquisitionBlocked as exc:
        return str(exc)
    return None


@dataclass(frozen=True)
class HoldingsCheck:
    """Result of searching existing stores for one resource.

    ``available`` is False when the stores could not be fully searched; the
    caller must then make no paid call (absence of a match proves nothing).
    """

    available: bool
    matches: tuple[dict[str, Any], ...] = ()
    stores_checked: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()


HoldingsLookup = Callable[..., HoldingsCheck]

# Blockers from ``audit_existing_corpus`` that mean its identity list is not
# the whole corpus (as opposed to relevance/reuse findings about it).
_AUDIT_INCOMPLETE = (
    "CORE_RELATION_ABSENT:",
    "CORPUS_ROW_BOUND:",
    "CORPUS_AUDIT_UNAVAILABLE:",
)
_MATCH_FIELDS = (
    "doi",
    "title",
    "year",
    "source_url",
    "content_hash",
    "registry_id",
    "revision_id",
    "relation",
)


class CorpusHoldings:
    """Existing-holdings lookup over the corpus and the source registry.

    Uses :func:`app.literature_extraction.corpus_audit.audit_existing_corpus`
    (``oc_import.document_revisions``, ``oc_sources.document_inventory`` and
    the legacy document relations) and matches the resource's root URL with
    :func:`app.literature_extraction.firecrawl_acquisition.held_source_match`.
    """

    def __init__(self, connect: Callable, *, audit: Callable | None = None) -> None:
        self.connect = connect
        self._audit = audit

    def __call__(self, *, root_url: str, search: str | None) -> HoldingsCheck:
        if not search or not _GENUS.fullmatch(search):
            # The corpus audit is genus-scoped; an unscoped map cannot be
            # checked, so it is not allowed to pay.
            return HoldingsCheck(False, blockers=("HOLDINGS_SCOPE_UNSUPPORTED",))
        audit = self._audit
        if audit is None:
            from app.literature_extraction.corpus_audit import audit_existing_corpus

            audit = audit_existing_corpus
        try:
            report = audit(self.connect, genus=search)
        except Exception as exc:  # noqa: BLE001 - unverifiable holdings block
            return HoldingsCheck(
                False, blockers=("CORPUS_AUDIT_UNAVAILABLE:" + type(exc).__name__,)
            )
        stores = tuple(
            sorted(
                name
                for name, relation in (report.get("relations") or {}).items()
                if isinstance(relation, Mapping)
                and relation.get("state") == "available"
            )
        )
        incomplete = tuple(
            blocker
            for blocker in report.get("blockers") or ()
            if str(blocker).startswith(_AUDIT_INCOMPLETE)
        )
        if (
            not report.get("available")
            or not report.get("audit_complete")
            or incomplete
        ):
            return HoldingsCheck(
                False,
                stores_checked=stores,
                blockers=incomplete or ("CORPUS_AUDIT_INCOMPLETE",),
            )
        from app.literature_extraction.firecrawl_acquisition import held_source_match

        candidate = {"source_url": root_url}
        matches = tuple(
            {key: identity[key] for key in _MATCH_FIELDS if identity.get(key)}
            for identity in report.get("identities") or ()
            if isinstance(identity, Mapping)
            and held_source_match(candidate, [identity])
        )
        return HoldingsCheck(True, matches=matches, stores_checked=stores)


class _CountingMapper:
    """Counts every provider invocation, so the report states paid attempts."""

    def __init__(self, mapper) -> None:
        self._mapper = mapper
        self._lock = threading.Lock()
        self.calls = 0

    @property
    def total_timeout_seconds(self):
        return getattr(self._mapper, "total_timeout_seconds", None)

    def map_source(self, **kwargs):
        with self._lock:
            self.calls += 1
        return self._mapper.map_source(**kwargs)


@dataclass
class PilotReport:
    status: str = "completed"
    reason: str | None = None
    problems: tuple[str, ...] = ()
    profiles: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    provider_calls: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "pilot": PILOT_ID,
            "status": self.status,
            "reason": self.reason,
            "ledger_problems": list(self.problems),
            "scientific_status": "reconnaissance_only",
            "automatic_publication_allowed": False,
            "provider_calls": self.provider_calls,
            "sources": self.sources,
            "profiles": self.profiles,
        }

    @property
    def resolved(self) -> bool:
        return self.status == "completed" and all(
            entry["status"] in RESOLVED for entry in self.sources
        )


def run_pilot(
    *,
    session: Session,
    sources: Mapping[str, Mapping[str, str]],
    mapper,
    holdings: HoldingsLookup,
    env: Mapping[str, str],
    limit: int = 50,
    sitemap: str = "include",
    authority: SpendAuthority | None = None,
    operator_override: str | None = None,
) -> PilotReport:
    """Map each source at most once across all runs; see the module docstring."""
    report = PilotReport()
    try:
        require_ledger_schema(session)
    except LedgerSchemaUnavailableError as exc:
        report.status, report.reason, report.problems = (
            "aborted",
            exc.code,
            exc.problems,
        )
        return report

    counting = _CountingMapper(mapper)
    service = SharedFirecrawlFederationService(
        session, mapper=counting, worker_id=PILOT_WORKER
    )
    context = _PilotContext(
        service=service,
        holdings=holdings,
        env=env,
        limit=limit,
        sitemap=sitemap,
        authority=authority,
        operator_override=operator_override,
    )
    try:
        for name, source in sources.items():
            entry = _map_one(name, source, context)
            profile = entry.pop("profile", None)
            if profile is not None:
                report.profiles.append(profile.to_dict())
            report.sources.append(entry)
    except LedgerSchemaUnavailableError as exc:
        # The schema went away after the preflight: no lease, no paid call.
        report.status, report.reason, report.problems = (
            "aborted",
            exc.code,
            exc.problems,
        )
    finally:
        report.provider_calls = counting.calls
    return report


@dataclass(frozen=True)
class _PilotContext:
    service: SharedFirecrawlFederationService
    holdings: HoldingsLookup
    env: Mapping[str, str]
    limit: int
    sitemap: str
    authority: SpendAuthority | None
    operator_override: str | None


def _map_one(name, source, ctx: _PilotContext):
    service = ctx.service
    params = {
        "root_url": source["root_url"],
        "search": source.get("search"),
        "limit": ctx.limit,
        "sitemap": ctx.sitemap,
        "include_subdomains": False,
    }
    entry: dict[str, Any] = {"source": name, "source_id": source["source_id"]}
    cached, profile, key = service.cached_profile(**params)
    entry["resource_key"] = key
    if cached == "cache_hit":
        entry.update(status="cache_hit", profile=profile)
        return entry
    if cached == REVIEW_REQUIRED:
        entry.update(status=REVIEW_REQUIRED, reason="OPERATOR_REVIEW_REQUIRED")
        return entry
    if cached == COVERAGE_INSUFFICIENT and not ctx.operator_override:
        entry.update(status=COVERAGE_INSUFFICIENT, reason="OPERATOR_OVERRIDE_REQUIRED")
        return entry

    blocked = provider_gate(
        ctx.env, authority=ctx.authority, lease_check=service.ledger.assert_lease_live
    )
    if blocked is not None:
        entry.update(status="blocked", reason=blocked)
        return entry

    held = ctx.holdings(root_url=params["root_url"], search=params["search"])
    entry["stores_checked"] = list(held.stores_checked)
    if not held.available:
        entry.update(
            status="blocked",
            reason="EXISTING_HOLDINGS_UNVERIFIED",
            holdings_blockers=list(held.blockers),
        )
        return entry
    if held.matches:
        entry.update(status="already_held", held_matches=list(held.matches))
        return entry

    config = load_config(ctx.env)
    authority = ctx.authority
    spend: dict[str, Any] = {}

    def reserve():
        spend["entry"], spend["reservation"] = reserve_live_attempt(
            config,
            governor=authority.governor,
            reserve=authority.reserve,
            reserve_credits=authority.reserve_credits,
            task_id=f"{PILOT_ID}:{name}",
            credit_cost=MAP_CREDIT_COST,
        )

    status = "provider_error"
    try:
        status, profile = service.map_source(
            consumer_module=PILOT_CONSUMER,
            source_id=source["source_id"],
            operator_override=ctx.operator_override,
            before_paid_call=reserve,
            **params,
        )
    except LedgerSchemaUnavailableError:
        raise
    except AcquisitionBlocked as exc:
        entry.update(status="blocked", reason=str(exc))
        return entry
    except LedgerContentionError as exc:
        entry.update(status="ledger_contention", reason=exc.operation)
        return entry
    except PaidResultUnrecordedError as exc:
        entry.update(
            status=REVIEW_REQUIRED,
            reason="PAID_RESULT_UNRECORDED",
            held_for_review=exc.held_for_review,
        )
        return entry
    except Exception as exc:  # noqa: BLE001 - reported without response bodies
        entry.update(status="provider_error", reason=type(exc).__name__)
        return entry
    finally:
        _settle_spend(authority, spend, succeeded=status == "fetched")
    entry.update(status=status, profile=profile)
    return entry


def _settle_spend(authority, spend, *, succeeded: bool) -> None:
    """End the governor entry and record (unknown) usage for a reserved call."""
    if "entry" not in spend:
        return
    try:
        # The Map response does not report credits; unknown usage stays
        # unknown (the conservative reservation is never refunded).
        authority.observe_credits(spend["reservation"], None)
    except Exception:  # noqa: BLE001 - the reservation itself already stands
        logger.warning("federation pilot: credit usage observation not recorded")
    finally:
        authority.governor.end(
            spend["entry"],
            succeeded=succeeded,
            termination_reason="completed" if succeeded else "failed",
        )
