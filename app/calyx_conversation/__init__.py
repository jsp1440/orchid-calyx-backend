"""Conversational analysis surface for Calyx.

This package also carries one bounded compatibility guard for the live
external-literature coverage gate.  Retrieval volume is not scientific
evidence: a non-empty list of unverified search hits must not suppress targeted
review-bound literature discovery.
"""

from __future__ import annotations

from typing import Any

from . import external_literature as _external_literature


def _has_usable_local_evidence(records: list[dict[str, Any]]) -> bool:
    """Return True only for rows carrying an explicit governed-evidence signal.

    Fail toward additional review-bound discovery when the retrieval schema is
    ambiguous. External literature remains REVIEW_REQUIRED and cannot publish or
    mutate the knowledge graph automatically, so treating an unknown row as
    insufficient is safer than promoting search volume into evidence coverage.
    """

    accepted_verification_states = {
        "VERIFIED",
        "CANONICAL",
        "CURATED",
        "PUBLISHED",
        "ACCEPTED",
    }
    accepted_review_states = {"VERIFIED", "APPROVED", "PUBLISHED"}

    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("canonical_evidence") is True:
            return True

        canonical_parent = record.get("canonical_parent")
        if isinstance(canonical_parent, dict):
            if canonical_parent.get("available") is True and canonical_parent.get("id"):
                return True

        verification_state = str(record.get("verification_state") or "").upper().strip()
        if verification_state in accepted_verification_states:
            return True

        review_state = str(record.get("review_state") or "").upper().strip()
        if review_state in accepted_review_states:
            return True

    return False


_original_augment_retrieval_with_external_literature = (
    _external_literature.augment_retrieval_with_external_literature
)


def _augment_retrieval_with_governed_local_coverage(
    retrieval: dict[str, Any],
    query: str,
    *,
    limit: int = 8,
) -> dict[str, Any]:
    """Keep unverified local hits visible without letting them suppress discovery."""

    local_results = retrieval.get("results") or []
    if not local_results or _has_usable_local_evidence(local_results):
        return _original_augment_retrieval_with_external_literature(
            retrieval,
            query,
            limit=limit,
        )

    # The existing implementation uses presence of ``results`` as its coverage
    # gate. Temporarily hide only those non-evidence rows from that gate, then
    # restore them unchanged so callers retain the complete local retrieval.
    discovery_input = dict(retrieval)
    discovery_input["results"] = []
    result = _original_augment_retrieval_with_external_literature(
        discovery_input,
        query,
        limit=limit,
    )
    result["results"] = local_results
    result["local_coverage_evidence_usable"] = False

    if result.get("status") == "local_empty_external_literature_available":
        result["status"] = str(retrieval.get("status") or "available")
    return result


_external_literature.augment_retrieval_with_external_literature = (
    _augment_retrieval_with_governed_local_coverage
)
