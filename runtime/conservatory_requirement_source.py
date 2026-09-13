"""Adapting stored trait candidates into the shape the requirement resolver reads.

WHY AN ADAPTER RATHER THAN A SHARED SHAPE

The candidate store and the requirement resolver were written for different
jobs and do not agree on how a claim looks. The store keeps a candidate's
anchors in a separate evidence_links table keyed by candidate id, records no
verification state at all, and expresses supersession as an `active` flag. The
resolver wants one dict per claim carrying its own anchors.

Bridging that in the resolver would have coupled it to the store's internals.
Bridging it here keeps both sides readable and puts the translation somewhere a
reader can check it against the storage it claims to describe.

WHAT IT REFUSES TO INVENT

The store has no verification_state, so nothing here reports one. A candidate
that has not been through review arrives as unverified, which is what it is.
Claiming otherwise would manufacture the exact assurance the resolver exists to
report honestly.

A candidate with no evidence links yields no anchors, and the resolver then
refuses it. That is correct: a trait claim whose supporting evidence was never
linked cannot be traced, and an untraceable number is indistinguishable from an
invented one.
"""

from __future__ import annotations

from typing import Any

from runtime.conservatory_taxon_requirements import REQUIREMENT_PREDICATES

__all__ = ["TRAIT_KIND", "collect_trait_candidates"]

#: The candidate kind that carries cultivation traits.
TRAIT_KIND = "TRAIT"


def _anchor_ids(links: list[dict[str, Any]], candidate_id: Any) -> list[int]:
    ids: list[int] = []
    for link in links:
        if link.get("candidate_id") != candidate_id:
            continue
        anchor = link.get("anchor") or {}
        anchor_id = anchor.get("anchor_id")
        if anchor_id is not None:
            ids.append(anchor_id)
    return sorted(set(ids))


def _revision_id(links: list[dict[str, Any]], candidate_id: Any) -> int | None:
    for link in links:
        if link.get("candidate_id") == candidate_id:
            revision = link.get("revision_id")
            if revision is not None:
                return revision
    return None


def collect_trait_candidates(
    taxon: str | None,
    *,
    candidates: list[dict[str, Any]] | None,
    evidence_links: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return stored trait candidates for a taxon in the resolver's shape.

    Only active candidates are returned. A superseded one describes what the
    Continuum used to think, and feeding it forward would let a corrected claim
    keep competing with the claim that corrected it.
    """
    if not taxon or not str(taxon).strip():
        return []

    subject = str(taxon).strip()
    links = evidence_links or []
    collected: list[dict[str, Any]] = []

    for candidate in candidates or []:
        if candidate.get("kind") != TRAIT_KIND:
            continue
        if not candidate.get("active"):
            continue
        # Matched case-insensitively: the store normalises subjects, and a
        # collection recording "Cattleya skinneri" should reach evidence filed
        # under the same name in a different case rather than silently missing.
        if (
            str(candidate.get("normalized_subject", "")).strip().lower()
            != subject.lower()
        ):
            continue
        if candidate.get("predicate") not in REQUIREMENT_PREDICATES:
            continue

        collected.append(
            {
                "predicate": candidate.get("predicate"),
                "numeric_value": candidate.get("numeric_value"),
                "unit": candidate.get("unit"),
                "source_anchor_ids": _anchor_ids(links, candidate.get("candidate_id")),
                "source_revision_id": _revision_id(
                    links, candidate.get("candidate_id")
                ),
                # The store records no verification state. Reporting one would
                # manufacture the assurance the resolver exists to report
                # honestly, so the field is simply absent and the resolver
                # reads it as unverified.
                "review_state": candidate.get("review_state"),
                "status": "ACTIVE",
                "directness": candidate.get("extraction_method") or "INDIRECT",
                "confidence": candidate.get("confidence"),
            }
        )

    return collected
