from runtime.knowledge_graph.scientific_method_vocabulary import (
    CLAIM_TYPE_TO_NODE_TYPE,
    SCIENTIFIC_METHOD_EDGE_TYPE_DOMAIN,
    SCIENTIFIC_METHOD_NODE_TYPE_DOMAIN,
)
from runtime.knowledge_graph.vocabulary import (
    domain_for_edge_type,
    domain_for_node_type,
)


def test_literature_claim_types_have_graph_node_semantics():
    assert CLAIM_TYPE_TO_NODE_TYPE["observation"] == "observation"
    assert CLAIM_TYPE_TO_NODE_TYPE["result"] == "result"
    assert CLAIM_TYPE_TO_NODE_TYPE["hypothesis"] == "hypothesis"
    assert CLAIM_TYPE_TO_NODE_TYPE["methodological"] == "method"
    assert CLAIM_TYPE_TO_NODE_TYPE["limitation"] == "limitation"
    assert CLAIM_TYPE_TO_NODE_TYPE["recommendation"] == "recommendation"


def test_scientific_method_nodes_are_registered_in_canonical_vocabulary():
    for node_type, domain in SCIENTIFIC_METHOD_NODE_TYPE_DOMAIN.items():
        assert domain_for_node_type(node_type) == domain


def test_scientific_method_edges_are_registered_in_canonical_vocabulary():
    for edge_type, domain in SCIENTIFIC_METHOD_EDGE_TYPE_DOMAIN.items():
        assert domain_for_edge_type(edge_type) == domain


def test_elevation_and_occurrence_relationships_remain_first_class_graph_semantics():
    assert domain_for_edge_type("occurs_at") == "occurrences"
    assert domain_for_edge_type("has_elevation") == "elevation"
    assert domain_for_node_type("occurrence") == "occurrences"
    assert domain_for_node_type("elevation") == "elevation"
