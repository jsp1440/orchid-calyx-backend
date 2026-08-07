"""Bounded licensed-image staging pipeline with allowlist enforcement.

All persistence is injected. Unsupported media is explicitly rejected.
No production graph mutation.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

ALLOWED_LICENSE_PATTERNS = frozenset({
    "cc0", "cc-by", "cc-by-sa", "cc-by-nc", "cc-by-nc-sa",
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
    "http://creativecommons.org/licenses/by/3.0/",
    "http://creativecommons.org/licenses/by-sa/3.0/",
    "http://creativecommons.org/licenses/by-nc/3.0/",
    "http://creativecommons.org/licenses/by-nc-sa/3.0/",
})
SUPPORTED_SOURCES = frozenset({"gbif", "inaturalist"})


def _normalise_license(raw: str | None) -> str | None:
    return raw.strip().lower() if raw else None


def _is_allowed_license(raw: str | None) -> bool:
    normalized = _normalise_license(raw)
    return bool(normalized and normalized in ALLOWED_LICENSE_PATTERNS)


@dataclass(frozen=True)
class StagedImage:
    source: str
    source_record_id: str
    url: str
    canonical_taxon_id: str | None
    taxon_name: str | None
    reconciliation_state: str
    provider: str
    license: str
    attribution: str | None
    checksum: str
    acquisition_checksum: str
    thumbnail_url: str | None = None
    mime_type: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RejectedImage:
    source: str
    source_record_id: str
    url: str | None
    reason: str
    license_raw: str | None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ImageReviewItem:
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
    return (canonical_id, "resolved") if canonical_id else (None, "unresolved")


def stage_image_batch(
    images: Iterable[Mapping[str, Any]],
    *,
    source: str,
    seen_checksums: set[str] | None = None,
    canonical_lookup: Mapping[str, str] | None = None,
) -> ImageStagingResult:
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
        license_text = str(license_raw) if license_raw is not None else None

        if not src_id:
            rejected.append(RejectedImage(source, "unknown", url or None, "Missing source_record_id.", license_text))
            continue
        if not url:
            rejected.append(RejectedImage(source, src_id, None, "Missing image URL.", license_text))
            continue
        if not _is_allowed_license(license_text):
            rejected.append(RejectedImage(source, src_id, url, "License not in allowlist or missing.", license_text))
            continue

        acq_checksum = _acquisition_checksum(source, src_id)
        if acq_checksum in seen:
            duplicate_skipped += 1
            continue
        seen.add(acq_checksum)

        taxon_name = img.get("taxon_name") or img.get("scientific_name") or img.get("accepted_name")
        canonical_taxon_id, reconciliation_state = _reconcile_image_taxon(
            str(taxon_name) if taxon_name is not None else None,
            canonical_lookup,
        )
        if reconciliation_state == "unresolved":
            review_queue.append(ImageReviewItem(
                source=source,
                source_record_id=src_id,
                taxon_name=str(taxon_name) if taxon_name is not None else None,
                reason="No canonical taxon match for supplied taxon name.",
            ))

        normalized_license = _normalise_license(license_text)
        if normalized_license is None:
            raise AssertionError("validated image license unexpectedly absent")
        staged.append(StagedImage(
            source=source,
            source_record_id=src_id,
            url=url,
            canonical_taxon_id=canonical_taxon_id,
            taxon_name=str(taxon_name) if taxon_name is not None else None,
            reconciliation_state=reconciliation_state,
            provider=str(img.get("publisher") or img.get("source") or source),
            license=normalized_license,
            attribution=img.get("creator"),
            checksum=_url_checksum(url),
            acquisition_checksum=acq_checksum,
            thumbnail_url=img.get("thumbnail_url"),
            mime_type=img.get("mime_type"),
            raw=dict(img.get("raw") or {}),
        ))

    return ImageStagingResult(
        staged=tuple(staged),
        rejected=tuple(rejected),
        review_queue=tuple(review_queue),
        duplicate_skipped=duplicate_skipped,
        source=source,
        idempotent=len(staged) == 0 and duplicate_skipped > 0,
    )
