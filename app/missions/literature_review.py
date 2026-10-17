"""Deterministic handler for the ``literature_ingestion_review`` mission.

The handler turns an owner-approved, bounded batch of bibliographic metadata
into a review packet for human reviewers. It is deliberately narrow:

* no model/provider call and no network access;
* no database read or write of its own (the mission framework stores the
  returned packet as the mission output manifest in ``oc_missions``);
* no canonical taxon lookup, so every record is routed to the human review
  queue with ``reconciliation_unavailable`` rather than an inferred identity;
* no scientific conclusion, approval, or publication: the packet is a staging
  artifact whose state is always ``awaiting_human_review``.

Malformed or out-of-contract manifests fail closed with ``ValueError`` so the
mission framework records a failed job instead of producing a partial packet.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

MAX_RECORDS = 100
ALLOWED_MANIFEST_KEYS = frozenset({"source", "records"})
ALLOWED_RECORD_KEYS = frozenset(
    {
        "source_record_id",
        "doi",
        "title",
        "authors",
        "publication_year",
        "taxon_name",
        "evidence_spans",
    }
)


def _invalid(detail: str) -> ValueError:
    return ValueError(f"LITERATURE_REVIEW_MANIFEST_INVALID:{detail}")


def validate_literature_review_manifest(
    manifest: Any,
) -> tuple[str, list[dict[str, Any]]]:
    """Return ``(source, records)`` or raise ``ValueError`` (fail closed)."""
    if not isinstance(manifest, Mapping):
        raise _invalid("manifest_not_object")
    unknown = sorted(set(manifest) - ALLOWED_MANIFEST_KEYS)
    if unknown:
        raise _invalid(f"unknown_manifest_keys={','.join(map(str, unknown))}")
    source = manifest.get("source")
    if not isinstance(source, str) or not source.strip():
        raise _invalid("source_required")
    records = manifest.get("records")
    if not isinstance(records, list) or not records:
        raise _invalid("records_required")
    if len(records) > MAX_RECORDS:
        raise _invalid(f"too_many_records>{MAX_RECORDS}")
    cleaned: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise _invalid(f"record_{index}_not_object")
        unknown_fields = sorted(set(record) - ALLOWED_RECORD_KEYS)
        if unknown_fields:
            raise _invalid(
                f"record_{index}_unknown_fields={','.join(map(str, unknown_fields))}"
            )
        spans = record.get("evidence_spans")
        if spans is not None and (
            not isinstance(spans, list)
            or not all(isinstance(span, Mapping) for span in spans)
        ):
            raise _invalid(f"record_{index}_evidence_spans_not_list_of_objects")
        cleaned.append(dict(record))
    return source.strip(), cleaned


def build_literature_ingestion_review(manifest: Any) -> dict[str, Any]:
    """Build a deterministic, human-review-only literature ingestion packet."""
    from runtime.literature_staging import stage_literature_batch

    source, records = validate_literature_review_manifest(manifest)
    # canonical_lookup=None: this mission has no taxonomy read authority, so it
    # never asserts a canonical identity; every record stays in review.
    result = stage_literature_batch(records, source=source, canonical_lookup=None)
    staged = [record.as_dict() for record in result.staged]
    review_queue = [item.as_dict() for item in result.review_queue]
    digest = hashlib.sha256(
        json.dumps(
            {"source": source, "staged": staged, "review_queue": review_queue},
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "status": "ok",
        "mission_type": "literature_ingestion_review",
        "artifact_type": "literature_ingestion_review_packet",
        "review_state": "awaiting_human_review",
        "human_review_required": True,
        "scientific_authority": "none",
        "scientific_conclusions_published": False,
        "approval_recorded": False,
        "provider_called": False,
        "external_network_called": False,
        "domain_database_written": False,
        "canonical_graph_mutated": False,
        "taxonomy_mutated": False,
        "summary": result.summary(),
        "staged_records": staged,
        "review_queue": review_queue,
        "packet_digest": digest,
    }
