"""Governed contributor-image intake for Matrix evidence acquisition.

Contributor photographs are preserved exactly as submitted: the original object
is never modified, re-encoded, or moved by this pipeline. Every staged image
carries contributor attribution, an explicit permission grant, a rights-holder
affirmation, taxonomic uncertainty, and full provenance.

Batch ingestion is idempotent (content-checksum dedup) and needs no manual
per-image handling. This module performs no production graph, taxonomy, or
object-store mutation; persistence of staged records is the caller's concern.

Alignment: complements runtime/image_staging.py (provider-licensed GBIF /
iNaturalist staging) with the distinct contributor-direct permission model,
where the contributor affirms rights and grants permission explicitly rather
than inheriting a provider license allowlist.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

SCHEMA_VERSION = "contributor-image-intake/v1"

PERMISSION_GRANTS = frozenset({
    "cc0",
    "cc-by",
    "cc-by-sa",
    "cc-by-nc",
    "cc-by-nc-sa",
    "all-rights-reserved-view-only",
    "all-rights-reserved-research-use",
})

TAXON_CERTAINTY_STATES = frozenset({
    "determined_by_contributor",
    "suggested",
    "unknown",
})

SUPPORTED_MEDIA = frozenset({
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/tiff",
})

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

_LICENSE_LABELS = {
    "cc0": "CC0",
    "cc-by": "CC-BY",
    "cc-by-sa": "CC-BY-SA",
    "cc-by-nc": "CC-BY-NC",
    "cc-by-nc-sa": "CC-BY-NC-SA",
    "all-rights-reserved-view-only": "All rights reserved (view only)",
    "all-rights-reserved-research-use": "All rights reserved (research use)",
}


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class StagedContributorImage:
    schema_version: str
    submission_id: str
    batch_id: str
    contributor_id: str
    contributor_display_name: str
    attribution_line: str
    permission_grant: str
    rights_holder_affirmed: bool
    original_object_ref: str
    content_sha256: str
    mime_type: str
    taxon_name: str | None
    taxon_certainty: str
    candidate_taxa: tuple[dict[str, Any], ...]
    canonical_taxon_id: str | None
    reconciliation_state: str
    provenance: dict[str, Any]
    staged_at: str
    original_preserved: bool = True

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class RejectedContributorSubmission:
    submission_id: str
    contributor_id: str | None
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ContributorReviewItem:
    submission_id: str
    taxon_name: str | None
    reason: str
    review_state: str = "needs_taxon_resolution"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ContributorIntakeResult:
    batch_id: str
    staged: tuple[StagedContributorImage, ...]
    rejected: tuple[RejectedContributorSubmission, ...]
    review_queue: tuple[ContributorReviewItem, ...]
    duplicate_skipped: int
    idempotent: bool

    def summary(self) -> dict[str, Any]:
        return {
            "batch_id": self.batch_id,
            "staged_count": len(self.staged),
            "rejected_count": len(self.rejected),
            "review_queue_count": len(self.review_queue),
            "duplicate_skipped": self.duplicate_skipped,
            "idempotent": self.idempotent,
            "original_preserved": True,
            "no_production_mutation": True,
        }


def _reconcile_taxon(
    taxon_name: str | None,
    canonical_lookup: Mapping[str, str] | None,
) -> tuple[str | None, str]:
    """Resolve against the supplied canonical lookup only; never guess a taxon."""
    if not taxon_name or not taxon_name.strip():
        return None, "unresolved"
    if canonical_lookup is None:
        return None, "reconciliation_unavailable"
    canonical_id = canonical_lookup.get(taxon_name.strip())
    return (canonical_id, "resolved") if canonical_id else (None, "unresolved")


def _normalized_candidates(raw: Any) -> tuple[dict[str, Any], ...]:
    if not isinstance(raw, (list, tuple)):
        return ()
    candidates: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, Mapping) and item.get("name"):
            entry = {"name": str(item["name"]).strip()}
            if item.get("taxon_id"):
                entry["taxon_id"] = str(item["taxon_id"]).strip()
            candidates.append(entry)
    return tuple(candidates)


def intake_contributor_batch(
    submissions: Iterable[Mapping[str, Any]],
    *,
    batch_id: str,
    seen_checksums: set[str] | None = None,
    canonical_lookup: Mapping[str, str] | None = None,
    staged_at: str | None = None,
) -> ContributorIntakeResult:
    """Stage one batch of contributor submissions under governance rules.

    Idempotent: a submission whose content checksum was already staged (in this
    or a previous batch sharing ``seen_checksums``) is skipped, not duplicated.
    """
    if not str(batch_id).strip():
        raise ValueError("batch_id is required")
    seen = seen_checksums if seen_checksums is not None else set()
    staged: list[StagedContributorImage] = []
    rejected: list[RejectedContributorSubmission] = []
    review_queue: list[ContributorReviewItem] = []
    duplicate_skipped = 0

    for submission in submissions:
        submission_id = str(submission.get("submission_id") or "").strip()
        contributor_id = submission.get("contributor_id")
        contributor_id = str(contributor_id).strip() if contributor_id else None

        def _reject(reason: str) -> None:
            rejected.append(
                RejectedContributorSubmission(
                    submission_id=submission_id or "unknown",
                    contributor_id=contributor_id,
                    reason=reason,
                )
            )

        if not submission_id:
            _reject("missing_submission_id")
            continue
        display_name = str(submission.get("contributor_display_name") or "").strip()
        if not contributor_id or not display_name:
            _reject("contributor_attribution_required")
            continue
        permission = str(submission.get("permission_grant") or "").strip().lower()
        if permission not in PERMISSION_GRANTS:
            _reject("missing_or_unrecognized_permission_grant")
            continue
        if submission.get("rights_holder_affirmed") is not True:
            _reject("rights_holder_affirmation_required")
            continue
        original_ref = str(submission.get("original_object_ref") or "").strip()
        if not original_ref:
            _reject("original_object_ref_required")
            continue
        content_sha256 = str(submission.get("content_sha256") or "").strip().lower()
        if not _SHA256_RE.fullmatch(content_sha256):
            _reject("content_sha256_must_be_lowercase_hex_sha256")
            continue
        mime_type = str(submission.get("mime_type") or "").strip().lower()
        if mime_type not in SUPPORTED_MEDIA:
            _reject("unsupported_media_type")
            continue
        taxon_certainty = str(submission.get("taxon_certainty") or "unknown").strip()
        if taxon_certainty not in TAXON_CERTAINTY_STATES:
            _reject("unrecognized_taxon_certainty")
            continue

        if content_sha256 in seen:
            duplicate_skipped += 1
            continue
        seen.add(content_sha256)

        taxon_name_raw = submission.get("taxon_name")
        taxon_name = str(taxon_name_raw).strip() if taxon_name_raw else None
        canonical_taxon_id, reconciliation_state = _reconcile_taxon(
            taxon_name, canonical_lookup
        )
        if reconciliation_state != "resolved":
            review_queue.append(
                ContributorReviewItem(
                    submission_id=submission_id,
                    taxon_name=taxon_name,
                    reason=f"Canonical taxon resolution required ({reconciliation_state}).",
                )
            )

        provenance = dict(submission.get("provenance") or {})
        provenance.update(
            {
                "intake_schema": SCHEMA_VERSION,
                "batch_id": str(batch_id),
                "intake_channel": provenance.get("channel", "contributor-submission"),
            }
        )
        license_label = _LICENSE_LABELS.get(permission, permission.upper())
        staged.append(
            StagedContributorImage(
                schema_version=SCHEMA_VERSION,
                submission_id=submission_id,
                batch_id=str(batch_id),
                contributor_id=contributor_id,
                contributor_display_name=display_name,
                attribution_line=f"{display_name} ({license_label})",
                permission_grant=permission,
                rights_holder_affirmed=True,
                original_object_ref=original_ref,
                content_sha256=content_sha256,
                mime_type=mime_type,
                taxon_name=taxon_name,
                taxon_certainty=taxon_certainty,
                candidate_taxa=_normalized_candidates(submission.get("candidate_taxa")),
                canonical_taxon_id=canonical_taxon_id,
                reconciliation_state=reconciliation_state,
                provenance=provenance,
                staged_at=staged_at or _now(),
            )
        )

    return ContributorIntakeResult(
        batch_id=str(batch_id),
        staged=tuple(staged),
        rejected=tuple(rejected),
        review_queue=tuple(review_queue),
        duplicate_skipped=duplicate_skipped,
        idempotent=len(staged) == 0 and duplicate_skipped > 0,
    )
