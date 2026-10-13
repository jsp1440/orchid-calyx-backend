"""Fail-closed validation of a composition against its evidence packet.

The validator is independent of the composer: it re-derives what the packet
permits and refuses any result that cites something the packet does not hold,
cites an unanchored source, drops a declared conflict, answers a question the
packet cannot support, speaks about a different taxon, or leaks locality.
"""

from __future__ import annotations

from typing import Any

from .contracts import (
    FORBIDDEN_RESULT_KEYS,
    AnchorState,
    Composition,
    EvidencePacket,
    ResolutionState,
    ResultState,
)


def _keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, inner in value.items():
            found.add(str(key))
            found |= _keys(inner)
    elif isinstance(value, (list, tuple)):
        for inner in value:
            found |= _keys(inner)
    return found


def validate(packet: EvidencePacket, composition: Composition) -> tuple[str, ...]:
    violations: list[str] = []
    facet_refs = {i.ref for i in packet.facet_items()}
    resolved = packet.resolution.state in {
        ResolutionState.RESOLVED_ACCEPTED,
        ResolutionState.RESOLVED_VIA_SYNONYM,
    }
    for index, claim in enumerate(composition.claims):
        if not claim.refs:
            violations.append(f"CLAIM_{index}_UNCITED")
        for ref in claim.refs:
            item = packet.item(ref)
            if item is None:
                violations.append(f"CLAIM_{index}_CITES_UNKNOWN_REF:{ref}")
            elif ref not in facet_refs:
                violations.append(f"CLAIM_{index}_CITES_OUT_OF_FACET_REF:{ref}")
            elif item.anchor_state != AnchorState.ANCHORED:
                violations.append(f"CLAIM_{index}_CITES_UNANCHORED_REF:{ref}")
        if claim.subject_canonical_id != packet.resolution.accepted_canonical_id:
            violations.append(f"CLAIM_{index}_SUBJECT_NOT_CANONICAL_TAXON")

    required = {
        pair for pair in packet.conflicts if pair[0] in facet_refs or pair[1] in facet_refs
    }
    if not required <= set(composition.conflicts):
        violations.append("DECLARED_CONFLICT_DROPPED")
    if required and composition.state != ResultState.CONFLICT_REVIEW_REQUIRED:
        violations.append("CONFLICT_NOT_SURFACED_IN_STATE")

    supportable = resolved and any(
        packet.item(r).anchor_state == AnchorState.ANCHORED for r in facet_refs
    )
    if not supportable and composition.state != ResultState.INSUFFICIENT_EVIDENCE:
        violations.append("ANSWERED_WITHOUT_ANCHORED_EVIDENCE")
    if composition.state == ResultState.INSUFFICIENT_EVIDENCE and composition.claims:
        violations.append("ABSTENTION_WITH_CLAIMS")
    if composition.state == ResultState.VALIDATION_FAILED:
        violations.append("COMPOSER_CANNOT_SELF_ASSIGN_VALIDATION_FAILED")

    leaked = _keys([c.to_dict() for c in composition.claims]) & FORBIDDEN_RESULT_KEYS
    leaked |= _keys(packet.to_dict()) & FORBIDDEN_RESULT_KEYS
    if leaked:
        violations.append("FORBIDDEN_LOCALITY_KEYS:" + ",".join(sorted(leaked)))
    return tuple(violations)
