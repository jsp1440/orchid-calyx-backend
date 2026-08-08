from __future__ import annotations

from app.brain.reasoning_map import relation_semantics
from runtime.knowledge_graph import Edge, InMemoryGraphRepository, Node
from runtime.knowledge_graph.causal_vocabulary import (
    CAUSAL_REASONING_NODE_TYPES,
    causal_relation_semantics,
)
from runtime.knowledge_graph.validation import validate_graph
from runtime.knowledge_graph.vocabulary import (
    EDGE_TYPE_DOMAIN,
    NODE_TYPE_DOMAIN,
    domain_for_edge_type,
    domain_for_node_type,
)


def node(node_id: int, node_type: str, source_pk: str) -> Node:
    return Node(
        node_id,
        node_type,
        f"{node_type}:{source_pk}",
        source_pk,
        "build_614_fixture",
        source_pk,
        "curated",
        0.9,
        "high",
    )


def causal_graph() -> InMemoryGraphRepository:
    return InMemoryGraphRepository(
        nodes=[
            node(1, "gene", "g1"),
            node(2, "protein", "p1"),
            node(3, "cell", "c1"),
            node(4, "physiology", "water-balance"),
            node(5, "developmental_process", "leaf-expansion"),
            node(6, "phenotype", "leaf-size"),
            node(7, "environment", "high-vpd"),
        ],
        edges=[
            Edge(1, "activates", 1, 2, "build_614_claims", "e1", "curated", 0.9),
            Edge(2, "regulates", 2, 3, "build_614_claims", "e2", "curated", 0.8),
            Edge(3, "promotes", 3, 4, "build_614_claims", "e3", "curated", 0.8),
            Edge(4, "promotes", 4, 5, "build_614_claims", "e4", "curated", 0.7),
            Edge(5, "results_in", 5, 6, "build_614_claims", "e5", "curated", 0.7),
            Edge(6, "inhibits", 7, 4, "build_614_claims", "e6", "curated", 0.85),
        ],
    )


def test_scientific_mechanism_node_types_are_canonical_graph_vocabulary():
    expected = {
        "gene": "molecular",
        "protein": "molecular",
        "cell": "anatomy",
        "physiology": "physiology",
        "developmental_process": "development",
        "phenotype": "phenotype",
        "environment": "environment",
        "plant": "cultivation",
        "specimen": "cultivation",
    }
    for node_type, domain in expected.items():
        assert NODE_TYPE_DOMAIN[node_type] == domain
        assert domain_for_node_type(node_type) == domain
        assert node_type in CAUSAL_REASONING_NODE_TYPES


def test_causal_relations_are_canonical_and_share_brain_semantics():
    expected = {
        "promotes": ("causal", 1, True),
        "inhibits": ("causal", -1, True),
        "regulates": ("regulatory", 0, True),
        "supports": ("evidence", 1, False),
        "contradicts": ("evidence", -1, False),
    }
    for edge_type, values in expected.items():
        controlled = causal_relation_semantics(edge_type)
        assert controlled is not None
        brain = relation_semantics(edge_type)
        assert (brain.role, brain.polarity, brain.causal) == values
        assert edge_type in EDGE_TYPE_DOMAIN


def test_legacy_evidence_domains_are_preserved_while_semantics_are_shared():
    assert domain_for_edge_type("documented_by") == "literature"
    assert domain_for_edge_type("supported_by_evidence") == "evidence"
    assert relation_semantics("documented_by").role == "evidence"
    assert relation_semantics("supported_by_evidence").polarity == 1


def test_cross_scale_causal_graph_passes_canonical_validation():
    report = validate_graph(causal_graph())
    assert report["vocabulary_compliance"]["compliant"] is True
    assert report["cross_domain_consistency"]["mismatched_endpoint_edges"] == 0
    assert report["cross_domain_consistency"]["causal_edges_checked"] == 6
    assert report["domain_breakdown"]["causal_reasoning"]["edges"] == 6
    assert report["healthy"] is True


def test_causal_edge_with_unapproved_endpoint_fails_validation():
    repo = InMemoryGraphRepository(
        nodes=[
            node(1, "gene", "g1"),
            node(2, "image", "image1"),
        ],
        edges=[Edge(1, "promotes", 1, 2, "build_614_claims", "e1", "curated", 0.9)],
    )
    report = validate_graph(repo)
    assert report["cross_domain_consistency"]["mismatched_endpoint_edges"] == 1
    assert "invalid_causal_target" in report["cross_domain_consistency"]["examples"][0]
    assert report["healthy"] is False


def test_unknown_relationship_remains_context_and_noncanonical():
    assert causal_relation_semantics("mystery_relation") is None
    assert relation_semantics("mystery_relation").role == "context"
    assert domain_for_edge_type("mystery_relation") == "unknown"
