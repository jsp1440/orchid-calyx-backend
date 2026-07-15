"""Typed representations of graph nodes, edges and traversal results."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Node:
    kg_node_id: int
    node_type: str
    canonical_key: str
    display_label: str | None = None
    source_table: str | None = None
    source_pk: str | None = None
    evidence_class: str | None = None
    confidence_score: float | None = None
    confidence_label: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.kg_node_id,
            "node_type": self.node_type,
            "canonical_key": self.canonical_key,
            "label": self.display_label,
            "provenance": {
                "source_table": self.source_table,
                "source_pk": self.source_pk,
            },
            "evidence_class": self.evidence_class,
            "confidence": {
                "score": self.confidence_score,
                "label": self.confidence_label,
            },
            "payload": self.payload,
        }


@dataclass(frozen=True)
class Edge:
    kg_edge_id: int
    edge_type: str
    from_node_id: int
    to_node_id: int
    source_table: str | None = None
    source_pk: str | None = None
    evidence_class: str | None = None
    confidence_score: float | None = None
    confidence_label: str | None = None
    rule_name: str | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.kg_edge_id,
            "edge_type": self.edge_type,
            "from": self.from_node_id,
            "to": self.to_node_id,
            "provenance": {
                "source_table": self.source_table,
                "source_pk": self.source_pk,
                "rule_name": self.rule_name,
            },
            "evidence_class": self.evidence_class,
            "confidence": {
                "score": self.confidence_score,
                "label": self.confidence_label,
            },
            "payload": self.payload,
        }
