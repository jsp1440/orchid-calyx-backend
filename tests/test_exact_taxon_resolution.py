from datetime import datetime, timezone

from app.literature_extraction.models import (
    AnalysisManifest,
    Entity,
    PaperKnowledge,
    PaperMetadata,
    Provenance,
    SourceDocument,
)
from runtime.knowledge_graph.exact_taxon_resolution import (
    resolve_exact_taxon_keys_with_cursor,
)


class FakeCursor:
    def __init__(self, rows_by_name):
        self.rows_by_name = rows_by_name
        self._rows = []
        self.queries = []

    def execute(self, sql, params):
        self.queries.append((sql, params))
        self._rows = list(self.rows_by_name.get(params[0], []))

    def fetchall(self):
        return list(self._rows)


def _entity(entity_id: str, name: str) -> Entity:
    return Entity(
        entity_id=entity_id,
        entity_type="taxon",
        name=name,
        normalized_name=name,
        provenance=Provenance(
            method="human_annotated",
            confidence=1.0,
            review_status="accepted",
        ),
    )


def _paper() -> PaperKnowledge:
    return PaperKnowledge(
        paper_id="paper-taxonomy-resolution",
        source=SourceDocument(
            content_hash="0123456789abcdef",
            media_type="application/pdf",
            original_filename="paper.pdf",
        ),
        metadata=PaperMetadata(title="Taxon resolution fixture"),
        entities=[
            _entity("e-resolved", "Laelia anceps"),
            _entity("e-ambiguous", "Example ambiguous"),
            _entity("e-missing", "Example missing"),
        ],
        analysis_manifest=AnalysisManifest(
            analysis_id="analysis-1",
            analysis_version=1,
            created_at=datetime.now(timezone.utc),
            pipeline_version="test",
            status="completed",
        ),
    )


def test_exact_taxon_resolution_requires_one_active_graph_match():
    cursor = FakeCursor(
        {
            "Laelia anceps": [("taxon:42",)],
            "Example ambiguous": [("taxon:51",), ("taxon:52",)],
            "Example missing": [],
        }
    )

    result = resolve_exact_taxon_keys_with_cursor(cursor, _paper())

    assert result.keys_by_entity_id == {"e-resolved": "taxon:42"}
    assert result.ambiguous_entity_ids == ("e-ambiguous",)
    assert result.unresolved_entity_ids == ("e-missing",)
    assert result.resolved_count == 1
    assert all("node_type = 'taxon'" in sql for sql, _ in cursor.queries)
    assert all("is_active" in sql for sql, _ in cursor.queries)
    assert all("lower(display_label) = lower(%s)" in sql for sql, _ in cursor.queries)
    assert all("LIMIT 2" in sql for sql, _ in cursor.queries)
