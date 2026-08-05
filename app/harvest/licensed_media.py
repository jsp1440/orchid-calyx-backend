"""Durable licensed-image pipeline for the Orchid Continuum harvest layer.

Responsibilities
----------------
* Enforce an explicit license allowlist before any media record is accepted.
* Persist accepted records with full provenance (provider, provider record ID,
  source URL, license, attribution, checksum, acquisition time).
* Link accepted records to canonical taxon IDs (or queue them for review when
  the taxon match is ambiguous).
* Project accepted records to a bounded staging store (idempotent replay).
* Reject unsupported or unlicensed media explicitly.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


# ---------------------------------------------------------------------------
# License allowlist
# ---------------------------------------------------------------------------

#: Explicit set of license identifiers that the pipeline accepts.
#: All other values are rejected.
LICENSE_ALLOWLIST: frozenset[str] = frozenset(
    {
        "CC0",
        "CC_BY",
        "CC_BY_2_0",
        "CC_BY_4_0",
        "CC_BY_NC",
        "CC_BY_NC_2_0",
        "CC_BY_NC_4_0",
        "CC_BY_SA",
        "CC_BY_SA_2_0",
        "CC_BY_SA_4_0",
        "CC_BY_NC_SA",
        "CC_BY_NC_SA_4_0",
        "PUBLIC_DOMAIN",
    }
)


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class LicensedMediaRecord:
    """Canonical durable record for a single accepted media asset."""

    record_id: str                  # sha256(provider + ":" + provider_record_id)
    provider: str                   # e.g. "gbif", "inat", "bhl"
    provider_record_id: str
    source_url: str
    license: str                    # normalised allowlisted value
    attribution: str | None
    checksum: str                   # sha256 of source_url (stable surrogate)
    acquired_at: datetime
    taxon_id: str | None            # canonical taxon ID (None → queued for review)
    taxon_review_pending: bool      # True when taxon match is ambiguous
    mime_type: str | None = None
    thumbnail_url: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class MediaStagingRecord:
    """Projection of a :class:`LicensedMediaRecord` into the staging store."""

    record_id: str
    provider: str
    provider_record_id: str
    source_url: str
    license: str
    attribution: str | None
    taxon_id: str | None
    taxon_review_pending: bool
    staged_at: datetime


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class LicensedImageRejected(Exception):
    """Raised when a raw media record is explicitly rejected by the pipeline."""

    def __init__(self, reason: str, record: Mapping[str, Any]) -> None:
        super().__init__(reason)
        self.reason = reason
        self.record = record


class LicensedImagePipeline:
    """Bounded source-to-staging pipeline for licensed media records.

    Parameters
    ----------
    allowlist:
        Set of accepted license strings.  Defaults to :data:`LICENSE_ALLOWLIST`.
    taxon_resolver:
        Optional callable ``(scientific_name: str) -> str | None``.  Returns
        the canonical taxon ID or *None* when the match is ambiguous.  When
        omitted every record is queued for taxon review.
    """

    def __init__(
        self,
        *,
        allowlist: frozenset[str] | None = None,
        taxon_resolver: Any | None = None,
    ) -> None:
        self._allowlist = allowlist if allowlist is not None else LICENSE_ALLOWLIST
        self._taxon_resolver = taxon_resolver

        # Durable stores (in-memory for tests; swap for DB-backed impls)
        self._media_store: dict[str, LicensedMediaRecord] = {}
        self._staging: dict[str, MediaStagingRecord] = {}
        self._review_queue: list[LicensedMediaRecord] = []

        self._accepted: list[str] = []
        self._rejected: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest(self, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """Ingest a sequence of raw media dicts and return run statistics."""
        for raw in records:
            try:
                media = self._validate_and_build(raw)
            except LicensedImageRejected as exc:
                self._rejected.append({"reason": exc.reason, "record": dict(raw)})
                continue

            # Idempotent — existing records are not overwritten
            if media.record_id not in self._media_store:
                self._media_store[media.record_id] = media
                if media.taxon_review_pending:
                    self._review_queue.append(media)

            self._accepted.append(media.record_id)
            self._project_to_staging(media)

        return self.statistics()

    def staging(self) -> list[MediaStagingRecord]:
        """Return all staged records (stable ordering by record_id)."""
        return sorted(self._staging.values(), key=lambda r: r.record_id)

    def review_queue(self) -> list[LicensedMediaRecord]:
        """Return records queued for taxon review."""
        return list(self._review_queue)

    def rejected(self) -> list[dict[str, Any]]:
        """Return all explicitly rejected raw records with their reasons."""
        return list(self._rejected)

    def statistics(self) -> dict[str, Any]:
        return {
            "accepted": len(self._accepted),
            "rejected": len(self._rejected),
            "staged": len(self._staging),
            "taxon_review_pending": len(self._review_queue),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_and_build(self, raw: Mapping[str, Any]) -> LicensedMediaRecord:
        provider = str(raw.get("source") or raw.get("provider") or "").strip()
        provider_record_id = str(
            raw.get("source_record_id") or raw.get("provider_record_id") or ""
        ).strip()
        source_url = str(raw.get("url") or raw.get("source_url") or "").strip()
        license_value = _normalise_license(
            str(raw.get("license") or raw.get("license_code") or "").strip()
        )

        if not provider:
            raise LicensedImageRejected("missing_provider", raw)
        if not provider_record_id:
            raise LicensedImageRejected("missing_provider_record_id", raw)
        if not source_url:
            raise LicensedImageRejected("missing_source_url", raw)
        if not license_value:
            raise LicensedImageRejected("missing_license", raw)
        if license_value not in self._allowlist:
            raise LicensedImageRejected(
                f"license_not_allowed:{license_value}", raw
            )

        record_id = _stable_record_id(provider, provider_record_id)
        checksum = hashlib.sha256(source_url.encode()).hexdigest()
        attribution = _coerce_str(
            raw.get("attribution") or raw.get("creator") or raw.get("publisher")
        )
        taxon_id, taxon_review_pending = self._resolve_taxon(raw)

        return LicensedMediaRecord(
            record_id=record_id,
            provider=provider,
            provider_record_id=provider_record_id,
            source_url=source_url,
            license=license_value,
            attribution=attribution,
            checksum=checksum,
            acquired_at=datetime.now(timezone.utc),
            taxon_id=taxon_id,
            taxon_review_pending=taxon_review_pending,
            mime_type=_coerce_str(raw.get("mime_type") or raw.get("type")),
            thumbnail_url=_coerce_str(raw.get("thumbnail_url") or raw.get("thumbnail")),
            raw=dict(raw),
        )

    def _resolve_taxon(
        self, raw: Mapping[str, Any]
    ) -> tuple[str | None, bool]:
        """Return (canonical_taxon_id, review_pending)."""
        # Prefer an explicit taxon_id already present in the record
        explicit = _coerce_str(raw.get("taxon_id") or raw.get("taxonKey"))
        if explicit:
            return explicit, False

        if self._taxon_resolver is None:
            return None, True

        scientific_name = _coerce_str(
            raw.get("scientific_name") or raw.get("acceptedScientificName")
        )
        if not scientific_name:
            return None, True

        resolved = self._taxon_resolver(scientific_name)
        if resolved:
            return str(resolved), False
        return None, True

    def _project_to_staging(self, media: LicensedMediaRecord) -> None:
        """Upsert a staging projection (idempotent)."""
        self._staging[media.record_id] = MediaStagingRecord(
            record_id=media.record_id,
            provider=media.provider,
            provider_record_id=media.provider_record_id,
            source_url=media.source_url,
            license=media.license,
            attribution=media.attribution,
            taxon_id=media.taxon_id,
            taxon_review_pending=media.taxon_review_pending,
            staged_at=datetime.now(timezone.utc),
        )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _stable_record_id(provider: str, provider_record_id: str) -> str:
    return hashlib.sha256(f"{provider}:{provider_record_id}".encode()).hexdigest()


def _normalise_license(raw: str) -> str:
    """Normalise common license URI/token variants to canonical allowlist tokens."""
    if not raw:
        return ""
    upper = raw.upper().strip()
    # Strip URI prefixes
    for prefix in (
        "HTTP://CREATIVECOMMONS.ORG/LICENSES/",
        "HTTPS://CREATIVECOMMONS.ORG/LICENSES/",
        "HTTP://CREATIVECOMMONS.ORG/PUBLICDOMAIN/",
        "HTTPS://CREATIVECOMMONS.ORG/PUBLICDOMAIN/",
    ):
        if upper.startswith(prefix):
            upper = upper[len(prefix):]
            break
    # Strip trailing version/deed fragments
    for suffix in ("/DEED", "/LEGALCODE", "/DEED.EN", "/"):
        if upper.endswith(suffix):
            upper = upper[: -len(suffix)]
    # Normalise separators (dots in version strings become underscores too)
    upper = upper.replace("/", "_").replace("-", "_").replace(" ", "_").replace(".", "_")
    # Map well-known abbreviations
    _alias: dict[str, str] = {
        "BY_4_0": "CC_BY_4_0",
        "BY": "CC_BY",
        "BY_2_0": "CC_BY_2_0",
        "BY_NC_4_0": "CC_BY_NC_4_0",
        "BY_NC": "CC_BY_NC",
        "BY_NC_2_0": "CC_BY_NC_2_0",
        "BY_SA_4_0": "CC_BY_SA_4_0",
        "BY_SA": "CC_BY_SA",
        "BY_SA_2_0": "CC_BY_SA_2_0",
        "BY_NC_SA_4_0": "CC_BY_NC_SA_4_0",
        "BY_NC_SA": "CC_BY_NC_SA",
        "ZERO_1_0": "CC0",
        "ZERO": "CC0",
        "CC0_1_0": "CC0",
        "PUBLICDOMAIN_ZERO_1_0": "CC0",
        "MARK_1_0": "PUBLIC_DOMAIN",
        "MARK": "PUBLIC_DOMAIN",
    }
    return _alias.get(upper, upper)


def _coerce_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
