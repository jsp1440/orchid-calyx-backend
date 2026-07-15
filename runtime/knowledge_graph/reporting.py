"""BUILD-066 graph-completion reporting.

Pure, side-effect-free report generators that read a populated
:class:`GraphRepository` (staging graph from DRY_RUN, or the live graph after a
PUBLISH) plus the source registry, and compute:

* **Domain coverage** — per domain: source availability, records connected
  (nodes/edges projected), skipped/rejected, and the registry connectivity
  strategy / blocked reason.
* **Graph completeness** — per canonical taxon: which domains are connected,
  which are missing, and the per-domain relationship counts; plus aggregate
  statistics across all taxa.
* **Review queues** — taxonomic conflicts (from :mod:`canonical_taxonomy`) and
  per-domain connectivity warnings, so nothing is silently discarded.

Nothing here opens a database connection or mutates any graph.  The functions
take already-fetched data structures so they are trivially testable against an
:class:`InMemoryGraphRepository`.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable

from .adapters import DOMAIN_ADAPTERS
from .repository import GraphRepository

TAXON_NODE_TYPE = "taxon"

#: edge_type -> domain, derived from the adapter definitions (single source of
#: truth).  Used to attribute each taxon-anchored edge to its domain.
EDGE_TYPE_TO_DOMAIN: dict[str, str] = {}


def _edge_type_of(adapter) -> str | None:
    """Best-effort extraction of an adapter's edge type via a probe row."""
    try:
        _, edges = adapter.produce([{"source_pk": "__probe__", "taxon_pk": "__probe__"}])
    except Exception:
        return None
    return edges[0].edge_type if edges else None


for _adapter in DOMAIN_ADAPTERS:
    _et = _edge_type_of(_adapter)
    if _et:
        EDGE_TYPE_TO_DOMAIN[_et] = _adapter.domain

ALL_ADAPTER_DOMAINS: tuple[str, ...] = tuple(a.domain for a in DOMAIN_ADAPTERS)


def domain_coverage_report(
    per_domain: Iterable[dict[str, Any]],
    registry: dict[str, Any],
    source_availability: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Per-domain coverage: records connected / published / skipped / blocked.

    ``per_domain`` are the orchestrator ``DomainOutcome.to_dict()`` entries.
    ``registry`` is ``registry_by_domain()``.  Counts reflect the run mode:
    under DRY_RUN they are *projected*; under PUBLISH they are *actual*.
    """
    avail = source_availability or {}
    domains: list[dict[str, Any]] = []
    for o in per_domain:
        d = o["domain"]
        rq = registry.get(d)
        meta = getattr(rq, "metadata", {}) if rq is not None else {}
        available = o.get("available_rows")
        if available is None:
            available = avail.get(d)
        connected = o.get("rows_processed", 0)
        domains.append({
            "domain": d,
            "status": o.get("status"),
            "source_available": available,
            "records_connected": connected,
            "nodes_published": o.get("nodes_written", 0),
            "edges_published": o.get("edges_written", 0),
            "skipped_existing_nodes": o.get("skipped_existing_nodes", 0),
            "skipped_existing_edges": o.get("skipped_existing_edges", 0),
            "invalid_rejected": o.get("invalid", 0),
            "connectivity_strategy": getattr(rq, "taxon_mapping", None),
            "enabled": getattr(rq, "enabled", None),
            "blocked_reason": getattr(rq, "blocked_reason", None),
            "readiness": meta.get("status"),
            "operator_notes": meta.get("operator_notes"),
            "warnings": o.get("warnings", []),
            "error": o.get("error"),
        })
    totals = {
        "domains": len(domains),
        "records_connected": sum(x["records_connected"] for x in domains),
        "nodes_published": sum(x["nodes_published"] for x in domains),
        "edges_published": sum(x["edges_published"] for x in domains),
        "invalid_rejected": sum(x["invalid_rejected"] for x in domains),
    }
    return {"per_domain": domains, "totals": totals}


def graph_completeness_report(repo: GraphRepository) -> dict[str, Any]:
    """Per-taxon domain connectivity + counts, plus aggregate statistics."""
    nodes = repo.all_nodes()
    edges = repo.all_edges()
    node_by_id = {n.kg_node_id: n for n in nodes}

    taxa = [n for n in nodes if n.node_type == TAXON_NODE_TYPE]
    domain_universe = sorted(set(EDGE_TYPE_TO_DOMAIN.values()))

    # taxon node id -> {domain: count}
    per_taxon_counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e in edges:
        domain = EDGE_TYPE_TO_DOMAIN.get(e.edge_type)
        if domain is None:
            continue
        frm = node_by_id.get(e.from_node_id)
        if frm is None or frm.node_type != TAXON_NODE_TYPE:
            continue
        per_taxon_counts[e.from_node_id][domain] += 1

    per_taxon: list[dict[str, Any]] = []
    domain_taxa_count: dict[str, int] = {d: 0 for d in domain_universe}
    connected_domain_histogram: dict[int, int] = defaultdict(int)
    for t in taxa:
        counts = per_taxon_counts.get(t.kg_node_id, {})
        connected = sorted(counts.keys())
        missing = [d for d in domain_universe if d not in counts]
        for d in connected:
            domain_taxa_count[d] += 1
        connected_domain_histogram[len(connected)] += 1
        per_taxon.append({
            "taxon_key": t.canonical_key,
            "taxon_label": t.display_label,
            "connected_domains": connected,
            "missing_domains": missing,
            "relationship_count": sum(counts.values()),
            "counts_by_domain": {d: counts.get(d, 0) for d in domain_universe},
        })

    total_taxa = len(taxa)
    taxa_with_any = sum(1 for p in per_taxon if p["connected_domains"])
    aggregate = {
        "total_canonical_taxa": total_taxa,
        "taxa_with_at_least_one_domain": taxa_with_any,
        "taxa_fully_unconnected": total_taxa - taxa_with_any,
        "domain_universe": domain_universe,
        "taxa_connected_per_domain": domain_taxa_count,
        "domain_coverage_pct": {
            d: (round(100.0 * domain_taxa_count[d] / total_taxa, 4) if total_taxa else 0.0)
            for d in domain_universe
        },
        "connected_domain_histogram": dict(sorted(connected_domain_histogram.items())),
        "overall_completion_pct": (
            round(100.0 * taxa_with_any / total_taxa, 4) if total_taxa else 0.0
        ),
    }
    return {"aggregate": aggregate, "per_taxon": per_taxon}


def review_queues(
    conflicts: dict[str, list[dict[str, Any]]],
    per_domain: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Assemble non-blocking review queues.

    ``conflicts`` is the output of :func:`canonical_taxonomy.detect_conflicts`.
    Per-domain connectivity warnings (name-join collisions, orphaned rows) are
    captured as their own queue so unconnected records are documented, never
    dropped.
    """
    queues: dict[str, list[dict[str, Any]]] = {
        "duplicate_accepted_taxa": conflicts.get("duplicate_accepted_taxa", []),
        "unresolved_synonym_chains": conflicts.get("unresolved_synonym_chains", []),
        "authority_disagreements": conflicts.get("authority_disagreements", []),
    }
    domain_connectivity: list[dict[str, Any]] = []
    for o in per_domain:
        warns = o.get("warnings", [])
        if warns or o.get("error"):
            domain_connectivity.append({
                "domain": o["domain"],
                "status": o.get("status"),
                "warnings": warns,
                "error": o.get("error"),
            })
    queues["domain_connectivity"] = domain_connectivity
    summary = {k: len(v) for k, v in queues.items()}
    summary["total_items"] = sum(summary.values())
    return {"summary": summary, "queues": queues}
