"""Bounded literature acquisition pipeline for the Orchid Continuum harvest layer.

Responsibilities
----------------
* Accept DOI or URL acquisition requests up to a configurable bound.
* Persist raw source text, extraction manifest, evidence spans, source binding,
  and content hashes — all keyed by a stable document identity.
* Resolve scientific names to canonical taxon IDs during the reviewed handoff;
  route ambiguous matches to the review queue instead of the graph.
* Project accepted records to a staging store with full provenance.
* Replay is idempotent (same document identity → upsert, not duplicate insert).
* Keep review queues and candidate-knowledge governance intact — never mutate
  the production graph directly.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator, Mapping, Sequence


# ---------------------------------------------------------------------------
# Domain models
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class AcquisitionRequest:
    """Input descriptor for a single document to acquire."""

    document_id: str          # stable caller-assigned ID
    source_type: str          # "doi" | "url"
    source_ref: str           # the DOI string or URL
    raw_text: str | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class EvidenceSpan:
    """Positional reference into a raw source document."""

    span_id: str
    text: str
    page_start: int | None = None
    page_end: int | None = None
    char_start: int | None = None
    char_end: int | None = None
    entity_ids: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class AcquiredLiteratureRecord:
    """Canonical durable record for a single acquired literature document."""

    record_id: str                # sha256(source_type + ":" + source_ref)
    document_id: str
    source_type: str
    source_ref: str
    raw_source: str | None        # raw text / OCR output
    content_hash: str             # sha256 of raw_source (or source_ref when absent)
    extraction_manifest: Mapping[str, Any]   # extractor name → status/counts
    evidence_spans: tuple[EvidenceSpan, ...]
    source_binding: Mapping[str, Any]        # DOI/URL provenance
    acquired_at: datetime
    canonical_taxon_ids: tuple[str, ...]     # resolved during handoff
    taxon_review_pending: bool               # True when any entity is ambiguous
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LiteratureStagingRecord:
    """Projection into the staging store after successful handoff."""

    record_id: str
    document_id: str
    source_type: str
    source_ref: str
    content_hash: str
    canonical_taxon_ids: tuple[str, ...]
    taxon_review_pending: bool
    staged_at: datetime


# ---------------------------------------------------------------------------
# Review-queue entry
# ---------------------------------------------------------------------------


@dataclass(slots=True, frozen=True)
class LiteratureReviewItem:
    record_id: str
    document_id: str
    source_ref: str
    unresolved_names: tuple[str, ...]
    queued_at: datetime


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class AcquisitionBoundExceeded(Exception):
    """Raised when the acquisition bound is reached before all requests complete."""


class LiteratureAcquisitionError(Exception):
    """Raised when a single request cannot be fulfilled."""

    def __init__(self, reason: str, request: AcquisitionRequest) -> None:
        super().__init__(reason)
        self.reason = reason
        self.request = request


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------


class LiteratureAcquisitionPipeline:
    """Bounded DOI/URL acquisition pipeline with source checkpoints.

    Parameters
    ----------
    bound:
        Maximum number of documents to acquire in a single run.  Defaults to
        ``100``.  Set to ``None`` to disable the bound (test/migration use).
    taxon_resolver:
        Optional callable ``(name: str) -> str | None``.  Returns a canonical
        taxon ID or ``None`` for ambiguous matches.
    extractor:
        Optional callable ``(request: AcquisitionRequest) -> dict[str, Any]``
        that returns ``{"spans": [...], "manifest": {...}}``.
    """

    def __init__(
        self,
        *,
        bound: int | None = 100,
        taxon_resolver: Any | None = None,
        extractor: Any | None = None,
    ) -> None:
        self._bound = bound
        self._taxon_resolver = taxon_resolver
        self._extractor = extractor

        # Durable stores
        self._records: dict[str, AcquiredLiteratureRecord] = {}
        self._staging: dict[str, LiteratureStagingRecord] = {}
        self._review_queue: list[LiteratureReviewItem] = []
        self._checkpoint: dict[str, Any] = {}   # source-level resumable state

        self._acquired_ids: list[str] = []
        self._rejected: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def acquire(self, requests: Sequence[AcquisitionRequest]) -> dict[str, Any]:
        """Acquire a bounded sequence of documents and return run statistics."""
        count = 0
        for req in requests:
            if self._bound is not None and count >= self._bound:
                raise AcquisitionBoundExceeded(
                    f"acquisition bound of {self._bound} reached"
                )
            try:
                record = self._process(req)
            except LiteratureAcquisitionError as exc:
                self._rejected.append({"reason": exc.reason, "document_id": req.document_id})
                continue

            record_id = record.record_id
            if record_id not in self._records:
                self._records[record_id] = record
                if record.taxon_review_pending:
                    self._enqueue_review(record)

            self._acquired_ids.append(record_id)
            self._project_to_staging(record)
            self._save_checkpoint(req, record_id)
            count += 1

        return self.statistics()

    def staging(self) -> list[LiteratureStagingRecord]:
        """Return all staged records ordered by record_id."""
        return sorted(self._staging.values(), key=lambda r: r.record_id)

    def review_queue(self) -> list[LiteratureReviewItem]:
        return list(self._review_queue)

    def rejected(self) -> list[dict[str, Any]]:
        return list(self._rejected)

    def checkpoint(self) -> dict[str, Any]:
        """Return current source-level checkpoint state."""
        return dict(self._checkpoint)

    def statistics(self) -> dict[str, Any]:
        return {
            "acquired": len(self._acquired_ids),
            "rejected": len(self._rejected),
            "staged": len(self._staging),
            "taxon_review_pending": len(self._review_queue),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _process(self, req: AcquisitionRequest) -> AcquiredLiteratureRecord:
        if req.source_type not in {"doi", "url"}:
            raise LiteratureAcquisitionError("unsupported_source_type", req)
        if not req.source_ref.strip():
            raise LiteratureAcquisitionError("empty_source_ref", req)

        raw_source = req.raw_text
        content_hash = hashlib.sha256(
            (raw_source or req.source_ref).encode()
        ).hexdigest()

        # Run extractor when available
        if self._extractor is not None:
            extraction = self._extractor(req)
        else:
            extraction = {"spans": [], "manifest": {"default": "skipped"}}

        spans = tuple(
            _build_span(s, i) for i, s in enumerate(extraction.get("spans") or [])
        )
        manifest = dict(extraction.get("manifest") or {})

        source_binding: dict[str, Any] = {
            "source_type": req.source_type,
            "source_ref": req.source_ref,
            "acquired_at": datetime.now(timezone.utc).isoformat(),
        }

        # Taxon resolution from metadata / span entities
        candidate_names = list(_extract_names(req))
        canonical_ids, unresolved = self._resolve_taxa(candidate_names)
        # A record is review-pending when names are unresolved OR when no
        # canonical taxon ID could be established at all.
        taxon_review_pending = bool(unresolved) or not canonical_ids

        record_id = hashlib.sha256(
            f"{req.source_type}:{req.source_ref}".encode()
        ).hexdigest()

        return AcquiredLiteratureRecord(
            record_id=record_id,
            document_id=req.document_id,
            source_type=req.source_type,
            source_ref=req.source_ref,
            raw_source=raw_source,
            content_hash=content_hash,
            extraction_manifest=manifest,
            evidence_spans=spans,
            source_binding=source_binding,
            acquired_at=datetime.now(timezone.utc),
            canonical_taxon_ids=tuple(canonical_ids),
            taxon_review_pending=taxon_review_pending,
            metadata=dict(req.metadata),
        )

    def _resolve_taxa(
        self, names: list[str]
    ) -> tuple[list[str], list[str]]:
        resolved: list[str] = []
        unresolved: list[str] = []
        for name in names:
            if self._taxon_resolver is None:
                unresolved.append(name)
                continue
            taxon_id = self._taxon_resolver(name)
            if taxon_id:
                resolved.append(str(taxon_id))
            else:
                unresolved.append(name)
        return resolved, unresolved

    def _enqueue_review(self, record: AcquiredLiteratureRecord) -> None:
        unresolved = list(
            _extract_names(
                AcquisitionRequest(
                    document_id=record.document_id,
                    source_type=record.source_type,
                    source_ref=record.source_ref,
                    metadata=record.metadata,
                )
            )
        )
        self._review_queue.append(
            LiteratureReviewItem(
                record_id=record.record_id,
                document_id=record.document_id,
                source_ref=record.source_ref,
                unresolved_names=tuple(unresolved),
                queued_at=datetime.now(timezone.utc),
            )
        )

    def _project_to_staging(self, record: AcquiredLiteratureRecord) -> None:
        self._staging[record.record_id] = LiteratureStagingRecord(
            record_id=record.record_id,
            document_id=record.document_id,
            source_type=record.source_type,
            source_ref=record.source_ref,
            content_hash=record.content_hash,
            canonical_taxon_ids=record.canonical_taxon_ids,
            taxon_review_pending=record.taxon_review_pending,
            staged_at=datetime.now(timezone.utc),
        )

    def _save_checkpoint(
        self, req: AcquisitionRequest, record_id: str
    ) -> None:
        self._checkpoint[req.document_id] = {
            "record_id": record_id,
            "source_ref": req.source_ref,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _build_span(raw: Any, index: int) -> EvidenceSpan:
    if not isinstance(raw, Mapping):
        raw = {}
    return EvidenceSpan(
        span_id=str(raw.get("span_id") or f"span:{index}"),
        text=str(raw.get("text") or ""),
        page_start=_int_or_none(raw.get("page_start")),
        page_end=_int_or_none(raw.get("page_end")),
        char_start=_int_or_none(raw.get("char_start")),
        char_end=_int_or_none(raw.get("char_end")),
        entity_ids=tuple(raw.get("entity_ids") or ()),
    )


def _extract_names(req: AcquisitionRequest) -> Iterator[str]:
    """Yield scientific names found in request metadata."""
    meta = req.metadata
    for key in ("scientific_names", "taxa"):
        value = meta.get(key)
        if isinstance(value, (list, tuple)):
            for item in value:
                name = str(item).strip()
                if name:
                    yield name
    for key in ("scientific_name", "taxon_name"):
        value = meta.get(key)
        if isinstance(value, str) and value.strip():
            yield value.strip()


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
