from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .integration import DocumentPage, DocumentRecord


def document_record_from_intelligence(
    record: Mapping[str, Any],
    extraction_run: Mapping[str, Any],
) -> DocumentRecord:
    """Adapt immutable Document Intelligence output without mutating its store."""
    revision_id = int(record.get("revision_id") or 0)
    run_revision_id = int(extraction_run.get("revision_id") or 0)
    if revision_id <= 0 or revision_id != run_revision_id:
        raise ValueError("DOCUMENT_INTELLIGENCE_REVISION_MISMATCH")
    if extraction_run.get("state") != "COMPLETED":
        raise ValueError("DOCUMENT_INTELLIGENCE_EXTRACTION_NOT_COMPLETED")

    metadata = record.get("metadata") or {}
    title = str(metadata.get("title") or metadata.get("filename") or f"revision-{revision_id}")
    text = str(record.get("text") or "")
    if not text.strip():
        raise ValueError("DOCUMENT_INTELLIGENCE_TEXT_REQUIRED")

    page_texts = text.split("\f")
    pages = tuple(
        DocumentPage(
            page_number=index,
            text=page_text.strip(),
            extraction_method="embedded_text",
        )
        for index, page_text in enumerate(page_texts, start=1)
        if page_text.strip()
    )
    if not pages:
        raise ValueError("DOCUMENT_INTELLIGENCE_TEXT_REQUIRED")

    canonical_uri = metadata.get("canonical_uri") or metadata.get("source_url")
    document = DocumentRecord(
        source_id=f"document-intelligence:revision:{revision_id}",
        title=title,
        pages=pages,
        canonical_uri=str(canonical_uri) if canonical_uri else None,
    )
    document.source_identity()
    return document
