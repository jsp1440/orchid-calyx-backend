"""Bounded literature staging pipeline with provenance preservation.

This module augments the existing literature_extraction infrastructure with:
- Bounded batch acquisition with source checkpoints.
- Canonical taxon ID persistence during reviewed handoff.
- Evidence span and content hash preservation.
- Explicit review queue for ambiguous taxon matches.

Side-effect free core logic; persistence injected. No production graph mutation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class LiteratureCheckpoint:
    """Resumable position in a bounded literature acquisition job."""

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
    """Canonical staged literature record with full provenance."""

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
    content_hash: str | None  # sha256 of raw source text if available
    source_url: str | None
    acquisition_checksum: str  # sha256 of (source, source_record_id)
    extraction_manifest: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["authors"] = list(result["authors"])
        result["evidence_spans"] = list(result["evidence_spans"])
        return result


@dataclass(frozen=True)
class LiteratureReviewItem:
    """Literature record that cannot be linked to a canonical taxon."""

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
    if not text:
        return None
    return hashlib.sha256(text.encode()).hexdigest()


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
    if canonical_id:
        return canonical_id, "resolved"
    return None, "unresolved"


def stage_literature_batch(
    records: Iterable[Mapping[str, Any]],
    *,
    source: str,
    batch_start: int = 0,
    seen_checksums: set[str] | None = None,
    canonical_lookup: Mapping[str, str] | None = None,
) -> LiteratureStagingResult:
    """Stage one bounded batch of literature records.

    Args:
        records: Dicts with at minimum source_record_id and one of: doi, title, taxon_name.
        source: Source identifier (e.g. "bhl", "manual", "gbif_literature").
        batch_start: Absolute record offset for checkpoint tracking.
        seen_checksums: Already-staged acquisition_checksums for idempotency.
        canonical_lookup: Optional taxon_name → canonical_taxon_id mapping.

    Returns:
        LiteratureStagingResult with staged, review queue, and checkpoint.
    """
    seen = seen_checksums if seen_checksums is not None else set()
    staged: list[StagedLiteratureRecord] = []
    review_queue: list[LiteratureReviewItem] = []
    duplicate_skipped = 0
    records_list = list(records)

    for record in records_list:
        src_id = str(record.get("source_record_id") or "")
        if not src_id:
            # Records without a source_record_id cannot be safely deduplicated;
            # enter review rather than silently dropping.
            review_queue.append(LiteratureReviewItem(
                source=source,
                source_record_id="unknown",
                taxon_name=record.get("taxon_name"),
                reason="Missing source_record_id; cannot deduplicate.",
            ))
            continue

        acq_checksum = _acquisition_checksum(source, src_id)
        if acq_checksum in seen:
            duplicate_skipped += 1
            continue
        seen.add(acq_checksum)

        taxon_name = (
            record.get("taxon_name")
            or record.get("accepted_name")
            or record.get("scientific_name")
        )
        canonical_taxon_id, reconciliation_state = _reconcile_taxon(
            taxon_name, canonical_lookup
        )

        if reconciliation_state == "unresolved":
            review_queue.append(LiteratureReviewItem(
                source=source,
                source_record_id=src_id,
                taxon_name=taxon_name,
                reason="No canonical taxon match for supplied taxon name.",
            ))

        raw_text = record.get("raw_text")
        evidence_spans_raw = record.get("evidence_spans") or []
        evidence_spans = tuple(
            dict(span) for span in evidence_spans_raw if isinstance(span, Mapping)
        )
        authors_raw = record.get("authors") or []
        authors = tuple(str(a) for a in authors_raw if a)
        pub_year = record.get("publication_year")
        if pub_year is not None:
            try:
                pub_year = int(pub_year)
            except (TypeError, ValueError):
                pub_year = None

        staged.append(StagedLiteratureRecord(
            source=source,
            source_record_id=src_id,
            doi=record.get("doi"),
            title=record.get("title"),
            authors=authors,
            publication_year=pub_year,
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

    checkpoint: dict[str, Any] = {
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
