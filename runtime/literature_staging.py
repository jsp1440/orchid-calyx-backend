"""Bounded literature staging pipeline with provenance preservation.

Augments literature extraction with bounded acquisition, canonical taxon
reconciliation, evidence-span preservation, and explicit review queues.
No production graph mutation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class LiteratureCheckpoint:
    job_key: str
    source: str
    offset: int
    processed: int
    completed: bool
    state: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StagedLiteratureRecord:
    source: str
    source_record_id: str
    doi: str | None
    title: str | None
    authors: tuple[str, ...]
    publication_year: int | None
    canonical_taxon_id: str | None
    taxon_name: str | None
    reconciliation_state: str
    evidence_spans: tuple[dict[str, Any], ...]
    content_hash: str | None
    source_url: str | None
    acquisition_checksum: str
    extraction_manifest: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["authors"] = list(result["authors"])
        result["evidence_spans"] = list(result["evidence_spans"])
        return result


@dataclass(frozen=True)
class LiteratureReviewItem:
    source: str
    source_record_id: str
    taxon_name: str | None
    reason: str
    review_state: str = "needs_taxon_resolution"
    suggested_action: str = "create_or_verify_canonical_crosswalk"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LiteratureStagingResult:
    staged: tuple[StagedLiteratureRecord, ...]
    review_queue: tuple[LiteratureReviewItem, ...]
    duplicate_skipped: int
    source: str
    batch_start: int
    batch_end: int
    checkpoint: dict[str, Any]
    idempotent: bool

    def summary(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "staged_count": len(self.staged),
            "review_queue_count": len(self.review_queue),
            "duplicate_skipped": self.duplicate_skipped,
            "batch_start": self.batch_start,
            "batch_end": self.batch_end,
            "checkpoint": dict(self.checkpoint),
            "idempotent": self.idempotent,
            "no_production_mutation": True,
            "candidate_knowledge_governance_intact": True,
        }


def _content_hash(text: str | None) -> str | None:
    return hashlib.sha256(text.encode()).hexdigest() if text else None


def _acquisition_checksum(source: str, source_record_id: str) -> str:
    return hashlib.sha256(f"{source}|{source_record_id}".encode()).hexdigest()[:16]


def _reconcile_taxon(
    taxon_name: str | None,
    canonical_lookup: Mapping[str, str] | None,
) -> tuple[str | None, str]:
    if canonical_lookup is None:
        return None, "reconciliation_unavailable"
    if not taxon_name or not taxon_name.strip():
        return None, "review_required"
    canonical_id = canonical_lookup.get(taxon_name.strip())
    return (canonical_id, "resolved") if canonical_id else (None, "unresolved")


def stage_literature_batch(
    records: Iterable[Mapping[str, Any]],
    *,
    source: str,
    batch_start: int = 0,
    seen_checksums: set[str] | None = None,
    canonical_lookup: Mapping[str, str] | None = None,
) -> LiteratureStagingResult:
    seen = seen_checksums if seen_checksums is not None else set()
    staged: list[StagedLiteratureRecord] = []
    review_queue: list[LiteratureReviewItem] = []
    duplicate_skipped = 0
    records_list = list(records)

    for record in records_list:
        src_id = str(record.get("source_record_id") or "")
        taxon_value = record.get("taxon_name") or record.get("accepted_name") or record.get("scientific_name")
        taxon_name = str(taxon_value) if taxon_value is not None else None
        if not src_id:
            review_queue.append(LiteratureReviewItem(
                source=source,
                source_record_id="unknown",
                taxon_name=taxon_name,
                reason="Missing source_record_id; cannot deduplicate.",
            ))
            continue

        acq_checksum = _acquisition_checksum(source, src_id)
        if acq_checksum in seen:
            duplicate_skipped += 1
            continue
        seen.add(acq_checksum)

        canonical_taxon_id, reconciliation_state = _reconcile_taxon(taxon_name, canonical_lookup)
        if reconciliation_state != "resolved":
            review_queue.append(LiteratureReviewItem(
                source=source,
                source_record_id=src_id,
                taxon_name=taxon_name,
                reason=f"Canonical taxon resolution required ({reconciliation_state}).",
            ))

        raw_text = record.get("raw_text")
        evidence_spans = tuple(
            dict(span)
            for span in (record.get("evidence_spans") or [])
            if isinstance(span, Mapping)
        )
        authors = tuple(str(author) for author in (record.get("authors") or []) if author)
        publication_year = record.get("publication_year")
        if publication_year is not None:
            try:
                publication_year = int(publication_year)
            except (TypeError, ValueError):
                publication_year = None

        staged.append(StagedLiteratureRecord(
            source=source,
            source_record_id=src_id,
            doi=record.get("doi"),
            title=record.get("title"),
            authors=authors,
            publication_year=publication_year,
            canonical_taxon_id=canonical_taxon_id,
            taxon_name=taxon_name,
            reconciliation_state=reconciliation_state,
            evidence_spans=evidence_spans,
            content_hash=_content_hash(raw_text) if isinstance(raw_text, str) else None,
            source_url=record.get("source_url"),
            acquisition_checksum=acq_checksum,
            extraction_manifest=dict(record.get("extraction_manifest") or {}),
            raw=dict(record.get("raw") or {}),
        ))

    batch_end = batch_start + len(records_list)
    idempotent = len(staged) == 0 and duplicate_skipped > 0
    checkpoint = {
        "source": source,
        "batch_start": batch_start,
        "batch_end": batch_end,
        "staged_count": len(staged),
        "idempotent": idempotent,
    }
    return LiteratureStagingResult(
        staged=tuple(staged),
        review_queue=tuple(review_queue),
        duplicate_skipped=duplicate_skipped,
        source=source,
        batch_start=batch_start,
        batch_end=batch_end,
        checkpoint=checkpoint,
        idempotent=idempotent,
    )
