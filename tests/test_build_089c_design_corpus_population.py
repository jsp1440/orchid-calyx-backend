from pathlib import Path

from app.design_intelligence import (
    DesignCorpusPopulationService,
    DesignIntelligenceService,
    DesignReasoningService,
    MemoryDesignCorpusRepository,
    ProvenanceBinding,
)


def _service():
    corpus = MemoryDesignCorpusRepository()
    return corpus, DesignCorpusPopulationService(DesignIntelligenceService(corpus), DesignReasoningService())


def test_authoritative_archive_inventory_is_complete():
    root = Path("corpus/design_intelligence/build-089c")
    files = DesignCorpusPopulationService.inventory(root)
    assert len(files) == 47
    assert sum(item.supported for item in files) == 42
    assert sum(not item.supported for item in files) == 5
    assert {item.path.suffix.casefold() for item in files if item.supported} == {".md", ".docx"}
    assert all(item.reason and item.correction for item in files if not item.supported)


def test_population_reuses_review_publication_provenance_and_reasoning(tmp_path):
    (tmp_path / "guide.md").write_text("# Dashboard guidance\nUse accessible contrast. This pattern supports usability.", encoding="utf-8")
    corpus, service = _service()
    report = service.populate(tmp_path, lambda _: ProvenanceBinding(1, 2, (3,), (4,)))
    assert report["documents_imported"] == 1
    assert report["documents_skipped"] == 0
    assert report["semantic_units"] >= 2
    assert report["semantic_units"] == report["embeddings"]
    assert report["provenance_coverage"] == 1.0
    assert corpus.published_latest()[0].provenance.evidence_link_ids == (4,)
    assert len(corpus.reviews) == len(corpus.publication_events) == 1


def test_validation_preserves_duplicates_conflicts_and_metadata_findings(tmp_path):
    (tmp_path / "a.md").write_text("This recommendation contradicts another rule.\n\nRepeated guidance.", encoding="utf-8")
    (tmp_path / "b.md").write_text("Repeated guidance.", encoding="utf-8")
    _, service = _service()
    counter = iter(range(10, 20))
    report = service.populate(tmp_path, lambda _: ProvenanceBinding(next(counter), next(counter), (next(counter),)))
    assert report["duplicates"] >= 1
    assert {finding["code"] for finding in report["findings"]} >= {"MISSING_AUTHOR_METADATA", "MISSING_REUSE_LICENSE", "MISSING_INLINE_CITATION"}
    assert report["documents_imported"] == 2


def test_retrieval_results_include_required_evidence_fields(tmp_path):
    (tmp_path / "ux.md").write_text("UX usability guidance should preserve accessibility and reduced motion.", encoding="utf-8")
    _, service = _service()
    report = service.populate(tmp_path, lambda _: ProvenanceBinding(1, 2, (3,)))
    result = report["retrieval"]["UX guidance"]["results"][0]
    assert result["supporting_citations"]
    assert result["provenance"]
    assert "confidence" in result and "classification" in result and "related_concepts" in result
