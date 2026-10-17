"""LANDSCAPE-001: design guidance is imported as a draft and surfaces only after review.

All tests use the in-memory repositories. Nothing touches a database.
"""

import json
import shutil
from pathlib import Path

import pytest

from app.design_intelligence import (
    DesignIntelligenceService,
    DesignReasoningService,
    DesignReviewDecision,
    LandscapeGuidanceImporter,
    MemoryDesignCorpusRepository,
    ProvenanceBinding,
    PublicationStatus,
    ReviewState,
)
from app.design_intelligence.service import DesignSearchQuery

ROOT = Path("corpus/design_intelligence/landscape-001")
BINDING = ProvenanceBinding(11, 12, (13,), (14,))


def _build():
    corpus = DesignIntelligenceService(MemoryDesignCorpusRepository())
    reasoning = DesignReasoningService()
    return corpus, reasoning, LandscapeGuidanceImporter(corpus, reasoning)


def test_manifest_matches_guidance_and_declares_no_authority():
    manifest = LandscapeGuidanceImporter.load_manifest(ROOT)
    assert manifest["evidence_class"] == "non_scientific_design_guidance"
    assert manifest["auto_review_or_publish"] is False
    assert manifest["publicly_redistributable"] is False
    assert len(manifest["guidance_record_ids"]) == 20
    text = (ROOT / manifest["guidance_file"]).read_text(encoding="utf-8")
    for record_id in manifest["guidance_record_ids"]:
        assert f"## {record_id}:" in text


def test_import_is_a_pending_draft_with_exact_provenance_and_blocked_redistribution():
    corpus, _, importer = _build()
    document = importer.import_pending(ROOT, BINDING)
    repository = corpus.repository
    assert repository.review_state(document.document_id) is ReviewState.PENDING
    assert (
        repository.publication_status(document.document_id) is PublicationStatus.DRAFT
    )
    assert repository.published_latest() == []
    assert document.provenance.anchor_ids == (13,)
    assert document.license_metadata["publicly_redistributable"] is False
    assert (
        document.source_metadata["evidence_class"] == "non_scientific_design_guidance"
    )
    assert len(repository.reviews) == len(repository.publication_events) == 0


def test_placeholder_provenance_is_refused():
    _, _, importer = _build()
    with pytest.raises(ValueError, match="DESIGN_EXACT_PROVENANCE_REQUIRED"):
        importer.import_pending(ROOT, ProvenanceBinding(0, 0, ()))


def test_unreviewed_guidance_is_not_retrievable_by_either_search_path():
    _, reasoning, importer = _build()
    document = importer.import_pending(ROOT, BINDING)
    with pytest.raises(
        ValueError, match="LANDSCAPE_INDEX_REQUIRES_APPROVED_PUBLISHED_DOCUMENT"
    ):
        importer.index_after_publication(document.document_id)
    assert reasoning.repository.units == []
    assert reasoning.search("relationship uncertainty evidence")["results"] == []


def test_rejected_guidance_cannot_be_published_or_indexed():
    corpus, _, importer = _build()
    document = importer.import_pending(ROOT, BINDING)
    corpus.review(
        document.document_id,
        DesignReviewDecision(ReviewState.REJECTED, "curator", "Not accepted."),
    )
    with pytest.raises(ValueError, match="DESIGN_REVIEW_APPROVAL_REQUIRED"):
        corpus.publish(document.document_id, "curator", "Attempt.")
    with pytest.raises(
        ValueError, match="LANDSCAPE_INDEX_REQUIRES_APPROVED_PUBLISHED_DOCUMENT"
    ):
        importer.index_after_publication(document.document_id)


def test_after_named_review_and_publication_guidance_is_retrievable_with_provenance():
    corpus, reasoning, importer = _build()
    document = importer.import_pending(ROOT, BINDING)
    corpus.review(
        document.document_id,
        DesignReviewDecision(
            ReviewState.APPROVED, "named-curator", "Reviewed against primary sources."
        ),
    )
    corpus.publish(
        document.document_id, "named-curator", "Approved for internal design retrieval."
    )
    units = importer.index_after_publication(document.document_id)
    assert units and len(importer.index_after_publication(document.document_id)) == len(
        units
    )
    result = reasoning.search("unknown conservation status is not safety")["results"][0]
    assert result["supporting_citations"] and result["provenance"]
    found = corpus.search(DesignSearchQuery("relationship evidence uncertainty"))
    assert found["total"] == 1
    assert (
        found["results"][0]["source_metadata"]["evidence_class"]
        == "non_scientific_design_guidance"
    )


def test_guidance_text_carries_the_scientific_boundary_and_no_authority_language():
    text = (ROOT / "LANDSCAPE-001-guidance.md").read_text(encoding="utf-8")
    assert "not scientific evidence" in text
    assert "canonical object governs" in text
    assert "Do not add a ninth" in text
    assert "never authorizes publication" in text


def test_tampered_guidance_is_refused(tmp_path):
    shutil.copytree(ROOT, tmp_path / "pkg")
    target = tmp_path / "pkg" / "LANDSCAPE-001-guidance.md"
    target.write_text(
        target.read_text(encoding="utf-8") + "\nInjected line.\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="LANDSCAPE_GUIDANCE_HASH_MISMATCH"):
        LandscapeGuidanceImporter.load_manifest(tmp_path / "pkg")


def test_manifest_that_enables_auto_publication_is_refused(tmp_path):
    shutil.copytree(ROOT, tmp_path / "pkg")
    path = tmp_path / "pkg" / "MANIFEST.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["auto_review_or_publish"] = True
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match="LANDSCAPE_AUTO_PUBLICATION_FORBIDDEN"):
        LandscapeGuidanceImporter.load_manifest(tmp_path / "pkg")
