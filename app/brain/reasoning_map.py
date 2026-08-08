from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from runtime.knowledge_graph import Edge, GraphRepository, Node


class ReasoningDirection(StrEnum):
    FORWARD = "forward"
    BACKWARD = "backward"
    BOTH = "both"


class ReasoningProfile(StrEnum):
    BIOLOGICAL_MECHANISM = "biological_mechanism"
    PHENOTYPE_EXPRESSION = "phenotype_expression"
    CULTIVATION_DIAGNOSIS = "cultivation_diagnosis"
    EVIDENCE_TRACE = "evidence_trace"
    ALL_RELATIONSHIPS = "all_relationships"


@dataclass(frozen=True)
class RelationSemantics:
    role: str
    polarity: int
    causal: bool


_POSITIVE = {
    "causes",
    "promotes",
    "activates",
    "induces",
    "enables",
    "results_in",
    "expressed_as",
    "increases",
    "stimulates",
    "supports",
    "facilitates",
}
_NEGATIVE = {
    "inhibits",
    "suppresses",
    "reduces",
    "blocks",
    "represses",
    "contradicts",
}
_REGULATORY = {
    "regulates",
    "modulates",
    "responds_to",
    "depends_on",
    "requires",
    "precedes",
    "influences",
}
_EVIDENCE = {
    "supports",
    "contradicts",
    "observed_as",
    "documented_by",
    "derived_from",
    "has_evidence",
}

_PROFILE_NODE_TYPES = {
    ReasoningProfile.BIOLOGICAL_MECHANISM: {
        "gene",
        "genetic_variant",
        "protein",
        "enzyme",
        "hormone",
        "signal",
        "cell",
        "tissue",
        "organ",
        "trait",
        "physiology",
        "process",
        "developmental_process",
        "phenotype",
        "environment",
        "climate",
    },
    ReasoningProfile.PHENOTYPE_EXPRESSION: {
        "gene",
        "genetic_variant",
        "protein",
        "hormone",
        "cell",
        "tissue",
        "organ",
        "trait",
        "physiology",
        "process",
        "developmental_process",
        "phenotype",
        "environment",
        "climate",
        "cultivation",
    },
    ReasoningProfile.CULTIVATION_DIAGNOSIS: {
        "taxon",
        "plant",
        "specimen",
        "trait",
        "symptom",
        "physiology",
        "process",
        "environment",
        "climate",
        "cultivation",
        "treatment",
        "nutrient",
        "pathogen",
        "pest",
    },
    ReasoningProfile.EVIDENCE_TRACE: set(),
    ReasoningProfile.ALL_RELATIONSHIPS: set(),
}


def relation_semantics(edge_type: str) -> RelationSemantics:
    normalized = edge_type.strip().lower()
    if normalized in _NEGATIVE:
        return RelationSemantics("causal", -1, True)
    if normalized in _POSITIVE:
        role = "evidence" if normalized == "supports" else "causal"
        return RelationSemantics(role, 1, normalized != "supports")
    if normalized in _REGULATORY:
        return RelationSemantics("regulatory", 0, True)
    if normalized in _EVIDENCE:
        polarity = -1 if normalized == "contradicts" else 0
        return RelationSemantics("evidence", polarity, False)
    return RelationSemantics("context", 0, False)


def _confidence(edge: Edge) -> float:
    value = edge.confidence_score if edge.confidence_score is not None else 0.5
    return max(0.0, min(float(value), 1.0))


def _edge_evidence(edge: Edge) -> dict[str, Any]:
    payload = edge.payload or {}
    return {
        "edge_id": edge.kg_edge_id,
        "source_table": edge.source_table,
        "source_pk": edge.source_pk,
        "evidence_class": edge.evidence_class,
        "doi": payload.get("doi"),
        "citation": payload.get("citation"),
        "paper_id": payload.get("paper_id"),
        "claim_id": payload.get("claim_id"),
        "evidence_id": payload.get("evidence_id"),
        "source_anchor": payload.get("source_anchor"),
    }


def _path_confidence(edges: Iterable[Edge]) -> float:
    ordered = list(edges)
    if not ordered:
        return 1.0
    conservative = min(_confidence(edge) for edge in ordered)
    depth_penalty = 0.95 ** max(0, len(ordered) - 1)
    return round(conservative * depth_penalty, 6)


def _path_polarity(edges: Iterable[Edge]) -> int:
    polarity = 1
    informative = False
    for edge in edges:
        value = relation_semantics(edge.edge_type).polarity
        if value == 0:
            continue
        informative = True
        polarity *= value
    return polarity if informative else 0


class ReasoningMapEngine:
    """Build deterministic, evidence-bearing causal maps without mutating canonical graph state."""

    def __init__(self, repository: GraphRepository) -> None:
        self.repository = repository

    def build(
        self,
        subject_id: int,
        *,
        direction: ReasoningDirection = ReasoningDirection.FORWARD,
        profile: ReasoningProfile = ReasoningProfile.ALL_RELATIONSHIPS,
        max_depth: int = 4,
        limit: int = 200,
        edge_types: tuple[str, ...] = (),
        causal_only: bool = False,
    ) -> dict[str, Any]:
        subject = self.repository.get_node(subject_id)
        if subject is None:
            raise LookupError("NODE_NOT_FOUND")
        if max_depth < 1 or max_depth > 8:
            raise ValueError("REASONING_MAP_DEPTH_OUT_OF_RANGE")
        if limit < 1 or limit > 1000:
            raise ValueError("REASONING_MAP_LIMIT_OUT_OF_RANGE")

        nodes_by_id = {node.kg_node_id: node for node in self.repository.all_nodes()}
        all_edges = sorted(
            self.repository.all_edges(), key=lambda item: item.kg_edge_id
        )
        selected = [
            edge
            for edge in all_edges
            if self._edge_allowed(edge, nodes_by_id, profile, edge_types, causal_only)
        ]
        outgoing: dict[int, list[Edge]] = {}
        incoming: dict[int, list[Edge]] = {}
        for edge in selected:
            outgoing.setdefault(edge.from_node_id, []).append(edge)
            incoming.setdefault(edge.to_node_id, []).append(edge)

        paths: list[dict[str, Any]] = []
        used_edge_ids: set[int] = set()
        used_node_ids: set[int] = {subject_id}
        layers: dict[int, set[int]] = {0: {subject_id}}
        queue: list[tuple[int, list[int], list[Edge]]] = [
            (subject_id, [subject_id], [])
        ]

        while queue and len(paths) < limit:
            current_id, node_path, edge_path = queue.pop(0)
            depth = len(edge_path)
            if depth >= max_depth:
                continue
            candidates = self._candidate_edges(
                current_id, outgoing, incoming, direction
            )
            for edge, next_id, traversal_direction in candidates:
                if next_id in node_path:
                    continue
                if next_id not in nodes_by_id:
                    continue
                next_edges = edge_path + [edge]
                next_nodes = node_path + [next_id]
                path = self._serialize_path(
                    next_nodes, next_edges, nodes_by_id, traversal_direction
                )
                paths.append(path)
                used_edge_ids.add(edge.kg_edge_id)
                used_node_ids.add(next_id)
                layers.setdefault(len(next_edges), set()).add(next_id)
                if len(paths) >= limit:
                    break
                queue.append((next_id, next_nodes, next_edges))

        mapped_edges = [edge for edge in selected if edge.kg_edge_id in used_edge_ids]
        mapped_nodes = [nodes_by_id[node_id] for node_id in sorted(used_node_ids)]
        return {
            "subject": subject.to_dict(),
            "configuration": {
                "direction": direction.value,
                "profile": profile.value,
                "max_depth": max_depth,
                "limit": limit,
                "edge_types": list(edge_types),
                "causal_only": causal_only,
            },
            "nodes": [node.to_dict() for node in mapped_nodes],
            "edges": [self._serialize_edge(edge) for edge in mapped_edges],
            "paths": paths,
            "layers": [
                {
                    "depth": depth,
                    "node_ids": sorted(node_ids),
                }
                for depth, node_ids in sorted(layers.items())
            ],
            "summary": {
                "node_count": len(mapped_nodes),
                "edge_count": len(mapped_edges),
                "path_count": len(paths),
                "causal_edge_count": sum(
                    1
                    for edge in mapped_edges
                    if relation_semantics(edge.edge_type).causal
                ),
                "evidence_edge_count": sum(
                    1
                    for edge in mapped_edges
                    if relation_semantics(edge.edge_type).role == "evidence"
                ),
            },
            "governance": {
                "read_only": True,
                "canonical_graph_mutated": False,
                "automatically_published": False,
                "reasoning_map_is_explanatory_artifact": True,
                "human_review_required_for_new_scientific_claims": True,
            },
        }

    @staticmethod
    def _edge_allowed(
        edge: Edge,
        nodes_by_id: dict[int, Node],
        profile: ReasoningProfile,
        edge_types: tuple[str, ...],
        causal_only: bool,
    ) -> bool:
        if edge_types and edge.edge_type not in edge_types:
            return False
        semantics = relation_semantics(edge.edge_type)
        if causal_only and not semantics.causal:
            return False
        if profile == ReasoningProfile.EVIDENCE_TRACE:
            return semantics.role == "evidence"
        allowed_node_types = _PROFILE_NODE_TYPES[profile]
        if not allowed_node_types:
            return True
        source = nodes_by_id.get(edge.from_node_id)
        target = nodes_by_id.get(edge.to_node_id)
        if source is None or target is None:
            return False
        return (
            source.node_type in allowed_node_types
            or target.node_type in allowed_node_types
        )

    @staticmethod
    def _candidate_edges(
        node_id: int,
        outgoing: dict[int, list[Edge]],
        incoming: dict[int, list[Edge]],
        direction: ReasoningDirection,
    ) -> list[tuple[Edge, int, str]]:
        candidates: list[tuple[Edge, int, str]] = []
        if direction in {ReasoningDirection.FORWARD, ReasoningDirection.BOTH}:
            candidates.extend(
                (edge, edge.to_node_id, "forward")
                for edge in outgoing.get(node_id, [])
            )
        if direction in {ReasoningDirection.BACKWARD, ReasoningDirection.BOTH}:
            candidates.extend(
                (edge, edge.from_node_id, "backward")
                for edge in incoming.get(node_id, [])
            )
        return sorted(
            candidates, key=lambda item: (item[0].kg_edge_id, item[1], item[2])
        )

    @staticmethod
    def _serialize_edge(edge: Edge) -> dict[str, Any]:
        semantics = relation_semantics(edge.edge_type)
        return {
            **edge.to_dict(),
            "reasoning": {
                "role": semantics.role,
                "causal": semantics.causal,
                "polarity": semantics.polarity,
            },
            "evidence": _edge_evidence(edge),
        }

    @staticmethod
    def _serialize_path(
        node_ids: list[int],
        edges: list[Edge],
        nodes_by_id: dict[int, Node],
        traversal_direction: str,
    ) -> dict[str, Any]:
        confidence = _path_confidence(edges)
        polarity = _path_polarity(edges)
        labels = [
            nodes_by_id[node_id].display_label or nodes_by_id[node_id].canonical_key
            for node_id in node_ids
        ]
        predicates = [edge.edge_type for edge in edges]
        explanation_parts = [labels[0]]
        for predicate, label in zip(predicates, labels[1:]):
            explanation_parts.extend((f" --{predicate}--> ", label))
        return {
            "node_ids": node_ids,
            "edge_ids": [edge.kg_edge_id for edge in edges],
            "predicates": predicates,
            "depth": len(edges),
            "confidence": confidence,
            "polarity": polarity,
            "polarity_label": {
                1: "promoting",
                -1: "inhibitory",
                0: "mixed_or_unspecified",
            }[polarity],
            "traversal_direction": traversal_direction,
            "evidence": [_edge_evidence(edge) for edge in edges],
            "explanation": "".join(explanation_parts),
        }
