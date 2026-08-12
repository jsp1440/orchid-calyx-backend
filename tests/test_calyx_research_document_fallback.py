from app.calyx_conversation.graph_literature_search import _research_document_matches


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = None
        self.params = None

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return list(self.rows)


def test_exact_binomial_document_fallback_preserves_nonclaim_boundary():
    cursor = FakeCursor([
        (
            77,
            "Pollination biology of Laelia anceps",
            "10.1000/example",
            2024,
            "article",
            "We studied Laelia anceps in Mexico.",
            "Laelia anceps; pollination",
        )
    ])
    results = _research_document_matches(
        cursor,
        ("Laelia anceps",),
        limit=5,
        seen_source_keys=set(),
    )
    assert len(results) == 1
    result = results[0]
    assert result["title"] == "Pollination biology of Laelia anceps"
    assert result["source_table"] == "public.research_documents"
    assert result["associated_taxa"] == ["Laelia anceps"]
    assert result["provenance"]["persisted_graph_edge"] is False
    assert result["provenance"]["scientific_claim_inferred"] is False
    assert "lower(coalesce(d.abstract,'')) like %s" in cursor.sql.lower()
    assert cursor.params[-1] == 5


def test_document_fallback_rejects_row_without_literal_binomial():
    cursor = FakeCursor([
        (78, "General orchid biology", None, 2020, "article", "No focal species here.", "orchids")
    ])
    results = _research_document_matches(
        cursor,
        ("Laelia anceps",),
        limit=5,
        seen_source_keys=set(),
    )
    assert results == []
