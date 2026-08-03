from runtime.knowledge_graph import InMemoryGraphRepository
from runtime.knowledge_graph.adapters import IMAGES_ADAPTER
from runtime.knowledge_graph.controlled_dry_run import (
    publication_authorization_payload,
    run_controlled_dry_run,
)
from runtime.knowledge_graph.models import Node
from runtime.knowledge_graph.sources import InMemorySourceProvider


def _graph_with_taxon() -> InMemoryGraphRepository:
    repo = InMemoryGraphRepository()
    repo.upsert_node(Node(
        kg_node_id=1,
        node_type="taxon",
        canonical_key="taxon:42",
        display_label="Cattleya labiata",
        source_table="public.taxonomy_species",
        source_pk="42",
    ))
    return repo


def test_controlled_dry_run_requires_zero_delta_and_full_coverage():
    source = InMemorySourceProvider({
        "media": [{
            "source_pk": "image-1",
            "taxon_pk": 42,
            "caption": "flower",
            "media_url": "https://example.org/image.jpg",
        }]
    })
    report = run_controlled_dry_run(
        _graph_with_taxon(), source, adapters=(IMAGES_ADAPTER,), max_rows_per_domain=10
    )
    assert report["graph_mutation"] is False
    assert report["zero_delta"] is True
    assert report["full_coverage"] is True
    assert report["totals"]["first_nodes"] == 1
    assert report["totals"]["first_edges"] == 1
    assert report["totals"]["second_nodes"] == 0
    assert report["totals"]["second_edges"] == 0
    assert report["publication_authorization_ready"] is True

    authorization = publication_authorization_payload(report)
    assert authorization["ready_for_owner_decision"] is True
    assert authorization["authorized"] is False
    assert authorization["production_write_executed"] is False


def test_truncated_dry_run_cannot_request_publication_authorization():
    source = InMemorySourceProvider({
        "media": [
            {"source_pk": f"image-{i}", "taxon_pk": 42, "media_url": f"https://example.org/{i}.jpg"}
            for i in range(3)
        ]
    })
    report = run_controlled_dry_run(
        _graph_with_taxon(), source, adapters=(IMAGES_ADAPTER,), max_rows_per_domain=1
    )
    assert report["zero_delta"] is True
    assert report["full_coverage"] is False
    assert report["truncated_domains"] == ["media"]
    assert report["publication_authorization_ready"] is False
    authorization = publication_authorization_payload(report)
    assert "truncated:media" in authorization["blockers"]
