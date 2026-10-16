from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.literature_extraction.ingest import build_empty_paper, ingest_text
from app.literature_extraction.models import (
    NormalizedEvidenceRecord,
    Provenance,
    PublicationDecision,
    ReconciliationRelation,
    ReviewDecision,
    ReviewItem,
)
from app.literature_extraction.output import build_metrics


def test_build_metrics_includes_review_and_reconciliation_counts(
    tmp_path: Path,
) -> None:
    """Test that metrics includes normalized_evidence_records, reconciliation_relations,
    review_items, review_decisions, and publication_decisions counts."""
    source = tmp_path / "sample.txt"
    source.write_text(
        "Orchid Study\n\nResults\nCattleya labiata flowers are pollinated by bees.\n"
        "Cattleya labiata flowers are pollinated by bees.\n",
        encoding="utf-8",
    )

    document = ingest_text(source)
    paper = build_empty_paper(document)

    # Add 2 normalized evidence records
    provenance = Provenance(
        method="rule_extracted",
        extractor="test",
        extractor_version="1.0.0",
        confidence=0.9,
    )
    paper.normalized_evidence_records = [
        NormalizedEvidenceRecord(
            record_id="record-1",
            source_claim_id="claim-1",
            statement="Cattleya labiata flowers are pollinated by bees.",
            normalized_statement="Cattleya labiata is pollinated by bees",
            domain="ecological_interaction",
            extraction_confidence=0.9,
            normalization_confidence=0.85,
            provenance=provenance,
        ),
        NormalizedEvidenceRecord(
            record_id="record-2",
            source_claim_id="claim-2",
            statement="Cattleya labiata flowers are pollinated by bees.",
            normalized_statement="Cattleya labiata is pollinated by bees",
            domain="ecological_interaction",
            extraction_confidence=0.9,
            normalization_confidence=0.85,
            provenance=provenance,
        ),
    ]

    # Add 1 reconciliation relation
    paper.reconciliation_relations = [
        ReconciliationRelation(
            relation_id="recon-1",
            subject_record_id="record-1",
            object_record_id="record-2",
            relation_type="duplicate",
            reason="Both records describe the same pollination fact",
        ),
    ]

    # Add 2 review items
    paper.review_items = [
        ReviewItem(
            review_item_id="review-1",
            source_record_id="record-1",
            priority=1,
            source_record_fingerprint="fingerprint-1",
        ),
        ReviewItem(
            review_item_id="review-2",
            source_record_id="record-2",
            priority=1,
            source_record_fingerprint="fingerprint-2",
        ),
    ]

    # Leave review_decisions and publication_decisions empty
    paper.review_decisions = []
    paper.publication_decisions = []

    metrics = build_metrics(paper)

    # Assert the new fields are present with correct counts
    assert metrics["normalized_evidence_records"] == 2
    assert metrics["reconciliation_relations"] == 1
    assert metrics["review_items"] == 2
    assert metrics["review_decisions"] == 0
    assert metrics["publication_decisions"] == 0

    # Assert all previous keys are still present
    assert "paper_id" in metrics
    assert "analysis_id" in metrics
    assert "status" in metrics
    assert "extractor_runs" in metrics
    assert "failed_extractors" in metrics
    assert "sections" in metrics
    assert "entities" in metrics
    assert "glossary_terms" in metrics
    assert "measurements" in metrics
    assert "claims" in metrics
    assert "evidence" in metrics
    assert "relationships" in metrics
    assert "figures" in metrics
    assert "tables" in metrics
    assert "references" in metrics
    assert "unknown_terms" in metrics


def test_build_metrics_with_populated_review_decisions(tmp_path: Path) -> None:
    """Test that metrics correctly counts review_decisions and publication_decisions."""
    source = tmp_path / "sample.txt"
    source.write_text("Orchid Study\n\nResults\nTest content.\n", encoding="utf-8")

    document = ingest_text(source)
    paper = build_empty_paper(document)

    provenance = Provenance(
        method="rule_extracted",
        extractor="test",
        extractor_version="1.0.0",
        confidence=0.9,
    )

    # Add normalized evidence record
    paper.normalized_evidence_records = [
        NormalizedEvidenceRecord(
            record_id="record-1",
            source_claim_id="claim-1",
            statement="Test content.",
            normalized_statement="Test content",
            domain="other",
            extraction_confidence=0.9,
            normalization_confidence=0.85,
            provenance=provenance,
        ),
    ]

    # Add review item
    paper.review_items = [
        ReviewItem(
            review_item_id="review-1",
            source_record_id="record-1",
            priority=0,
            source_record_fingerprint="fingerprint-1",
        ),
    ]

    # Add review decision
    paper.review_decisions = [
        ReviewDecision(
            decision_id="decision-1",
            review_item_id="review-1",
            decision="accept",
            reviewer_id="reviewer-1",
            decided_at=datetime.now(timezone.utc),
            source_record_fingerprint="fingerprint-1",
        ),
    ]

    # Add publication decision
    paper.publication_decisions = [
        PublicationDecision(
            publication_decision_id="pub-decision-1",
            review_item_id="review-1",
            source_record_id="record-1",
            status="eligible_for_publication",
        ),
    ]

    metrics = build_metrics(paper)

    assert metrics["normalized_evidence_records"] == 1
    assert metrics["review_items"] == 1
    assert metrics["review_decisions"] == 1
    assert metrics["publication_decisions"] == 1
    assert metrics["reconciliation_relations"] == 0
