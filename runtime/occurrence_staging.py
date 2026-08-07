"""Bounded, resumable occurrence staging pipeline with taxon reconciliation.

This module is side-effect free for the core logic. Persistence, checkpoints,
and reconciliation outputs are injected. No production graph mutation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

SUPPORTED_SOURCES = frozenset({"gbif", "inaturalist"})
ALLOWED_LICENSES = frozenset({
    "CC0", "CC_BY", "CC_BY_NC", "CC_BY_SA", "CC_BY_NC_SA",
    "cc0", "cc-by", "cc-by-nc", "cc-by-sa", "cc-by-nc-sa",
    "http://creativecommons.org/publicdomain/zero/1.0/",
    "http://creativecommons.org/licenses/by/4.0/",
    "http://creativecommons.org/licenses/by-nc/4.0/",
    "http://creativecommons.org/licenses/by-sa/4.0/",
    "http://creativecommons.org/licenses/by-nc-sa/4.0/",
})


@dataclass(frozen=True)
class StagedOccurrence:
    source: str
    source_record_id: str
    scientific_name: str
    accepted_name: str | None
    taxon_key: str | None
    canonical_taxon_id: str | None
    reconciliation_state: str
    latitude: float | None
    longitude: float | None
    country_code: str | None
    locality: str | None
    event_date: str | None
    recorded_by: str | None
    license: str | None
    basis_of_record: str | None
    acquisition_checksum: str
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["event_date"] = str(result["event_date"]) if result["event_date"] else None
        return result


@dataclass(frozen=True)
class OccurrenceReviewItem:
    source: str
    source_record_id: str
    scientific_name: str
    reason: str
    review_state: str = "needs_taxon_resolution"
    suggested_action: str = "create_or_verify_canonical_crosswalk"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class OccurrenceStagingResult:
    staged: tuple[StagedOccurrence, ...]
    review_queue: tuple[OccurrenceReviewItem, ...]
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
        }


def _checksum(source: str, source_record_id: str, scientific_name: str) -> str:
    return hashlib.sha256(f"{source}|{source_record_id}|{scientific_name}".encode()).hexdigest()[:16]


def _reconcile_taxon(
    normalized: Mapping[str, Any],
    canonical_lookup: Mapping[str, str] | None,
) -> tuple[str | None, str]:
    if canonical_lookup is None:
        return None, "reconciliation_unavailable"
    accepted = str(normalized.get("accepted_name") or normalized.get("scientific_name") or "").strip()
    if not accepted:
        return None, "review_required"
    canonical_id = canonical_lookup.get(accepted)
    if canonical_id:
        return canonical_id, "resolved"
    scientific = str(normalized.get("scientific_name") or "").strip()
    canonical_id = canonical_lookup.get(scientific)
    if canonical_id:
        return canonical_id, "resolved"
    return None, "unresolved"


def stage_occurrence_batch(
    records: Iterable[Mapping[str, Any]],
    *,
    source: str,
    batch_start: int = 0,
    seen_checksums: set[str] | None = None,
    canonical_lookup: Mapping[str, str] | None = None,
) -> OccurrenceStagingResult:
    if source not in SUPPORTED_SOURCES:
        raise ValueError(f"unsupported occurrence source: {source!r}")

    seen = seen_checksums if seen_checksums is not None else set()
    staged: list[StagedOccurrence] = []
    review_queue: list[OccurrenceReviewItem] = []
    duplicate_skipped = 0
    records_list = list(records)

    for record in records_list:
        src_id = str(record.get("source_record_id") or "")
        sci_name = str(record.get("scientific_name") or "")
        if not src_id or not sci_name:
            review_queue.append(OccurrenceReviewItem(
                source=source,
                source_record_id=src_id or "unknown",
                scientific_name=sci_name or "unknown",
                reason="Missing source_record_id or scientific_name.",
            ))
            continue

        checksum = _checksum(source, src_id, sci_name)
        if checksum in seen:
            duplicate_skipped += 1
            continue
        seen.add(checksum)

        canonical_taxon_id, reconciliation_state = _reconcile_taxon(record, canonical_lookup)
        if reconciliation_state != "resolved":
            review_queue.append(OccurrenceReviewItem(
                source=source,
                source_record_id=src_id,
                scientific_name=sci_name,
                reason=f"Canonical taxon resolution required ({reconciliation_state}).",
            ))

        event_date = record.get("event_date")
        if hasattr(event_date, "isoformat"):
            event_date = event_date.isoformat()
        elif event_date is not None:
            event_date = str(event_date)

        staged.append(StagedOccurrence(
            source=source,
            source_record_id=src_id,
            scientific_name=sci_name,
            accepted_name=record.get("accepted_name"),
            taxon_key=record.get("taxon_key"),
            canonical_taxon_id=canonical_taxon_id,
            reconciliation_state=reconciliation_state,
            latitude=record.get("latitude"),
            longitude=record.get("longitude"),
            country_code=record.get("country_code"),
            locality=record.get("locality"),
            event_date=event_date,
            recorded_by=record.get("recorded_by"),
            license=record.get("license"),
            basis_of_record=record.get("basis_of_record"),
            acquisition_checksum=checksum,
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
    return OccurrenceStagingResult(
        staged=tuple(staged),
        review_queue=tuple(review_queue),
        duplicate_skipped=duplicate_skipped,
        source=source,
        batch_start=batch_start,
        batch_end=batch_end,
        checkpoint=checkpoint,
        idempotent=idempotent,
    )
