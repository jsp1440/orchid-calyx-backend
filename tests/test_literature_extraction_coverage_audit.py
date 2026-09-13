from __future__ import annotations

from datetime import datetime, timezone

from app.literature_extraction.coverage_audit import (
    _paper_coverage,
    audit_literature_extraction_coverage,
)
from app.literature_extraction.models import (
    AnalysisManifest,
    Entity,
    Identifier,
    PaperKnowledge,
    PaperMetadata,
    Provenance,
    SourceDocument,
)
from app.literature_extraction.repository import LiteratureResultRepository


def _paper(*, status: str = "completed") -> PaperKnowledge:
    return PaperKnowledge(
        paper_id="paper-a",
        source=SourceDocument(
            content_hash="sha256:0123456789abcdef",
            media_type="application/pdf",
            original_filename="paper.pdf",
        ),
        metadata=PaperMetadata(title="Orchid study"),
        entities=[
            Entity(
                entity_id="entity:taxon",
                entity_type="taxon",
                name="Phalaenopsis amabilis",
                external_ids=[Identifier(scheme="other", value="taxon:123")],
                provenance=Provenance(method="source_reported", confidence=1.0),
            )
        ],
        analysis_manifest=AnalysisManifest(
            analysis_id="analysis:paper-a:1",
            analysis_version=1,
            created_at=datetime.now(timezone.utc),
            pipeline_version="0.1.0",
            status=status,
        ),
    )


def test_taxon_binding_does_not_imply_successful_extraction() -> None:
    coverage = _paper_coverage(
        _paper(status="failed"), full_text_available=True, kg_doi_index=None
    )
    assert coverage.taxonomically_bound is True
    assert coverage.extracted is False
    assert coverage.kg_materialized is None


def test_database_unavailable_is_not_reported_as_absence_or_graph_zero(tmp_path) -> None:
    repository = LiteratureResultRepository(tmp_path / "missing")
    result = audit_literature_extraction_coverage(None, repository)
    assert result["graph_mutation"] is False
    assert result["discovered_corpus"]["measurement"]["state"] == "unavailable"
    assert result["extraction_pipeline"]["kg_materialized"] == 0
    assert result["extraction_pipeline"]["papers_examined"] == 0


def test_repository_listing_skips_partial_bundles(tmp_path) -> None:
    repository = LiteratureResultRepository(tmp_path)
    (tmp_path / "partial").mkdir()
    assert repository.root_available() is True
    assert repository.list_paper_ids() == []
