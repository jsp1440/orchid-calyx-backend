from app.calyx_conversation.graph_literature_search import (
    MAX_QUERY_TERMS,
    lexical_terms,
    search_persisted_literature,
)


def test_lexical_terms_are_bounded_and_do_not_expand_synonyms():
    terms = lexical_terms(
        "What does the literature say about foliar nutrient uptake through orchid leaves and mineral absorption?"
    )
    assert terms[:4] == ("foliar", "nutrient", "uptake", "leaves")
    assert "orchid" not in terms
    assert len(terms) <= MAX_QUERY_TERMS


def test_search_without_meaningful_terms_is_not_requested():
    report = search_persisted_literature("What does this say about orchids?", dsn="")
    assert report["status"] == "not_requested"
    assert report["results"] == []
    assert report["knowledge_graph_mutation"] is False


def test_search_with_terms_and_no_database_reports_unavailable():
    report = search_persisted_literature("foliar nutrient uptake", dsn="")
    assert report["status"] == "unavailable"
    assert report["reason"] == "DATABASE_URL_NOT_CONFIGURED"
    assert report["terms"] == ["foliar", "nutrient", "uptake"]


def test_search_returns_publication_metadata_and_taxon_links(monkeypatch):
    class Cursor:
        def __init__(self):
            self.last_sql = ""
            self.params = ()
            self.phase = "search"

        def execute(self, sql, params=()):
            self.last_sql = " ".join(sql.split())
            self.params = tuple(params)
            self.phase = "taxa" if "JOIN oc_graph.kg_nodes t" in self.last_sql else "search"

        def fetchall(self):
            if self.phase == "taxa":
                return [("Laelia anceps",), ("Phalaenopsis aphrodite",)]
            return [
                (
                    101,
                    "Foliar nutrient uptake in epiphytic orchids",
                    "oc_graph.taxon_literature_edges",
                    "22",
                    "normalized",
                    0.91,
                    "high",
                    {"doi": "10.1000/example", "year": 2020, "edge_strength": 0.8},
                )
            ]

    class Connection:
        def __init__(self):
            self.cursor_obj = Cursor()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def cursor(self):
            return CursorContext(self.cursor_obj)

    class CursorContext:
        def __init__(self, cursor):
            self.cursor_obj = cursor

        def __enter__(self):
            return self.cursor_obj

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "app.calyx_conversation.graph_literature_search.psycopg.connect",
        lambda *args, **kwargs: Connection(),
    )

    report = search_persisted_literature(
        "foliar nutrient uptake",
        dsn="postgresql://example",
    )
    assert report["status"] == "available"
    assert report["result_count"] == 1
    item = report["results"][0]
    assert item["title"] == "Foliar nutrient uptake in epiphytic orchids"
    assert item["doi"] == "10.1000/example"
    assert item["associated_taxa"] == ["Laelia anceps", "Phalaenopsis aphrodite"]
    assert item["provenance"]["relationship"] == "documented_by"
