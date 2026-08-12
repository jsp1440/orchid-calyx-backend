"""Governed materialization of verified relational domains into the Knowledge Graph.

This module closes the gap between the existing source/adaptor infrastructure and
persisted ``oc_graph`` nodes/edges.  It deliberately reuses the canonical source
registry, domain adapters, BuildOrchestrator, and writable graph repository.

Default behavior is a full dry run.  Production mutation requires BOTH
``execute=True`` and the exact confirmation token.  No blocked/unverified source
projection can be selected for publication.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .adapters import adapters_by_domain
from .orchestrator import BuildOrchestrator, ExecutionMode
from .repository import PostgresGraphRepository, WritablePostgresGraphRepository
from .source_registry import enabled_queries
from .sources import PostgresSourceProvider

CONFIRMATION_TOKEN = "PUBLISH_VERIFIED_GRAPH_RELATIONSHIPS"

# Domains with verified read projections in source_registry.py.  This list is
# intentionally derived from the registry at runtime; it is documented here only
# as the audit-remediation target set.
AUDIT_PRIORITY_DOMAINS = (
    "media",
    "occurrences",
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


def select_domains(domains: Iterable[str] | None = None) -> MaterializationSelection:
    queries = dict(enabled_queries())
    adapters = adapters_by_domain()
    allowed = set(queries).intersection(adapters)
    requested = tuple(dict.fromkeys(str(d).strip() for d in (domains or AUDIT_PRIORITY_DOMAINS) if str(d).strip()))
    selected = tuple(d for d in requested if d in allowed)
    unavailable = tuple(d for d in requested if d not in allowed)
    return MaterializationSelection(requested, selected, unavailable)


def materialize_verified_relationships(
    dsn: str,
    *,
    domains: Iterable[str] | None = None,
    execute: bool = False,
    confirmation: str | None = None,
    batch_size: int = 500,
) -> dict[str, Any]:
    """Dry-run or publish verified taxon-linked domain relationships.

    Production publication is fail-closed: unknown/blocked domains, a missing
    confirmation token, or an empty selection all stop before a writable graph
    repository is opened.
    """
    if not dsn or not str(dsn).strip():
        raise ValueError("DATABASE_URL_REQUIRED")
    selection = select_domains(domains)
    if not selection.selected:
        raise ValueError("NO_VERIFIED_GRAPH_DOMAINS_SELECTED")
    if selection.unavailable:
        raise ValueError(
            "UNVERIFIED_OR_UNAVAILABLE_GRAPH_DOMAINS:" + ",".join(selection.unavailable)
        )
    if execute and confirmation != CONFIRMATION_TOKEN:
        raise PermissionError("GRAPH_PUBLICATION_CONFIRMATION_REQUIRED")

    query_map = dict(enabled_queries())
    queries = {domain: query_map[domain] for domain in selection.selected}
    adapter_map = adapters_by_domain()
    adapters = tuple(adapter_map[domain] for domain in selection.selected)
    source = PostgresSourceProvider(dsn, queries)

    if not execute:
        repo = PostgresGraphRepository(dsn)
        report = BuildOrchestrator(
            repo,
            source,
            adapters=adapters,
            batch_size=batch_size,
            authorized_to_publish=False,
        ).run(ExecutionMode.DRY_RUN)
        report["materialization"] = {
            "contract": "calyx-verified-relationship-materialization-v1",
            "requested_domains": list(selection.requested),
            "selected_domains": list(selection.selected),
            "production_graph_mutation": False,
            "confirmation_required": CONFIRMATION_TOKEN,
        }
        return report

    with WritablePostgresGraphRepository(dsn) as repo:
        report = BuildOrchestrator(
            repo,
            source,
            adapters=adapters,
            batch_size=batch_size,
            authorized_to_publish=True,
        ).run(ExecutionMode.PUBLISH)

    report["materialization"] = {
        "contract": "calyx-verified-relationship-materialization-v1",
        "requested_domains": list(selection.requested),
        "selected_domains": list(selection.selected),
        "production_graph_mutation": True,
        "confirmation": "verified",
    }
    return report
