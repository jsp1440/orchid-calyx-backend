"""Governed materialization of verified relational domains into the Knowledge Graph.

This module closes the gap between the existing source/adapter infrastructure and
persisted ``oc_graph`` nodes/edges. It deliberately reuses the canonical source
registry, domain adapters, controlled dry-run engine, and transactional production
publisher instead of creating a second graph implementation.

Read-only validation is bounded by default so multi-million-row domains cannot
exhaust an operator process. Production mutation requires an explicit domain list,
``execute=True``, and the exact confirmation token. Blocked or unverified source
projections always fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .adapters import adapters_by_domain
from .controlled_dry_run import run_controlled_dry_run
from .production_publish import publish_to_production
from .repository import PostgresGraphRepository
from .source_registry import enabled_queries
from .sources import PostgresSourceProvider
from .verified_bulk_sources import bulk_verified_queries

CONFIRMATION_TOKEN = "PUBLISH_VERIFIED_GRAPH_RELATIONSHIPS"
DEFAULT_DRY_RUN_MAX_ROWS_PER_DOMAIN = 10_000
MAX_BATCH_SIZE = 5_000

# Integration-priority domains whose read projections are verified.  Occurrences
# and traits intentionally resolve through verified_bulk_sources.py because the
# deployed catalog proved that the legacy registry selected tiny partial corpora
# (26 occurrence rows and 6,751 resolved trait rows) while production contains
# 580,612 occurrence rows and 19,929 normalized trait-consensus rows.
AUDIT_PRIORITY_DOMAINS = (
    "media",
    "occurrences",
    "traits",
    "climate",
    "literature",
    "pollinators",
    "mycorrhiza",
    "conservation",
)


@dataclass(frozen=True, slots=True)
class MaterializationSelection:
    requested: tuple[str, ...]
    selected: tuple[str, ...]
    unavailable: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return not self.unavailable and bool(self.selected)


def _verified_query_map() -> dict[str, str]:
    """Return canonical verified queries with live bulk overrides applied."""
    query_map = dict(enabled_queries())
    query_map.update(bulk_verified_queries())
    return query_map


def select_domains(domains: Iterable[str] | None = None) -> MaterializationSelection:
    queries = _verified_query_map()
    adapters = adapters_by_domain()
    allowed = set(queries).intersection(adapters)
    raw = AUDIT_PRIORITY_DOMAINS if domains is None else domains
    requested = tuple(
        dict.fromkeys(str(domain).strip() for domain in raw if str(domain).strip())
    )
    selected = tuple(domain for domain in requested if domain in allowed)
    unavailable = tuple(domain for domain in requested if domain not in allowed)
    return MaterializationSelection(requested, selected, unavailable)


def _validate_batch_size(batch_size: int) -> int:
    resolved = int(batch_size)
    if not 1 <= resolved <= MAX_BATCH_SIZE:
        raise ValueError(f"BATCH_SIZE_OUT_OF_RANGE:1..{MAX_BATCH_SIZE}")
    return resolved


def _validate_selection(
    domains: Iterable[str] | None,
    *,
    execute: bool,
) -> MaterializationSelection:
    if execute and domains is None:
        raise ValueError("EXPLICIT_PRODUCTION_DOMAINS_REQUIRED")
    selection = select_domains(domains)
    if not selection.selected:
        raise ValueError("NO_VERIFIED_GRAPH_DOMAINS_SELECTED")
    if selection.unavailable:
        raise ValueError(
            "UNVERIFIED_OR_UNAVAILABLE_GRAPH_DOMAINS:"
            + ",".join(selection.unavailable)
        )
    return selection


def _selected_adapters(selection: MaterializationSelection):
    adapter_map = adapters_by_domain()
    return tuple(adapter_map[domain] for domain in selection.selected)


def _selected_queries(selection: MaterializationSelection) -> dict[str, str]:
    query_map = _verified_query_map()
    return {domain: query_map[domain] for domain in selection.selected}


def _publication_summary(report: dict[str, Any]) -> dict[str, Any]:
    domains = report.get("per_domain") or []
    return {
        "healthy": bool(report.get("healthy")),
        "committed": bool(report.get("committed")),
        "rows_processed": sum(int(item.get("rows_processed") or 0) for item in domains),
        "nodes_written": sum(int(item.get("nodes_written") or 0) for item in domains),
        "edges_written": sum(int(item.get("edges_written") or 0) for item in domains),
        "failed_domains": [
            str(item.get("domain"))
            for item in domains
            if item.get("status") == "failed" or item.get("error")
        ],
    }


def materialize_verified_relationships(
    dsn: str,
    *,
    domains: Iterable[str] | None = None,
    execute: bool = False,
    confirmation: str | None = None,
    batch_size: int = 500,
    max_dry_run_rows_per_domain: int = DEFAULT_DRY_RUN_MAX_ROWS_PER_DOMAIN,
) -> dict[str, Any]:
    """Dry-run or publish verified taxon-linked domain relationships.

    Dry runs are bounded, two-pass, idempotency checks against an in-memory
    staging graph. Production publication delegates to the canonical
    ``publish_to_production`` transaction, which acquires the single-writer lock
    and rolls the entire run back if any domain fails or cross-domain validation
    is unhealthy.
    """
    if not dsn or not str(dsn).strip():
        raise ValueError("DATABASE_URL_REQUIRED")
    batch = _validate_batch_size(batch_size)
    selection = _validate_selection(domains, execute=execute)

    if execute and confirmation != CONFIRMATION_TOKEN:
        raise PermissionError("GRAPH_PUBLICATION_CONFIRMATION_REQUIRED")

    adapters = _selected_adapters(selection)
    queries = _selected_queries(selection)

    if not execute:
        maximum = int(max_dry_run_rows_per_domain)
        if maximum < 1:
            raise ValueError("DRY_RUN_ROW_LIMIT_MUST_BE_POSITIVE")
        source = PostgresSourceProvider(dsn, queries)
        report = run_controlled_dry_run(
            PostgresGraphRepository(dsn),
            source,
            adapters=adapters,
            max_rows_per_domain=maximum,
            batch_size=batch,
        )
        report["materialization"] = {
            "contract": "calyx-verified-relationship-materialization-v4-bulk",
            "requested_domains": list(selection.requested),
            "selected_domains": list(selection.selected),
            "production_graph_mutation": False,
            "bounded_validation": True,
            "max_rows_per_domain": maximum,
            "bulk_source_domains": [
                domain for domain in selection.selected if domain in bulk_verified_queries()
            ],
            "confirmation_required": CONFIRMATION_TOKEN,
        }
        return report

    report = publish_to_production(
        dsn,
        adapters=adapters,
        batch_size=batch,
        queries=queries,
    )
    summary = _publication_summary(report)
    report["materialization"] = {
        "contract": "calyx-verified-relationship-materialization-v4-bulk",
        "requested_domains": list(selection.requested),
        "selected_domains": list(selection.selected),
        "bulk_source_domains": [
            domain for domain in selection.selected if domain in bulk_verified_queries()
        ],
        "production_graph_mutation": summary["committed"],
        "confirmation": "verified",
        "transactional": True,
        "single_writer_lock": True,
        "publication_summary": summary,
    }
    return report
