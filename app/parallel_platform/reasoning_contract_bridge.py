"""Bridge from Brain reasoning_contracts types to BrainCandidateHandoffRequest.

Converts an oc-verification-handoff-v1 packet (produced by
`calyx_brain.reasoning_contracts.build_verification_packet`) into a
`BrainCandidateHandoffRequest` so the Brain contract layer can flow into the
canonical candidate-knowledge pipeline.

The caller must supply integer database IDs (`source_object_id`, `revision_id`,
`extraction_run_id`) because Brain contracts use string identifiers and the
backend requires database-scoped integer keys.

All governance flags from the verification packet are preserved in the
`provenance` and `qualifiers` fields of the resulting handoff request.
"""

from __future__ import annotations

from typing import Any, Literal

from .brain_candidate_handoff import BrainCandidateHandoffRequest, BrainEvidenceAnchor

DomainLiteral = Literal[
    "taxonomy",
    "trait",
    "morphology",
    "ecology",
    "geography",
    "phenology",
    "conservation",
    "measurement",
    "molecular",
    "cultivation",
]


def verification_packet_to_handoff_request(
    verification_packet: dict[str, Any],
    *,
    domain: DomainLiteral,
    source_object_type: str,
    source_object_id: int,
    revision_id: int,
    extraction_run_id: int,
) -> BrainCandidateHandoffRequest:
    """Convert an oc-verification-handoff-v1 packet to BrainCandidateHandoffRequest.

    Parameters
    ----------
    verification_packet:
        Output of `calyx_brain.reasoning_contracts.build_verification_packet`.
        Must carry `contract_version == "oc-verification-handoff-v1"` and
        `human_review_required == True`.
    domain:
        Candidate knowledge domain for this observation (e.g. "cultivation").
    source_object_type:
        Backend object type string identifying the source record type.
    source_object_id:
        Integer primary key of the source record in the backend database.
    revision_id:
        Integer revision ID of the source record.
    extraction_run_id:
        Integer extraction run ID under which this handoff is recorded.

    Returns
    -------
    BrainCandidateHandoffRequest
        Ready to pass to `handoff_brain_candidate()`.

    Raises
    ------
    ValueError
        If the packet version is unsupported, governance flags are violated,
        or required candidate fields are missing or empty.
    """
    if verification_packet.get("contract_version") != "oc-verification-handoff-v1":
        raise ValueError("UNSUPPORTED_VERIFICATION_PACKET")
    if verification_packet.get("human_review_required") is not True:
        raise ValueError("PACKET_GOVERNANCE_INVALID")
    if verification_packet.get("automatic_scientific_publication_allowed") is not False:
        raise ValueError("PACKET_GOVERNANCE_INVALID")
    if verification_packet.get("canonical_knowledge_mutation_allowed") is not False:
        raise ValueError("PACKET_GOVERNANCE_INVALID")
    if verification_packet.get("verification_state") != "ready_for_review":
        raise ValueError("PACKET_NOT_READY_FOR_REVIEW")

    reasoning = verification_packet.get("reasoning") or {}
    candidate = reasoning.get("candidate_knowledge") or {}

    candidate_id = str(candidate.get("candidate_id") or "").strip()
    subject_id = str(candidate.get("subject_id") or "").strip()
    predicate = str(candidate.get("predicate") or "").strip()
    object_id = str(candidate.get("object_id") or "").strip()

    if not candidate_id:
        raise ValueError("CANDIDATE_ID_REQUIRED")
    if not subject_id:
        raise ValueError("SUBJECT_ID_REQUIRED")
    if not predicate:
        raise ValueError("PREDICATE_REQUIRED")
    if not object_id:
        raise ValueError("OBJECT_ID_REQUIRED")

    confidence = float(candidate.get("confidence") or 0.0)

    resolved = list(verification_packet.get("resolved_evidence") or [])
    if not resolved:
        raise ValueError("RESOLVED_EVIDENCE_REQUIRED")

    statements: list[str] = []
    anchors: list[BrainEvidenceAnchor] = []
    anchor_id = 1

    for ev in resolved:
        stmt = str(ev.get("statement") or "").strip()
        if stmt:
            statements.append(stmt)
        evidence_id = str(ev.get("evidence_id") or "")
        for prov_item in ev.get("provenance") or []:
            anchors.append(
                BrainEvidenceAnchor(
                    anchor_id=anchor_id,
                    logical_unit=str(prov_item),
                    locator={
                        "evidence_id": evidence_id,
                        "provenance_item": str(prov_item),
                    },
                )
            )
            anchor_id += 1

    if not anchors:
        anchors = [
            BrainEvidenceAnchor(
                anchor_id=1,
                logical_unit=candidate_id,
                locator={"candidate_id": candidate_id},
            )
        ]

    evidence_text = "\n\n".join(statements) or object_id

    return BrainCandidateHandoffRequest(
        reasoning_id=candidate_id,
        domain=domain,
        subject=subject_id,
        predicate=predicate,
        object_value=object_id,
        confidence=confidence,
        evidence_text=evidence_text,
        source_object_type=source_object_type,
        source_object_id=source_object_id,
        revision_id=revision_id,
        extraction_run_id=extraction_run_id,
        source_anchors=anchors,
        provenance={
            "contract_version": "oc-verification-handoff-v1",
            "candidate_id": candidate_id,
            "contradictions": list(verification_packet.get("contradictions") or []),
            "knowledge_gap_count": len(
                list(verification_packet.get("knowledge_gaps") or [])
            ),
            "missing_evidence_count": len(
                list(verification_packet.get("missing_evidence") or [])
            ),
        },
        qualifiers={
            "human_review_required": True,
            "automatic_scientific_publication_allowed": False,
            "canonical_knowledge_mutation_allowed": False,
        },
    )
