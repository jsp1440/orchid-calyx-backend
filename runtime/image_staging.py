"""Bounded licensed-image staging pipeline with allowlist enforcement.

This module is side-effect free for the core logic. All persistence is injected.
Unlicensed or unsupported media is explicitly rejected — never silently dropped.
No production graph mutation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

# Normalized license identifiers accepted for public staging.
ALLOWED_LICENSE_PATTERNS = frozenset({
    "cc0",
    "cc-by",
    "cc-by-sa",
    "cc-by-nc",
    "cc-by-nc-sa",
    "http://creativecommons.org/publicdomain/zero/1.0/",
    "https://creativecommons.org/publicdomain/zero/1.0/",
    "http://creativecommons.org/licenses/by/4.0/",
    "https://creativecommons.org/licenses/by/4.0/",
    "http://creativecommons.org/licenses/by-sa/4.0/",
    "https://creativecommons.org/licenses/by-sa/4.0/",
    "http://creativecommons.org/licenses/by-nc/4.0/",
    "https://creativecommons.org/licenses/by-nc/4.0/",
    "http://creativecommons.org/licenses/by-nc-sa/4.0/",
    "https://creativecommons.org/licenses/by-nc-sa/4.0/",
    # Legacy 3.0
    "http://creativecommons.org/licenses/by/3.0/",
    "http://creativecommons.org/licenses/by-sa/3.0/",
    "http://creativecommons.org/licenses/by-nc/3.0/",
    "http://creativecommons.org/licenses/by-nc-sa/3.0/",
})

SUPPORTED_SOURCES = frozenset({"gbif", "inaturalist"})


def _normalise_license(raw: str | None) -> str | None:
    if not raw:
        return None
    return raw.strip().lower()


def _is_allowed_license(raw: str | None) -> bool:
    normalized = _normalise_license(raw)
    if not normalized:
        return False
    return normalized in ALLOWED_LICENSE_PATTERNS


@dataclass(frozen=True)
class StagedImage:
    """Canonical staged image record with full provenance."""

    source: str
    source_record_id: str
    url: str
    canonical_taxon_id: str | None
    taxon_name: str | None
    reconciliation_state: str
    provider: str
    license: str
    attribution: str | None
    checksum: str  # sha256 of url for dedup
    acquisition_checksum: str  # sha256 of (source, source_record_id)
    thumbnail_url: str | None = None
    mime_type: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RejectedImage:
    """Image explicitly rejected due to missing or unsupported license."""

    source: str
    source_record_id: str
    url: str | None
    reason: str
    license_raw: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ImageReviewItem:
    """Image that could not be linked to a canonical taxon."""

    source: str
    source_record_id: str
    taxon_name: str | None
    reason: str
    review_state: str = "needs_taxon_resolution"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ImageStagingResult:
    staged: tuple[StagedImage, ...]
    rejected: tuple[RejectedImage, ...]
    review_queue: tuple[ImageReviewItem, ...]
    duplicate_skipped: int
    source: str
    idempotent: bool

    def summary(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "staged_count": len(self.staged),
            "rejected_count": len(self.rejected),
            "review_queue_count": len(self.review_queue),
            "duplicate_skipped": self.duplicate_skipped,
            "idempotent": self.idempotent,
            "no_production_mutation": True,
        }


def _url_checksum(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:16]


def _acquisition_checksum(source: str, source_record_id: str) -> str:
    return hashlib.sha256(f"{source}|{source_record_id}".encode()).hexdigest()[:16]


def _reconcile_image_taxon(
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


def stage_image_batch(
    images: Iterable[Mapping[str, Any]],
    *,
    source: str,
    seen_checksums: set[str] | None = None,
    canonical_lookup: Mapping[str, str] | None = None,
) -> ImageStagingResult:
    """Stage one bounded batch of normalized image records.

    Args:
        images: Normalized image dicts (from harvester extract_images output).
        source: Source name ("gbif" or "inaturalist").
        seen_checksums: Set of already-staged acquisition_checksums for idempotency.
        canonical_lookup: Optional taxon_name → canonical_taxon_id mapping.

    Returns:
        ImageStagingResult with staged, rejected, and review queues.
    """
    if source not in SUPPORTED_SOURCES:
        raise ValueError(f"unsupported image source: {source!r}")

    seen = seen_checksums if seen_checksums is not None else set()
    staged: list[StagedImage] = []
    rejected: list[RejectedImage] = []
    review_queue: list[ImageReviewItem] = []
    duplicate_skipped = 0

    for img in images:
        src_id = str(img.get("source_record_id") or "")
        url = str(img.get("url") or "")
        license_raw = img.get("license")

        if not src_id:
            rejected.append(RejectedImage(
                source=source,
                source_record_id=src_id or "unknown",
                url=url or None,
                reason="Missing source_record_id.",
                license_raw=str(license_raw) if license_raw is not None else None,
            ))
            continue

        if not url:
            rejected.append(RejectedImage(
                source=source,
                source_record_id=src_id,
                url=None,
                reason="Missing image URL.",
                license_raw=str(license_raw) if license_raw is not None else None,
            ))
            continue

        if not _is_allowed_license(license_raw):
            rejected.append(RejectedImage(
                source=source,
                source_record_id=src_id,
                url=url,
                reason="License not in allowlist or missing.",
                license_raw=str(license_raw) if license_raw is not None else None,
            ))
            continue

        acq_checksum = _acquisition_checksum(source, src_id)
        if acq_checksum in seen:
            duplicate_skipped += 1
            continue
        seen.add(acq_checksum)

        taxon_name = img.get("taxon_name") or img.get("scientific_name") or img.get("accepted_name")
        canonical_taxon_id, reconciliation_state = _reconcile_image_taxon(
            taxon_name, canonical_lookup
        )

        if reconciliation_state == "unresolved":
            review_queue.append(ImageReviewItem(
                source=source,
                source_record_id=src_id,
                taxon_name=taxon_name,
                reason="No canonical taxon match for supplied taxon name.",
            ))

        staged.append(StagedImage(
            source=source,
            source_record_id=src_id,
            url=url,
            canonical_taxon_id=canonical_taxon_id,
            taxon_name=taxon_name,
            reconciliation_state=reconciliation_state,
            provider=str(img.get("publisher") or img.get("source") or source),
            license=str(_normalise_license(license_raw)),
            attribution=img.get("creator"),
            checksum=_url_checksum(url),
            acquisition_checksum=acq_checksum,
            thumbnail_url=img.get("thumbnail_url"),
            mime_type=img.get("mime_type"),
            raw=dict(img.get("raw") or {}),
        ))

    idempotent = len(staged) == 0 and duplicate_skipped > 0
    return ImageStagingResult(
        staged=tuple(staged),
        rejected=tuple(rejected),
        review_queue=tuple(review_queue),
        duplicate_skipped=duplicate_skipped,
        source=source,
        idempotent=idempotent,
    )
