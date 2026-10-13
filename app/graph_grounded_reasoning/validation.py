"""Fail-closed validation of a composition against its evidence packet.

The validator is independent of the composer: it re-derives what the packet
permits and refuses any result that cites something the packet does not hold,
cites an unanchored source, drops a declared conflict, answers a question the
packet cannot support, speaks about a different taxon, or leaks locality.
"""

from __future__ import annotations

from app.calyx_flywheel.locality import (
    SensitiveLocalityError,
    assert_no_sensitive_locality,
)

from .contracts import (
    AnchorState,
    Composition,
    EvidencePacket,
    ResolutionState,
    ResultState,
)


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
    if not set(composition.conflicts) <= set(packet.conflicts):
        violations.append("UNDECLARED_CONFLICT_ASSERTED")
    cited = {ref for claim in composition.claims for ref in claim.refs}
    for pair in sorted(required):
        for ref in pair:
            item = packet.item(ref)
            if item is not None and item.anchor_state == AnchorState.ANCHORED and ref not in cited:
                violations.append(f"CONFLICT_ENDPOINT_NOT_CITED:{ref}")
    if required and composition.state != ResultState.CONFLICT_REVIEW_REQUIRED:
        violations.append("CONFLICT_NOT_SURFACED_IN_STATE")

    supportable = resolved and any(
        packet.item(r).anchor_state == AnchorState.ANCHORED for r in facet_refs
    )
    if not supportable and composition.state != ResultState.INSUFFICIENT_EVIDENCE:
        violations.append("ANSWERED_WITHOUT_ANCHORED_EVIDENCE")
    if composition.state == ResultState.CANDIDATE and any(
        packet.item(r).anchor_state != AnchorState.ANCHORED
        or packet.item(r).review_state != "APPROVED"
        or packet.item(r).verification_state != "VERIFIED"
        for r in facet_refs
    ):
        violations.append("CANDIDATE_WITH_UNREVIEWED_OR_UNANCHORED_EVIDENCE")
    if composition.state == ResultState.INSUFFICIENT_EVIDENCE and composition.claims:
        violations.append("ABSTENTION_WITH_CLAIMS")
    if composition.state == ResultState.VALIDATION_FAILED:
        violations.append("COMPOSER_CANNOT_SELF_ASSIGN_VALIDATION_FAILED")

    try:
        assert_no_sensitive_locality(
            {"claims": [c.to_dict() for c in composition.claims], "packet": packet.to_dict()}
        )
    except SensitiveLocalityError as exc:
        violations.append(f"FORBIDDEN_LOCALITY_KEYS:{exc}")
    return tuple(violations)
