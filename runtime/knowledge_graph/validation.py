"""Automatic validation for the unified Knowledge Graph build.

Validation is read-only: it inspects a repository's current node/edge set and
reports structural, vocabulary, provenance and cross-domain problems.

The original cross-domain rule assumed non-taxonomy relationships radiated
from taxon nodes into one domain. BUILD-614 preserves that rule for the legacy
biodiversity graph while adding a separate contract for controlled scientific
causal/evidence relationships that legitimately connect mechanisms across
molecular, anatomical, physiological, developmental, environmental, phenotype,
and cultivation domains.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from .causal_vocabulary import (
    CAUSAL_REASONING_NODE_TYPES,
    is_causal_reasoning_edge,
)
from .models import Edge, Node
from .quality import quality_report
from .repository import GraphRepository
from .vocabulary import (
    EDGE_TYPE_DOMAIN,
    NODE_TYPE_DOMAIN,
    domain_for_edge_type,
    domain_for_node_type,
)


def _identifier_integrity(nodes: list[Node]) -> dict[str, Any]:
    bad_keys = [
        n.canonical_key
        for n in nodes
        if not n.canonical_key
        or ":" not in n.canonical_key
        or n.canonical_key != f"{n.node_type}:{n.source_pk}"
    ]
    return {"invalid_canonical_keys": len(bad_keys), "examples": bad_keys[:10]}


def _duplicate_relationships(edges: list[Edge]) -> dict[str, Any]:
    counts = Counter(
        (e.edge_type, e.from_node_id, e.to_node_id, e.source_table) for e in edges
    )
    dupes = sum(c - 1 for c in counts.values() if c > 1)
    return {"duplicate_edges": dupes}


def _vocabulary_compliance(nodes: list[Node], edges: list[Edge]) -> dict[str, Any]:
    bad_nodes = sorted(
        {n.node_type for n in nodes if n.node_type not in NODE_TYPE_DOMAIN}
    )
    bad_edges = sorted(
        {e.edge_type for e in edges if e.edge_type not in EDGE_TYPE_DOMAIN}
    )
    return {
        "invalid_node_types": bad_nodes,
        "invalid_edge_types": bad_edges,
        "compliant": not bad_nodes and not bad_edges,
    }


def _provenance_completeness(nodes: list[Node], edges: list[Edge]) -> dict[str, Any]:
    nodes_missing = sum(1 for n in nodes if not n.source_table or not n.source_pk)
    edges_missing = sum(1 for e in edges if not e.source_table)
    return {
        "nodes_missing_provenance": nodes_missing,
        "edges_missing_provenance": edges_missing,
    }


def _causal_endpoint_violations(
    edge: Edge,
    source: Node | None,
    target: Node | None,
) -> list[str]:
    violations: list[str] = []
    if source is None or target is None:
        return violations
    if source.node_type not in CAUSAL_REASONING_NODE_TYPES:
        violations.append(f"{source.node_type}-{edge.edge_type}:invalid_causal_source")
    if target.node_type not in CAUSAL_REASONING_NODE_TYPES:
        violations.append(f"{edge.edge_type}->{target.node_type}:invalid_causal_target")
    return violations


def _cross_domain_consistency(nodes: list[Node], edges: list[Edge]) -> dict[str, Any]:
    """Validate legacy taxon-domain edges and cross-scale causal relationships.

    Legacy non-taxonomy domain edges retain the original invariant: source is a
    taxonomic node and target belongs to the edge's domain.

    Controlled causal/evidence relationships use a different invariant: both
    endpoints must be approved causal-reasoning node types. They are allowed to
    cross scientific domains because that cross-scale linkage is the purpose of
    the causal graph.
    """
    by_id = {n.kg_node_id: n for n in nodes}
    violations: list[str] = []
    causal_edges_checked = 0
    legacy_edges_checked = 0

    for edge in edges:
        source = by_id.get(edge.from_node_id)
        target = by_id.get(edge.to_node_id)

        if is_causal_reasoning_edge(edge.edge_type):
            causal_edges_checked += 1
            violations.extend(_causal_endpoint_violations(edge, source, target))
            continue

        edge_domain = domain_for_edge_type(edge.edge_type)
        if edge_domain in ("taxonomy", "unknown"):
            continue

        legacy_edges_checked += 1
        if target is not None and domain_for_node_type(target.node_type) != edge_domain:
            violations.append(f"{edge.edge_type}->{target.node_type}")
        if source is not None and domain_for_node_type(source.node_type) != "taxonomy":
            violations.append(f"{source.node_type}-{edge.edge_type}")

    return {
        "mismatched_endpoint_edges": len(violations),
        "examples": sorted(set(violations))[:10],
        "causal_edges_checked": causal_edges_checked,
        "legacy_cross_domain_edges_checked": legacy_edges_checked,
    }


def _domain_breakdown(
    nodes: list[Node], edges: list[Edge]
) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = defaultdict(lambda: {"nodes": 0, "edges": 0})
    for node in nodes:
        out[domain_for_node_type(node.node_type)]["nodes"] += 1
    for edge in edges:
        out[domain_for_edge_type(edge.edge_type)]["edges"] += 1
    return {key: value for key, value in out.items() if key != "unknown"}


def validate_graph(
    repo: GraphRepository,
    publication_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run every automatic validation check against a repository and its input.

    ``publication_metrics`` carries source-row rejections that cannot be
    inferred from the graph after a row has been rejected. Any missing required
    identifier is a validation problem and prevents a healthy result.
    """
    nodes = repo.all_nodes()
    edges = repo.all_edges()

    quality = quality_report(repo)
    identifiers = _identifier_integrity(nodes)
    duplicates = _duplicate_relationships(edges)
    vocabulary = _vocabulary_compliance(nodes, edges)
    provenance = _provenance_completeness(nodes, edges)
    cross_domain = _cross_domain_consistency(nodes, edges)
    publication_input = {
        "source_rows": int((publication_metrics or {}).get("source_rows", 0)),
        "missing_identifier_rows": int(
            (publication_metrics or {}).get("missing_identifier_rows", 0)
        ),
        "missing_identifier_counts": dict(
            (publication_metrics or {}).get("missing_identifier_counts", {})
        ),
        "missing_identifier_examples": list(
            (publication_metrics or {}).get("missing_identifier_examples", [])
        )[:10],
    }

    problems = (
        quality["orphan_nodes"]
        + quality["dangling_edges"]
        + quality["duplicate_canonical_nodes"]
        + identifiers["invalid_canonical_keys"]
        + duplicates["duplicate_edges"]
        + (0 if vocabulary["compliant"] else 1)
        + provenance["nodes_missing_provenance"]
        + provenance["edges_missing_provenance"]
        + cross_domain["mismatched_endpoint_edges"]
        + publication_input["missing_identifier_rows"]
    )

    return {
        "identifier_integrity": identifiers,
        "duplicate_relationships": duplicates,
        "orphan_nodes": quality["orphan_nodes"],
        "orphan_edges": quality["dangling_edges"],
        "vocabulary_compliance": vocabulary,
        "provenance_completeness": provenance,
        "quality": quality,
        "cross_domain_consistency": cross_domain,
        "publication_input_integrity": publication_input,
        "domain_breakdown": _domain_breakdown(nodes, edges),
        "total_problems": problems,
        "healthy": problems == 0,
    }
