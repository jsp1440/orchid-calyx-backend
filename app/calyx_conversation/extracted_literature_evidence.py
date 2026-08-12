"""Read-only bridge from canonical literature documents to reviewed extraction output.

The canonical source binding is the authority connecting a literature document id
to a ``PaperKnowledge`` extraction bundle.  This module follows that binding,
re-verifies source integrity, and exposes only normalized evidence records whose
publication decision is ``eligible_for_publication``.  It never promotes records,
changes review state, or writes to either storage layer.
"""

from __future__ import annotations

import os
from typing import Any, Iterable

from app.literature_extraction.repository import LiteratureResultRepository
from app.literature_extraction.source_binding import (
    FileLiteratureSourceBindingRepository,
    LiteratureSourceBindingError,
)

LITERATURE_SOURCE_OBJECT_TYPE = "LITERATURE_DOCUMENT"
MAX_DOCUMENTS = 8
MAX_RECORDS_PER_DOCUMENT = 12


def _root() -> str:
    return os.getenv("LITERATURE_EXTRACTION_ROOT", "runtime/literature_extraction")


def reviewed_evidence_for_documents(
    document_ids: Iterable[int | str],
    *,
    root: str | None = None,
    max_documents: int = MAX_DOCUMENTS,
    max_records_per_document: int = MAX_RECORDS_PER_DOCUMENT,
) -> dict[str, Any]:
    """Return integrity-verified, publication-eligible normalized evidence."""
    ids: list[int] = []
    seen: set[int] = set()
    for raw in document_ids:
        try:
            value = int(raw)
        except (TypeError, ValueError):
            continue
        if value <= 0 or value in seen:
            continue
        seen.add(value)
        ids.append(value)
        if len(ids) >= max(1, min(int(max_documents), 50)):
            break

    if not ids:
        return {
            "status": "not_requested",
            "read_only": True,
            "documents": {},
            "reviewed_record_count": 0,
        }

    resolved_root = root or _root()
    papers = LiteratureResultRepository(resolved_root)
    bindings = FileLiteratureSourceBindingRepository(resolved_root)
    documents: dict[str, Any] = {}
    total = 0
    record_limit = max(1, min(int(max_records_per_document), 50))

    for document_id in ids:
        matched_bindings = bindings.find_by_source_object(
            LITERATURE_SOURCE_OBJECT_TYPE,
            document_id,
            limit=4,
        )
        if not matched_bindings:
            documents[str(document_id)] = {
                "status": "no_canonical_extraction_binding",
                "records": [],
            }
            continue

        document_records: list[dict[str, Any]] = []
        binding_summaries: list[dict[str, Any]] = []
        integrity_failures: list[str] = []
        for binding in matched_bindings:
            paper = papers.get(binding.paper_id)
            raw_bytes = papers.get_raw_bytes(binding.paper_id)
            if paper is None or raw_bytes is None:
                integrity_failures.append(f"{binding.paper_id}:EXTRACTION_BUNDLE_INCOMPLETE")
                continue
            try:
                binding.validate_integrity(paper, raw_bytes)
            except LiteratureSourceBindingError as exc:
                integrity_failures.append(f"{binding.paper_id}:{exc.code}")
                continue

            eligible_ids = {
                item.source_record_id
                for item in paper.publication_decisions
                if item.status == "eligible_for_publication"
            }
            records = {
                item.record_id: item for item in paper.normalized_evidence_records
            }
            binding_summaries.append(
                {
                    "paper_id": binding.paper_id,
                    "revision_id": binding.revision_id,
                    "extraction_run_id": binding.extraction_run_id,
                    "binding_fingerprint": binding.fingerprint,
                    "source_hash": paper.source.content_hash,
                    "title": paper.metadata.title,
                    "publication_year": paper.metadata.publication_year,
                }
            )
            for record_id in sorted(eligible_ids):
                record = records.get(record_id)
                if record is None:
                    continue
                anchors = [
                    binding.evidence_integrity[evidence_id]
                    for evidence_id in record.evidence_ids
                    if evidence_id in binding.evidence_integrity
                ]
                document_records.append(
                    {
                        "paper_id": binding.paper_id,
                        "record_id": record.record_id,
                        "source_claim_id": record.source_claim_id,
                        "statement": record.statement,
                        "normalized_statement": record.normalized_statement,
                        "domain": record.domain,
                        "polarity": record.polarity,
                        "canonical_entity_ids": list(record.canonical_entity_ids),
                        "unresolved_entities": list(record.unresolved_entities),
                        "extraction_confidence": record.extraction_confidence,
                        "normalization_confidence": record.normalization_confidence,
                        "review_status": record.review_status,
                        "source_excerpts": list(record.source_excerpts),
                        "evidence_anchors": anchors,
                        "publication_status": "eligible_for_publication",
                        "scientific_claim_inferred": False,
                    }
                )
                if len(document_records) >= record_limit:
                    break
            if len(document_records) >= record_limit:
                break

        status = "available" if document_records else "no_publication_eligible_evidence"
        if not binding_summaries and integrity_failures:
            status = "integrity_validation_failed"
        documents[str(document_id)] = {
            "status": status,
            "bindings": binding_summaries,
            "integrity_failures": integrity_failures,
            "records": document_records,
        }
        total += len(document_records)

    return {
        "status": "available",
        "contract": "calyx-reviewed-literature-evidence-bridge-v1",
        "read_only": True,
        "automatic_publication": False,
        "candidate_promotion": False,
        "documents": documents,
        "reviewed_record_count": total,
    }
