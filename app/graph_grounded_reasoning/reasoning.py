"""Deterministic, provider-free composition over an evidence packet.

The composer only restates packet items; it never adds knowledge.  State
selection follows the SCIAN-002 fail-closed order (missing anchors ->
INSUFFICIENT_EVIDENCE, conflict -> CONFLICT_REVIEW_REQUIRED, unverified or
unreviewed -> REVIEW_REQUIRED, otherwise CANDIDATE).  A future model-backed
composer must satisfy the same ``Composer`` signature and is gated by the same
validator.
"""

from __future__ import annotations

from collections.abc import Callable

from .contracts import (
    AnchorState,
    Claim,
    Composition,
    EvidencePacket,
    ResolutionState,
    ResultState,
)

Composer = Callable[[EvidencePacket], Composition]


def _statement(item) -> str:
    relation = item.edge_type.replace("_", " ")
    qualifier = f" ({item.qualifier})" if item.qualifier else ""
    return f"{item.subject} {relation} {item.object_label}{qualifier}"


def compose(packet: EvidencePacket) -> Composition:
    uncertainty: list[str] = []
    resolution = packet.resolution
    if resolution.state == ResolutionState.RESOLVED_VIA_SYNONYM:
        uncertainty.append(
            f"SYNONYM_RESOLVED:{resolution.via_synonym}->{resolution.accepted_name}"
        )
    if resolution.state not in {
        ResolutionState.RESOLVED_ACCEPTED,
        ResolutionState.RESOLVED_VIA_SYNONYM,
    }:
        return Composition(
            state=ResultState.INSUFFICIENT_EVIDENCE,
            claims=(),
            conflicts=(),
            uncertainty=(f"TAXON_{resolution.state.value}",),
            gaps=packet.gaps,
        )

    facet_items = packet.facet_items()
    anchored = [i for i in facet_items if i.anchor_state == AnchorState.ANCHORED]
    gaps = list(packet.gaps)
    if not facet_items:
        gaps.append(f"NO_GRAPH_EVIDENCE_FOR_FACET:{packet.question.facet.value}")
    elif not anchored:
        gaps.append("NO_ANCHORED_SOURCE_FOR_FACET")
    if not anchored:
        return Composition(
            state=ResultState.INSUFFICIENT_EVIDENCE,
            claims=(),
            conflicts=(),
            uncertainty=tuple(uncertainty),
            gaps=tuple(gaps),
        )

    refs = {i.ref for i in facet_items}
    conflicts = tuple(p for p in packet.conflicts if p[0] in refs or p[1] in refs)
    claims = tuple(
        Claim(
            statement=_statement(item),
            subject_canonical_id=resolution.accepted_canonical_id,
            refs=(item.ref,),
        )
        for item in anchored
    )
    unanchored = len(facet_items) - len(anchored)
    if unanchored:
        uncertainty.append(f"UNANCHORED_ASSERTIONS_EXCLUDED:{unanchored}")
    unreviewed = [
        i
        for i in anchored
        if i.review_state != "APPROVED" or i.verification_state != "VERIFIED"
    ]
    if unreviewed:
        uncertainty.append(f"UNREVIEWED_OR_UNVERIFIED_ASSERTIONS:{len(unreviewed)}")
    if conflicts:
        uncertainty.append(f"DECLARED_CONFLICTS:{len(conflicts)}")
        state = ResultState.CONFLICT_REVIEW_REQUIRED
    elif unanchored or unreviewed:
        state = ResultState.REVIEW_REQUIRED
    else:
        state = ResultState.CANDIDATE
    if len(anchored) == 1:
        uncertainty.append("SINGLE_SOURCE")
    return Composition(
        state=state,
        claims=claims,
        conflicts=conflicts,
        uncertainty=tuple(uncertainty),
        gaps=tuple(gaps),
    )
