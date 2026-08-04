from runtime.calyx_certification.literature_ingestion import (
    certify_literature_ingestion,
)


def _report():
    return {
        "supported_inputs": ["doi", "url", "file", "text"],
        "native_pdf_extraction": True,
        "scanned_pdf_detection": True,
        "ocr_route_available": True,
        "immutable_source_identity": True,
        "immutable_revision_identity": True,
        "source_anchor_persistence": True,
        "source_hash_persistence": True,
        "bounded_retry": True,
        "dead_letter": True,
        "owner_isolation": True,
    }


def test_complete_ingestion_report_certifies_candidate_generation_only():
    result = certify_literature_ingestion(_report())
    assert result["certified"] is True
    assert result["candidate_generation_authorized"] is True
    assert result["publication_authorized"] is False


def test_missing_ocr_and_hash_fail_closed():
    report = _report()
    report["ocr_route_available"] = False
    report["source_hash_persistence"] = False
    result = certify_literature_ingestion(report)
    assert result["certified"] is False
    assert "OCR_ROUTE_NOT_AVAILABLE" in result["blockers"]
    assert "SOURCE_HASH_PERSISTENCE_NOT_PROVEN" in result["blockers"]
