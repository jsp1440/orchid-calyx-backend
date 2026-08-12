from runtime.knowledge_graph.models import Node
from runtime.knowledge_graph.publisher import DomainAdapter, canonical_key, publish_domain
from runtime.knowledge_graph.repository import InMemoryGraphRepository

from tests.test_publication_eligible_paper_graph import _paper
from runtime.knowledge_graph.publication_eligible_paper_graph import (
    build_publication_eligible_paper_graph_specs,
)


def test_publication_eligible_bundle_uses_only_registered_graph_semantics():
    taxon_key = canonical_key("taxon", 42)
    taxon = Node(
        kg_node_id=1,
        node_type="taxon",
        canonical_key=taxon_key,
        display_label="Laelia anceps",
        source_table="taxonomy",
        source_pk="42",
    )
    repo = InMemoryGraphRepository(nodes=[taxon])
    bundle = build_publication_eligible_paper_graph_specs(
        _paper(),
        taxon_keys_by_entity_id={"taxon-1": taxon_key},
    )
    adapter = DomainAdapter(
        domain="scientific_method",
        source_table="literature_extraction.paper_knowledge",
        produce=lambda rows: (list(bundle.nodes), list(bundle.edges)),
    )

    result = publish_domain(repo, adapter, [{}])

    assert result.invalid == []
    assert result.nodes_written == len(bundle.nodes)
    assert result.edges_written == len(bundle.edges)
    edge_types = {edge.edge_type for edge in repo.all_edges()}
    assert "about_taxon" in edge_types
    assert "measurement_of" in edge_types
    assert "reports_result" in edge_types
    assert "supported_by_evidence" in edge_types
