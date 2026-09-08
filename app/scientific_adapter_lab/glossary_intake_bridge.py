"""Bridge from literature GlossaryExtractor output to Lexicon intake staging.

OC-COMPLETE-007-glossary-intake-wire: Connect literature GlossaryExtractor
output to review-bound Lexicon intake staging so extracted concepts flow into
the governed concept store rather than remaining as unstructured extraction
output.

Rules (ALL MUST HOLD):
- Every staged record has status='candidate' — no auto-promotion.
- Canonical concept resolution happens downstream through human review.
- No database writes. Staging produces reviewable in-memory records.
- Source provenance (paper source hash, extractor version) is preserved.
- Duplicate terms across extraction runs are deduplicated by normalized term;
  highest confidence wins, provenance is merged.
- No credential values, no live model calls, no taxonomy activation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


BRIDGE_SCHEMA_VERSION = "oc-glossary-intake-bridge/v1"


@dataclass(frozen=True)
class GlossaryIntakeStagingRecord:
    """A single candidate concept record waiting for human review.

    Mirrors the field structure of the governed Lexicon intake manifest so
    a reviewer can decide which records to promote into the canonical concept
    store.  Never auto-promoted.
    """

    term_id: str
    term: str
    normalized_term: str
    status: str  # always "candidate"
    confidence: float
    source_hash: str
    extractor: str
    extractor_version: str
    mention_count: int
    concept_intake_state: str  # always "PENDING_REVIEW"
    review_required: bool  # always True
    auto_promotion_blocked: bool  # always True
    provenance_chain: tuple[str, ...]

    def validate(self) -> None:
        if self.status != "candidate":
            raise ValueError("INTAKE_STAGING_STATUS_MUST_BE_CANDIDATE")
        if self.concept_intake_state != "PENDING_REVIEW":
            raise ValueError("INTAKE_STAGING_CONCEPT_STATE_MUST_BE_PENDING_REVIEW")
        if not self.review_required:
            raise ValueError("INTAKE_STAGING_REVIEW_REQUIRED_MUST_BE_TRUE")
        if not self.auto_promotion_blocked:
            raise ValueError("INTAKE_STAGING_AUTO_PROMOTION_MUST_BE_BLOCKED")
        if self.confidence < 0.0 or self.confidence > 1.0:
            raise ValueError(f"INTAKE_STAGING_CONFIDENCE_OUT_OF_RANGE:{self.confidence}")
        if not self.term_id or not self.normalized_term:
            raise ValueError("INTAKE_STAGING_TERM_ID_AND_NORMALIZED_TERM_REQUIRED")

    def to_dict(self) -> dict[str, Any]:
        return {
            "term_id": self.term_id,
            "term": self.term,
            "normalized_term": self.normalized_term,
            "status": self.status,
            "confidence": self.confidence,
            "source_hash": self.source_hash,
            "extractor": self.extractor,
            "extractor_version": self.extractor_version,
            "mention_count": self.mention_count,
            "concept_intake_state": self.concept_intake_state,
            "review_required": self.review_required,
            "auto_promotion_blocked": self.auto_promotion_blocked,
            "provenance_chain": list(self.provenance_chain),
        }


@dataclass
class GlossaryIntakeStagingBatch:
    """Deduped, reviewable batch of staged concepts from one extraction run."""

    source_hash: str
    extractor: str
    extractor_version: str
    records: list[GlossaryIntakeStagingRecord] = field(default_factory=list)
    schema_version: str = BRIDGE_SCHEMA_VERSION
    auto_promotion_blocked: bool = True
    review_required: bool = True
    graph_mutation: bool = False

    def validate_all(self) -> list[str]:
        """Validate every record. Returns list of validation errors (empty = OK)."""
        errors: list[str] = []
        for rec in self.records:
            try:
                rec.validate()
            except ValueError as exc:
                errors.append(f"{rec.term_id}: {exc}")
        if self.graph_mutation:
            errors.append("BATCH_GRAPH_MUTATION_MUST_BE_FALSE")
        if not self.auto_promotion_blocked:
            errors.append("BATCH_AUTO_PROMOTION_MUST_BE_BLOCKED")
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_hash": self.source_hash,
            "extractor": self.extractor,
            "extractor_version": self.extractor_version,
            "record_count": len(self.records),
            "auto_promotion_blocked": self.auto_promotion_blocked,
            "review_required": self.review_required,
            "graph_mutation": self.graph_mutation,
            "records": [r.to_dict() for r in self.records],
        }

    def serialize_as_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=False)


def stage_glossary_terms_for_intake(
    glossary_terms: list[Any],  # list of GlossaryTerm from literature extraction
    *,
    source_hash: str,
    extractor: str = "glossary",
    extractor_version: str = "0.1.0",
) -> GlossaryIntakeStagingBatch:
    """Convert GlossaryTerm list to a reviewable intake staging batch.

    Deduplicates by normalized_term; highest confidence wins; mentions merged.
    Each output record is status='candidate', concept_intake_state='PENDING_REVIEW',
    auto_promotion_blocked=True.  No database writes.  No canonical promotion.

    Args:
        glossary_terms: GlossaryTerm objects from GlossaryExtractor.run()
        source_hash: Content hash of the source document (for provenance).
        extractor: Extractor name (default 'glossary').
        extractor_version: Extractor version string.

    Returns:
        GlossaryIntakeStagingBatch with deduped, review-bound staging records.
    """
    deduped: dict[str, dict[str, Any]] = {}

    for term in glossary_terms:
        norm = getattr(term, "normalized_term", None) or ""
        if not norm:
            continue
        if norm not in deduped:
            deduped[norm] = {
                "term_id": getattr(term, "term_id", f"glossary-{norm[:40]}"),
                "term": getattr(term, "term", norm),
                "normalized_term": norm,
                "confidence": float(getattr(term, "provenance", None) and getattr(term.provenance, "confidence", 0.0) or 0.0),
                "mention_count": len(getattr(term, "mentions", []) or []),
                "provenance_chain": [
                    f"source:{source_hash[:16]}",
                    f"extractor:{extractor}@{extractor_version}",
                ],
            }
        else:
            existing = deduped[norm]
            new_conf = float(
                getattr(term, "provenance", None)
                and getattr(term.provenance, "confidence", 0.0)
                or 0.0
            )
            existing["confidence"] = max(existing["confidence"], new_conf)
            existing["mention_count"] += len(getattr(term, "mentions", []) or [])

    records = [
        GlossaryIntakeStagingRecord(
            term_id=v["term_id"],
            term=v["term"],
            normalized_term=v["normalized_term"],
            status="candidate",
            confidence=v["confidence"],
            source_hash=source_hash,
            extractor=extractor,
            extractor_version=extractor_version,
            mention_count=v["mention_count"],
            concept_intake_state="PENDING_REVIEW",
            review_required=True,
            auto_promotion_blocked=True,
            provenance_chain=tuple(v["provenance_chain"]),
        )
        for v in sorted(deduped.values(), key=lambda d: d["normalized_term"])
    ]

    return GlossaryIntakeStagingBatch(
        source_hash=source_hash,
        extractor=extractor,
        extractor_version=extractor_version,
        records=records,
        auto_promotion_blocked=True,
        review_required=True,
        graph_mutation=False,
    )
