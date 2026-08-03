from runtime.knowledge_graph import InMemoryGraphRepository
from runtime.knowledge_graph.adapters import DOMAIN_ADAPTERS, adapters_by_domain
from runtime.knowledge_graph.models import Node
from runtime.knowledge_graph.publisher import publish_domain


EXPECTED_DOMAINS = {
    "media", "occurrences", "geography", "habitat", "climate", "elevation",
    "traits", "glossary", "literature", "evidence", "pollinators",
    "mycorrhiza", "conservation", "molecular", "education",
}


def _seed_taxon(repo: InMemoryGraphRepository) -> None:
    repo.upsert_node(Node(
        kg_node_id=0,
        node_type="taxon",
        canonical_key="taxon:42",
        display_label="Cattleya labiata",
        source_table="taxonomy",
        source_pk="42",
    ))


def test_every_required_non_taxonomy_domain_has_an_adapter():
    assert set(adapters_by_domain()) == EXPECTED_DOMAINS
    assert len(DOMAIN_ADAPTERS) == len(EXPECTED_DOMAINS)


def test_every_adapter_is_idempotent_against_canonical_taxon():
    for adapter in DOMAIN_ADAPTERS:
        repo = InMemoryGraphRepository()
        _seed_taxon(repo)
        row = {
            "source_pk": f"{adapter.domain}-1",
            "taxon_pk": 42,
            "scientific_name": "Cattleya labiata",
            "title": f"{adapter.domain} evidence",
            "source_name": "test",
            "evidence_class": "test",
            "confidence_score": 1.0,
            "confidence_label": "high",
        }
        first = publish_domain(repo, adapter, [row])
        second = publish_domain(repo, adapter, [row])
        assert first.nodes_written == 1, adapter.domain
        assert first.edges_written == 1, adapter.domain
        assert second.nodes_written == 0, adapter.domain
        assert second.edges_written == 0, adapter.domain
        assert second.skipped_existing_nodes == 1, adapter.domain
        assert second.skipped_existing_edges == 1, adapter.domain
