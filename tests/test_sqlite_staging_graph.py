from runtime.knowledge_graph.models import Edge, Node
from runtime.knowledge_graph.sqlite_staging import SqliteStagingGraphRepository


def test_sqlite_staging_persists_and_deduplicates(tmp_path):
    path = str(tmp_path / "staging.sqlite3")
    repo = SqliteStagingGraphRepository(path)
    taxon = repo.upsert_node(Node(0, "taxon", "taxon:1", "Test orchid", "taxonomy", "1", None, None, None, {}))
    evidence = repo.upsert_node(Node(0, "image", "image:10", "Image", "media", "10", None, None, None, {}))
    repo.upsert_edge(Edge(0, "has_image", taxon.kg_node_id, evidence.kg_node_id, "media", "10", None, None, None, None, {}))

    reopened = SqliteStagingGraphRepository(path)
    before = reopened.counts()
    reopened.upsert_node(Node(0, "image", "image:10", "Image", "media", "10", None, None, None, {}))
    reopened.upsert_edge(Edge(0, "has_image", taxon.kg_node_id, evidence.kg_node_id, "media", "10", None, None, None, None, {}))
    assert reopened.counts() == before == {"nodes": 2, "edges": 1}
    assert len(reopened.all_edges()) == 1
