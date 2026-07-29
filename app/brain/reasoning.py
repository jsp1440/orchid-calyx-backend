from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from runtime.knowledge_graph import Edge, GraphRepository, Node


class InferenceType(StrEnum):
    HABITAT_SIMILARITY = "habitat_similarity"
    POLLINATOR_SIMILARITY = "pollinator_similarity"
    CULTIVATION_SIMILARITY = "cultivation_similarity"
    CONSERVATION_RISK = "conservation_risk"
    EVOLUTIONARY_RELATIONSHIP = "evolutionary_relationship"
    PROBABLE_MYCORRHIZAL_PARTNER = "probable_mycorrhizal_partner"
    MISSING_ECOLOGICAL_INTERACTION = "missing_ecological_interaction"
    CLIMATE_COMPATIBILITY = "climate_compatibility"
    RESTORATION_SUITABILITY = "restoration_suitability"
    HYBRID_COMPATIBILITY = "hybrid_compatibility"
    LIKELY_FLOWERING_PERIOD = "likely_flowering_period"
    GEOGRAPHIC_EXPANSION = "geographic_expansion"
    UNDISCOVERED_POPULATION = "undiscovered_population"


@dataclass(frozen=True)
class InferenceRule:
    inference_type: InferenceType
    edge_types: tuple[str, ...]
    weight: float
    mode: str = "shared_target"


RULES = {
    InferenceType.HABITAT_SIMILARITY: InferenceRule(
        InferenceType.HABITAT_SIMILARITY, ("occurs_in", "has_habitat"), 0.90
    ),
    InferenceType.POLLINATOR_SIMILARITY: InferenceRule(
        InferenceType.POLLINATOR_SIMILARITY, ("has_pollinator",), 0.85
    ),
    InferenceType.CULTIVATION_SIMILARITY: InferenceRule(
        InferenceType.CULTIVATION_SIMILARITY, ("has_trait", "requires_climate"), 0.75
    ),
    InferenceType.CONSERVATION_RISK: InferenceRule(
        InferenceType.CONSERVATION_RISK,
        ("has_conservation_assessment", "threatened_by"),
        0.85,
        "direct",
    ),
    InferenceType.EVOLUTIONARY_RELATIONSHIP: InferenceRule(
        InferenceType.EVOLUTIONARY_RELATIONSHIP,
        ("belongs_to_genus", "belongs_to_section", "has_dna_sequence"),
        0.80,
    ),
    InferenceType.PROBABLE_MYCORRHIZAL_PARTNER: InferenceRule(
        InferenceType.PROBABLE_MYCORRHIZAL_PARTNER, ("has_mycorrhiza",), 0.70
    ),
    InferenceType.MISSING_ECOLOGICAL_INTERACTION: InferenceRule(
        InferenceType.MISSING_ECOLOGICAL_INTERACTION,
        ("has_pollinator", "has_mycorrhiza"),
        0.60,
    ),
    InferenceType.CLIMATE_COMPATIBILITY: InferenceRule(
        InferenceType.CLIMATE_COMPATIBILITY,
        ("occurs_in_climate", "requires_climate"),
        0.80,
    ),
    InferenceType.RESTORATION_SUITABILITY: InferenceRule(
        InferenceType.RESTORATION_SUITABILITY, ("occurs_in", "protected_by"), 0.65
    ),
    InferenceType.HYBRID_COMPATIBILITY: InferenceRule(
        InferenceType.HYBRID_COMPATIBILITY,
        ("belongs_to_section", "has_chromosome_count"),
        0.55,
    ),
    InferenceType.LIKELY_FLOWERING_PERIOD: InferenceRule(
        InferenceType.LIKELY_FLOWERING_PERIOD, ("flowers_during",), 0.75
    ),
    InferenceType.GEOGRAPHIC_EXPANSION: InferenceRule(
        InferenceType.GEOGRAPHIC_EXPANSION, ("occurs_in",), 0.55
    ),
    InferenceType.UNDISCOVERED_POPULATION: InferenceRule(
        InferenceType.UNDISCOVERED_POPULATION, ("occurs_in", "has_habitat"), 0.45
    ),
}


def _confidence(edge: Edge) -> float:
    return edge.confidence_score if edge.confidence_score is not None else 0.5


def _citation(edge: Edge) -> dict[str, Any]:
    payload = edge.payload or {}
    return {
        "edge_id": edge.kg_edge_id,
        "source_table": edge.source_table,
        "source_pk": edge.source_pk,
        "doi": payload.get("doi"),
        "citation": payload.get("citation"),
        "evidence_class": edge.evidence_class,
    }


class InferenceEngine:
    """Deterministic graph-pattern inference; never publishes conclusions."""

    def __init__(self, repository: GraphRepository) -> None:
        self.repository = repository

    def infer(
        self, subject_id: int, inference_type: InferenceType, *, limit: int = 25
    ) -> dict[str, Any]:
        subject = self.repository.get_node(subject_id)
        if subject is None:
            raise LookupError("NODE_NOT_FOUND")
        rule = RULES[inference_type]
        all_edges = sorted(
            self.repository.all_edges(), key=lambda edge: edge.kg_edge_id
        )
        relevant = [edge for edge in all_edges if edge.edge_type in rule.edge_types]
        subject_edges = [edge for edge in relevant if edge.from_node_id == subject_id]
        results = (
            self._direct(subject_edges, rule)
            if rule.mode == "direct"
            else self._shared(subject, subject_edges, relevant, rule)
        )
        results.sort(key=lambda item: (-item["confidence"], item["candidate_node_id"]))
        return {
            "subject": subject.to_dict(),
            "inference_type": inference_type.value,
            "rule": {
                "mode": rule.mode,
                "edge_types": list(rule.edge_types),
                "weight": rule.weight,
            },
            "results": results[:limit],
            "governance": {
                "status": "candidate_inference",
                "automatically_published": False,
                "human_review_required": True,
            },
        }

    def _direct(self, edges: list[Edge], rule: InferenceRule) -> list[dict[str, Any]]:
        return [
            self._result(edge.to_node_id, rule.weight * _confidence(edge), [edge], rule)
            for edge in edges
        ]

    def _shared(
        self,
        subject: Node,
        subject_edges: list[Edge],
        edges: list[Edge],
        rule: InferenceRule,
    ) -> list[dict[str, Any]]:
        by_target = {edge.to_node_id: edge for edge in subject_edges}
        candidates: dict[int, list[Edge]] = {}
        for edge in edges:
            shared = by_target.get(edge.to_node_id)
            if shared and edge.from_node_id != subject.kg_node_id:
                candidates.setdefault(edge.from_node_id, []).extend((shared, edge))
        output = []
        for candidate_id, evidence in candidates.items():
            unique = {edge.kg_edge_id: edge for edge in evidence}
            ordered = [unique[key] for key in sorted(unique)]
            score = rule.weight * min(_confidence(edge) for edge in ordered)
            output.append(self._result(candidate_id, score, ordered, rule))
        return output

    @staticmethod
    def _result(
        candidate_id: int, score: float, evidence: list[Edge], rule: InferenceRule
    ) -> dict[str, Any]:
        return {
            "candidate_node_id": candidate_id,
            "confidence": round(max(0.0, min(score, 1.0)), 6),
            "evidence": [edge.to_dict() for edge in evidence],
            "supporting_citations": [_citation(edge) for edge in evidence],
            "reasoning_chain": [
                {"step": 1, "kind": "rule", "value": rule.inference_type.value},
                {
                    "step": 2,
                    "kind": "matched_edges",
                    "value": [edge.kg_edge_id for edge in evidence],
                },
                {"step": 3, "kind": "candidate", "value": candidate_id},
            ],
        }
