SUPPORTED_INPUTS = {"doi", "url", "file", "text"}


def certify_literature_ingestion(report: dict) -> dict:
    blockers: list[str] = []
    inputs = set(report.get("supported_inputs") or [])
    for input_type in sorted(SUPPORTED_INPUTS - inputs):
        blockers.append(f"INPUT:{input_type}:MISSING")

    if report.get("native_pdf_extraction") is not True:
        blockers.append("NATIVE_PDF_EXTRACTION_NOT_PROVEN")
    if report.get("scanned_pdf_detection") is not True:
        blockers.append("SCANNED_PDF_DETECTION_NOT_PROVEN")
    if report.get("ocr_route_available") is not True:
        blockers.append("OCR_ROUTE_NOT_AVAILABLE")
    if report.get("immutable_source_identity") is not True:
        blockers.append("IMMUTABLE_SOURCE_IDENTITY_NOT_PROVEN")
    if report.get("immutable_revision_identity") is not True:
        blockers.append("IMMUTABLE_REVISION_IDENTITY_NOT_PROVEN")
    if report.get("source_anchor_persistence") is not True:
        blockers.append("SOURCE_ANCHOR_PERSISTENCE_NOT_PROVEN")
    if report.get("source_hash_persistence") is not True:
        blockers.append("SOURCE_HASH_PERSISTENCE_NOT_PROVEN")
    if report.get("bounded_retry") is not True:
        blockers.append("BOUNDED_RETRY_NOT_PROVEN")
    if report.get("dead_letter") is not True:
        blockers.append("DEAD_LETTER_NOT_PROVEN")
    if report.get("owner_isolation") is not True:
        blockers.append("OWNER_ISOLATION_NOT_PROVEN")

    return {
        "certified": not blockers,
        "blockers": blockers,
        "candidate_generation_authorized": not blockers,
        "publication_authorized": False,
    }
