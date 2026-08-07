import pytest

from app.multimodal_intelligence.document_adapter import (
    document_record_from_intelligence,
)


def test_completed_document_intelligence_record_adapts_to_pages() -> None:
    record = {
        "revision_id": 42,
        "metadata": {
            "title": "Orchid morphology",
            "canonical_uri": "urn:orchid:paper:42",
        },
        "text": "First page evidence.\fSecond page evidence.",
    }
    run = {"revision_id": 42, "extraction_run_id": 42, "state": "COMPLETED"}
    document = document_record_from_intelligence(record, run)
    assert document.source_id == "document-intelligence:revision:42"
    assert document.title == "Orchid morphology"
    assert len(document.pages) == 2
    assert document.pages[1].page_number == 2
    assert len(document.content_hash) == 64


def test_incomplete_extraction_fails_closed() -> None:
    record = {"revision_id": 42, "metadata": {"title": "Paper"}, "text": "Evidence"}
    run = {"revision_id": 42, "state": "CANCELLED"}
    with pytest.raises(ValueError, match="EXTRACTION_NOT_COMPLETED"):
        document_record_from_intelligence(record, run)


def test_revision_mismatch_fails_closed() -> None:
    record = {"revision_id": 42, "metadata": {"title": "Paper"}, "text": "Evidence"}
    run = {"revision_id": 43, "state": "COMPLETED"}
    with pytest.raises(ValueError, match="REVISION_MISMATCH"):
        document_record_from_intelligence(record, run)
