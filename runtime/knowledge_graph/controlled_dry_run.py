"""Controlled, non-production Knowledge Graph dry run.

The engine reads canonical source rows, seeds an in-memory graph with existing
taxonomy nodes, publishes each eligible scientific domain twice, and requires
the second pass to have a zero node/edge delta. It never writes to PostgreSQL.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from .adapters import DOMAIN_ADAPTERS
from .publisher import DomainAdapter, publish_domain
from .repository import GraphRepository, InMemoryGraphRepository
from .sources import SourceProvider
from .validation import validate_graph


@dataclass(frozen=True)
class DryRunDomainResult:
    domain: str
    available_rows: int
    rows_tested: int
    first_nodes: int
    first_edges: int
    second_nodes: int
    second_edges: int
    invalid: int
    truncated: bool
    error: str | None = None

    @property
    def zero_delta(self) -> bool:
        return self.error is None and self.second_nodes == 0 and self.second_edges == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "available_rows": self.available_rows,
            "rows_tested": self.rows_tested,
            "first_pass": {"nodes_written": self.first_nodes, "edges_written": self.first_edges},
            "second_pass": {"nodes_written": self.second_nodes, "edges_written": self.second_edges},
            "invalid": self.invalid,
            "truncated": self.truncated,
            "zero_delta": self.zero_delta,
            "error": self.error,
        }


def _seed_taxonomy(source_repo: GraphRepository, staging: InMemoryGraphRepository) -> int:
    fetch = getattr(source_repo, "taxonomy_nodes", None)
    nodes: Iterable[Any]
    if callable(fetch):
        nodes = fetch()
    else:
        nodes = (n for n in source_repo.all_nodes() if n.node_type in {"taxon", "genus"})
    count = 0
    for node in nodes:
        staging.upsert_node(node)
        count += 1
    return count


def _load_rows(source: SourceProvider, domain: str, maximum: int, batch_size: int) -> tuple[list[dict[str, Any]], int]:
    available = source.count(domain)
    target = min(available, maximum)
    rows: list[dict[str, Any]] = []
    offset = 0
    while len(rows) < target:
        chunk = source.fetch(domain, min(batch_size, target - len(rows)), offset)
        if not chunk:
            break
        rows.extend(chunk)
        offset += len(chunk)
    return rows, available


def run_controlled_dry_run(
    graph_repo: GraphRepository,
    source: SourceProvider,
    *,
    adapters: Iterable[DomainAdapter] = DOMAIN_ADAPTERS,
    max_rows_per_domain: int = 10_000,
    batch_size: int = 500,
) -> dict[str, Any]:
    """Run a two-pass publication against an in-memory graph only."""
    maximum = max(1, int(max_rows_per_domain))
    batch = max(1, int(batch_size))
    staging = InMemoryGraphRepository()
    taxonomy_seeded = _seed_taxonomy(graph_repo, staging)
    results: list[DryRunDomainResult] = []

    for adapter in adapters:
        try:
            rows, available = _load_rows(source, adapter.domain, maximum, batch)
            first = publish_domain(staging, adapter, rows)
            second = publish_domain(staging, adapter, rows)
            results.append(DryRunDomainResult(
                domain=adapter.domain,
                available_rows=available,
                rows_tested=len(rows),
                first_nodes=first.nodes_written,
                first_edges=first.edges_written,
                second_nodes=second.nodes_written,
                second_edges=second.edges_written,
                invalid=len(first.invalid) + len(second.invalid),
                truncated=available > len(rows),
            ))
        except Exception as exc:  # surfaced per-domain; other domains continue
            results.append(DryRunDomainResult(
                domain=adapter.domain,
                available_rows=-1,
                rows_tested=0,
                first_nodes=0,
                first_edges=0,
                second_nodes=0,
                second_edges=0,
                invalid=0,
                truncated=False,
                error=str(exc),
            ))

    validation = validate_graph(staging)
    zero_delta = all(item.zero_delta for item in results)
    errors = [f"{item.domain}: {item.error}" for item in results if item.error]
    truncated_domains = [item.domain for item in results if item.truncated]
    full_coverage = not truncated_domains and not errors
    authorization_ready = zero_delta and full_coverage and validation.get("healthy", False)

    return {
        "contract": "calyx-controlled-graph-dry-run-v1",
        "graph_mutation": False,
        "taxonomy_nodes_seeded": taxonomy_seeded,
        "max_rows_per_domain": maximum,
        "domains": [item.to_dict() for item in results],
        "totals": {
            "rows_tested": sum(item.rows_tested for item in results),
            "first_nodes": sum(item.first_nodes for item in results),
            "first_edges": sum(item.first_edges for item in results),
            "second_nodes": sum(item.second_nodes for item in results),
            "second_edges": sum(item.second_edges for item in results),
            "invalid": sum(item.invalid for item in results),
        },
        "zero_delta": zero_delta,
        "truncated_domains": truncated_domains,
        "full_coverage": full_coverage,
        "validation": validation,
        "errors": errors,
        "publication_authorization_ready": authorization_ready,
    }


def publication_authorization_payload(report: dict[str, Any]) -> dict[str, Any]:
    """Produce a non-executing owner decision payload from a dry-run report."""
    ready = bool(report.get("publication_authorization_ready"))
    return {
        "contract": "calyx-graph-publication-authorization-v1",
        "ready_for_owner_decision": ready,
        "authorized": False,
        "projected_nodes": report.get("totals", {}).get("first_nodes", 0),
        "projected_edges": report.get("totals", {}).get("first_edges", 0),
        "domains": [d.get("domain") for d in report.get("domains", []) if not d.get("error")],
        "blockers": ([] if ready else [
            *report.get("errors", []),
            *(f"truncated:{d}" for d in report.get("truncated_domains", [])),
            *( ["second_pass_not_zero_delta"] if not report.get("zero_delta") else [] ),
            *( ["graph_integrity_failed"] if not report.get("validation", {}).get("healthy", False) else [] ),
        ]),
        "operator_action": (
            "Review projected counts and explicitly authorize a separate production publication run."
            if ready else "Resolve all blockers and rerun the complete dry run."
        ),
        "production_write_executed": False,
    }
