from types import SimpleNamespace

from app.calyx_conversation.graph_context import (
    explicit_taxon_names,
    graph_context_for_message,
)


def test_explicit_taxon_names_are_exact_binomials_only():
    assert explicit_taxon_names(
        "Compare Laelia anceps with Cattleya skinneri, then Laelia anceps again."
    ) == ("Laelia anceps", "Cattleya skinneri")
    assert explicit_taxon_names("Tell me about foliar feeding in orchids") == ()
    assert explicit_taxon_names("Could this be Laelia Anceps?") == ()


def test_graph_context_without_taxon_does_not_touch_database():
    report = graph_context_for_message("What does the literature say about foliar nutrition?", dsn="")
    assert report["status"] == "not_requested"
    assert report["requested_taxa"] == []
    assert report["knowledge_graph_mutation"] is False


def test_graph_context_reports_unavailable_when_database_missing():
    report = graph_context_for_message("Tell me about Laelia anceps", dsn="")
    assert report["status"] == "unavailable"
    assert report["reason"] == "DATABASE_URL_NOT_CONFIGURED"
    assert report["requested_taxa"] == ["Laelia anceps"]


def test_graph_context_returns_bounded_persisted_traversal(monkeypatch):
    focal = SimpleNamespace(kg_node_id=77)

    class FakeRepo:
        def __init__(self, dsn):
            assert dsn == "postgresql://example"

        def get_node(self, node_id):
            assert node_id == 77
            return focal

    monkeypatch.setattr(
        "app.calyx_conversation.graph_context.PostgresGraphRepository",
        FakeRepo,
    )
    monkeypatch.setattr(
        "app.calyx_conversation.graph_context._resolve_taxon_node_id",
        lambda dsn, name: 77 if name == "Laelia anceps" else None,
    )
    monkeypatch.setattr(
        "app.calyx_conversation.graph_context.traverse",
        lambda repo, node, depth, limit, offset: {
            "focal_node": {"kg_node_id": 77, "display_label": "Laelia anceps"},
            "nodes": [{"kg_node_id": 91, "node_type": "publication"}],
            "edges": [{"edge_type": "documented_by", "from_node_id": 77, "to_node_id": 91}],
            "node_types": ["taxon", "publication"],
            "edge_types": ["documented_by"],
            "domain_coverage": {"literature": 1},
            "data_gaps": [],
            "pagination": {"limit": limit, "offset": offset, "truncated": False},
        },
    )

    report = graph_context_for_message(
        "Tell me about Laelia anceps",
        dsn="postgresql://example",
        limit=20,
    )
    assert report["status"] == "available"
    assert report["found_taxa"] == 1
    assert report["resolution_policy"] == "explicit_binomial_exact_display_label_only"
    taxon = report["taxa"][0]
    assert taxon["scientific_name"] == "Laelia anceps"
    assert taxon["edge_types"] == ["documented_by"]
    assert taxon["domain_coverage"] == {"literature": 1}
