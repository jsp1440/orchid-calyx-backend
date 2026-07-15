"""Idempotent graph publication.

The publisher turns rows from a domain's *canonical relational source* into
canonical graph nodes and evidence-linked edges.  It is the reusable ingestion
path for every scientific domain — nothing here is genus-specific.

IMPORTANT: publication mutates the graph and is therefore only ever executed as
part of an explicit build run against a writable store.  It is NOT invoked by
the read-only API and is NOT run against production by this change.  Tests
exercise it against an :class:`InMemoryGraphRepository`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .models import Edge, Node
from .vocabulary import EDGE_TYPE_DOMAIN, NODE_TYPE_DOMAIN


def canonical_key(node_type: str, source_pk: Any) -> str:
    """Deterministic node identity.  Same object -> same key -> idempotent."""
    return f"{node_type}:{source_pk}"


@dataclass(frozen=True)
class NodeSpec:
    node_type: str
    source_pk: Any
    display_label: str | None = None
    source_table: str | None = None
    evidence_class: str | None = None
    confidence_score: float | None = None
    confidence_label: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def key(self) -> str:
        return canonical_key(self.node_type, self.source_pk)


@dataclass(frozen=True)
class EdgeSpec:
    edge_type: str
    from_key: str
    to_key: str
    source_table: str | None = None
    source_pk: Any = None
    evidence_class: str | None = None
    confidence_score: float | None = None
    confidence_label: str | None = None
    rule_name: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class DomainAdapter:
    """Maps a canonical relational source to node/edge specs for one domain."""

    domain: str
    source_table: str
    produce: Callable[[Iterable[dict[str, Any]]], tuple[list[NodeSpec], list[EdgeSpec]]]
    required_identifiers: tuple[str, ...] = ()


@dataclass
class PublishResult:
    domain: str
    nodes_written: int = 0
    edges_written: int = 0
    skipped_existing_nodes: int = 0
    skipped_existing_edges: int = 0
    source_rows: int = 0
    missing_identifier_rows: int = 0
    missing_identifier_counts: dict[str, int] = field(default_factory=dict)
    missing_identifier_examples: list[dict[str, Any]] = field(default_factory=list)
    invalid: list[str] = field(default_factory=list)


class _Writer:
    """Adapts an InMemory-style repository's upsert methods to spec publication."""

    def __init__(self, repo: Any):
        if not (hasattr(repo, "upsert_node") and hasattr(repo, "upsert_edge")):
            raise TypeError("publisher requires a writable repository (upsert_node/upsert_edge)")
        self._repo = repo

    def publish(self, nodes: list[NodeSpec], edges: list[EdgeSpec], domain: str) -> PublishResult:
        result = PublishResult(domain=domain)
        key_to_id: dict[str, int] = {}

        for spec in nodes:
            if spec.node_type not in NODE_TYPE_DOMAIN:
                result.invalid.append(f"node_type:{spec.node_type}")
                continue
            existed = self._repo.get_node_by_key(spec.key()) is not None
            node = self._repo.upsert_node(Node(
                kg_node_id=0,
                node_type=spec.node_type,
                canonical_key=spec.key(),
                display_label=spec.display_label,
                source_table=spec.source_table or "",
                source_pk=str(spec.source_pk),
                evidence_class=spec.evidence_class,
                confidence_score=spec.confidence_score,
                confidence_label=spec.confidence_label,
                payload=spec.payload,
            ))
            key_to_id[spec.key()] = node.kg_node_id
            if existed:
                result.skipped_existing_nodes += 1
            else:
                result.nodes_written += 1

        for spec in edges:
            if spec.edge_type not in EDGE_TYPE_DOMAIN:
                result.invalid.append(f"edge_type:{spec.edge_type}")
                continue
            from_id = key_to_id.get(spec.from_key) or self._resolve(spec.from_key)
            to_id = key_to_id.get(spec.to_key) or self._resolve(spec.to_key)
            if from_id is None or to_id is None:
                result.invalid.append(f"edge_missing_endpoint:{spec.edge_type}")
                continue
            before = len(self._repo.all_edges())
            self._repo.upsert_edge(Edge(
                kg_edge_id=0,
                edge_type=spec.edge_type,
                from_node_id=from_id,
                to_node_id=to_id,
                source_table=spec.source_table or "",
                source_pk=(str(spec.source_pk) if spec.source_pk is not None else None),
                evidence_class=spec.evidence_class,
                confidence_score=spec.confidence_score,
                confidence_label=spec.confidence_label,
                rule_name=spec.rule_name,
                payload=spec.payload,
            ))
            if len(self._repo.all_edges()) > before:
                result.edges_written += 1
            else:
                result.skipped_existing_edges += 1
        return result

    def _resolve(self, key: str) -> int | None:
        node = self._repo.get_node_by_key(key)
        return node.kg_node_id if node else None


def publish_domain(
    repo: Any,
    adapter: DomainAdapter,
    rows: Iterable[dict[str, Any]],
) -> PublishResult:
    """Publish one domain's rows into the graph, idempotently."""
    source_rows = list(rows)
    valid_rows: list[dict[str, Any]] = []
    missing_counts = {key: 0 for key in adapter.required_identifiers}
    missing_examples: list[dict[str, Any]] = []
    invalid: list[str] = []

    for index, row in enumerate(source_rows):
        missing = [
            key for key in adapter.required_identifiers
            if row.get(key) is None or row.get(key) == ""
        ]
        if not missing:
            valid_rows.append(row)
            continue
        for key in missing:
            missing_counts[key] += 1
        invalid.append(
            f"missing_required_identifier:row={index}:fields={','.join(missing)}"
        )
        if len(missing_examples) < 10:
            missing_examples.append({
                "domain": adapter.domain,
                "row_index": index,
                "missing": missing,
            })

    nodes, edges = adapter.produce(valid_rows)
    result = _Writer(repo).publish(nodes, edges, adapter.domain)
    result.source_rows = len(source_rows)
    result.missing_identifier_rows = len(source_rows) - len(valid_rows)
    result.missing_identifier_counts = {
        key: count for key, count in missing_counts.items() if count
    }
    result.missing_identifier_examples = missing_examples
    result.invalid = invalid + result.invalid
    return result
