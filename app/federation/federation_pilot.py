"""Ledger-routed Firecrawl federation reconnaissance pilot.

The owner rule this module enforces: never spend Firecrawl (or any paid)
credits on material Orchid Continuum already holds. For every pilot source, in
this order and before any paid call:

1. **Ledger schema** -- :func:`require_ledger_schema`. A missing or
   incompatible ``acquisition_ledger`` aborts the whole run with zero provider
   calls. There is no fallback to a direct mapper call and no bypass flag.
2. **Prior acquisition records** -- a completed ledger row for the same
   ``resource_key`` is returned read-only (no claim, no paid call).
3. **Provider gate** -- ``FIRECRAWL_KILL_SWITCH``, ``NO_API_MODE`` and
   ``FIRECRAWL_API_KEY``, with the same fail-closed semantics as
   :class:`app.literature_extraction.firecrawl_provider.FirecrawlProvider`.
   A blocked gate takes no lease.
4. **Existing holdings** -- the corpus and the source registry's document
   inventory, through the existing read-only corpus audit and the existing
   DOI/URL/content-hash/bibliography matcher. Holdings that cannot be verified
   block the source (no lease); a held match is reused (no lease).
5. **Ledger claim** -- :class:`SharedFirecrawlFederationService`: the mapper
   runs only for ``acquired_lease``; ``in_flight``/``retry_blocked`` make no
   paid call; the result is completed (or failed) on the fenced lease.

Output is reconnaissance only; nothing here writes scientific stores.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.source_federation.acquisition_ledger import (
    AcquisitionLedger,
    LedgerContentionError,
)
from app.source_federation.acquisition_ledger_schema import (
    LedgerSchemaUnavailableError,
    require_ledger_schema,
)

from .shared_firecrawl import SharedFirecrawlFederationService, profile_from_payload

PILOT_ID = "firecrawl-federation-phragmipedium-v1"
PILOT_CONSUMER = "federation-pilot"
PILOT_WORKER = "firecrawl-federation-pilot"

#: Statuses in which the source is answered without any further paid call.
RESOLVED = frozenset({"fetched", "cache_hit", "already_held"})

_GENUS = re.compile(r"[A-Z][a-z]{2,40}")


def provider_gate(env: Mapping[str, str]) -> str | None:
    """Return why a paid Firecrawl call is not allowed, or ``None``.

    Same semantics as ``FirecrawlProvider._gate``: the kill switch is off only
    when exactly ``false``; NO_API mode is off only when exactly ``false``
    (absent means on).
    """
    if env.get("FIRECRAWL_KILL_SWITCH", "false").lower() != "false":
        return "FIRECRAWL_KILL_SWITCH"
    if env.get("NO_API_MODE", "true").lower() != "false":
        return "NO_API_MODE"
    if not env.get("FIRECRAWL_API_KEY"):
        return "FIRECRAWL_KEY_UNAVAILABLE"
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
    ledger: AcquisitionLedger = service.ledger
    try:
        for name, source in sources.items():
            entry = _map_one(
                name, source, service, ledger, holdings, env, limit, sitemap
            )
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


def _map_one(name, source, service, ledger, holdings, env, limit, sitemap):
    params = {
        "root_url": source["root_url"],
        "search": source.get("search"),
        "limit": limit,
        "sitemap": sitemap,
        "include_subdomains": False,
    }
    entry: dict[str, Any] = {"source": name, "source_id": source["source_id"]}
    request = service.acquisition_request(consumer_module=PILOT_CONSUMER, **params)
    entry["resource_key"] = request.key

    cached = ledger.cached_payload(request.key)
    if cached is not None:
        entry.update(status="cache_hit", profile=profile_from_payload(cached))
        return entry

    blocked = provider_gate(env)
    if blocked is not None:
        entry.update(status="blocked", reason=blocked)
        return entry

    held = holdings(root_url=params["root_url"], search=params["search"])
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

    try:
        status, profile = service.map_source(
            consumer_module=PILOT_CONSUMER, source_id=source["source_id"], **params
        )
    except LedgerSchemaUnavailableError:
        raise
    except LedgerContentionError as exc:
        entry.update(status="ledger_contention", reason=exc.operation)
        return entry
    except Exception as exc:  # noqa: BLE001 - reported without response bodies
        entry.update(status="provider_error", reason=type(exc).__name__)
        return entry
    entry.update(status=status, profile=profile)
    return entry
